from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from cryptography.fernet import Fernet
from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl, field_validator

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "arrmedic"
CONFIG_DIR = Path(os.environ.get("ARRMEDIC_CONFIG_DIR", str(DEFAULT_CONFIG_DIR)))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR / "arrmedic.db"
KEY_PATH = CONFIG_DIR / "secret.key"
SESSION_COOKIE = "arrmedic_session"
SESSION_DAYS = 30
APP_VERSION = "0.6.0"
MAX_SAVED_SCANS = 50

API_VERSION_ORDER = {
    "sonarr": ("v3", "v1"),
    "radarr": ("v3", "v1"),
    "whisparr": ("v3", "v1"),
    "prowlarr": ("v1", "v3"),
    "lidarr": ("v1", "v3"),
    "readarr": ("v1", "v3"),
}

app = FastAPI(
    title="ArrMedic",
    version=APP_VERSION,
    description="Open-source diagnostics and health monitoring for the *Arr media stack.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def prevent_stale_ui(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


ServiceKind = Literal["sonarr", "radarr", "prowlarr", "lidarr", "readarr", "whisparr"]


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                url TEXT NOT NULL,
                api_key_enc TEXT NOT NULL,
                version TEXT,
                os_name TEXT,
                api_version TEXT,
                last_checked TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS diagnostic_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                score INTEGER,
                service_count INTEGER NOT NULL,
                online_count INTEGER NOT NULL,
                issue_count INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(instances)")}
        if "api_version" not in columns:
            conn.execute("ALTER TABLE instances ADD COLUMN api_version TEXT")
        if "last_checked" not in columns:
            conn.execute("ALTER TABLE instances ADD COLUMN last_checked TEXT")


def cipher() -> Fernet:
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(Fernet.generate_key())
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
    return Fernet(KEY_PATH.read_bytes().strip())


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def issue_session(response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(),))
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires.isoformat()),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


def require_user(session: str | None) -> sqlite3.Row:
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    token_hash = hashlib.sha256(session.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Session expired")
    return row


class SetupRequest(BaseModel):
    username: str
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def username_rules(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3 or len(value) > 40:
            raise ValueError("Username must be 3-40 characters")
        return value

    @field_validator("password")
    @classmethod
    def password_rules(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str


class InstanceRequest(BaseModel):
    name: str
    kind: ServiceKind
    url: HttpUrl
    api_key: str

    @field_validator("name", "api_key")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required")
        return value


class InstanceUpdateRequest(BaseModel):
    name: str
    kind: ServiceKind
    url: HttpUrl
    api_key: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Service name is required")
        return value


def instance_payload(row: sqlite3.Row) -> InstanceRequest:
    try:
        api_key = cipher().decrypt(row["api_key_enc"].encode()).decode()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to decrypt the saved API key") from exc
    return InstanceRequest(name=row["name"], kind=row["kind"], url=row["url"], api_key=api_key)


def get_instance(instance_id: int) -> sqlite3.Row:
    with db() as conn:
        row = conn.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return row


def api_versions(kind: str, preferred: str | None = None) -> list[str]:
    ordered = list(API_VERSION_ORDER.get(kind, ("v3", "v1")))
    if preferred and preferred in ordered:
        ordered.remove(preferred)
        ordered.insert(0, preferred)
    return ordered


async def arr_get(
    payload: InstanceRequest,
    endpoint: str,
    *,
    preferred_version: str | None = None,
    params: dict | None = None,
    allow_missing: bool = False,
) -> tuple[object | None, str | None]:
    base_url = str(payload.url).rstrip("/")
    headers = {"X-Api-Key": payload.api_key}
    last_error: Exception | None = None
    versions = api_versions(payload.kind, preferred_version)

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        for index, version in enumerate(versions):
            url = f"{base_url}/api/{version}/{endpoint.lstrip('/')}"
            try:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 404 and index < len(versions) - 1:
                    continue
                if response.status_code == 404 and allow_missing:
                    return None, version
                response.raise_for_status()
                if not response.content:
                    return {}, version
                return response.json(), version
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404 and allow_missing:
                    return None, version
                if exc.response.status_code == 401:
                    raise HTTPException(status_code=400, detail=f"{payload.kind.title()} rejected the API key") from exc
                raise HTTPException(
                    status_code=400,
                    detail=f"{payload.kind.title()} returned HTTP {exc.response.status_code} for {endpoint}",
                ) from exc
            except (httpx.RequestError, ValueError) as exc:
                last_error = exc
                break

    if allow_missing and isinstance(last_error, httpx.HTTPStatusError) and last_error.response.status_code == 404:
        return None, None
    raise HTTPException(status_code=400, detail=f"Unable to connect to {payload.kind.title()}: {last_error}")


async def probe_instance(payload: InstanceRequest, preferred_version: str | None = None) -> dict:
    data, api_version = await arr_get(payload, "system/status", preferred_version=preferred_version)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"Unexpected response from {payload.kind.title()}")
    return {
        "ok": True,
        "kind": payload.kind,
        "appName": data.get("appName", payload.kind.title()),
        "version": data.get("version", "unknown"),
        "osName": data.get("osName", "unknown"),
        "runtimeVersion": data.get("runtimeVersion", "unknown"),
        "apiVersion": api_version,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def check(code: str, title: str, status: str, message: str, details: object | None = None) -> dict:
    return {"code": code, "title": title, "status": status, "message": message, "details": details}


def score_checks(checks: list[dict]) -> int:
    score = 100
    for item in checks:
        if item.get("status") == "fail":
            score -= 20
        elif item.get("status") == "warn":
            score -= 7
    return max(0, min(100, score))


def local_path_info(path_value: str) -> dict:
    path = Path(path_value)
    result = {"path": path_value, "visible": False, "readable": False, "writable": False}
    try:
        if not path.exists():
            return result
        stat_result = path.stat()
        usage = shutil.disk_usage(path)
        result.update(
            {
                "visible": True,
                "readable": os.access(path, os.R_OK),
                "writable": os.access(path, os.W_OK),
                "device": stat_result.st_dev,
                "freeBytes": usage.free,
                "totalBytes": usage.total,
                "freePercent": round((usage.free / usage.total) * 100, 1) if usage.total else None,
            }
        )
    except OSError as exc:
        result["error"] = str(exc)
    return result


def records_from(data: object | None) -> list[dict]:
    if isinstance(data, dict):
        records = data.get("records", [])
        return records if isinstance(records, list) else []
    return data if isinstance(data, list) else []


def health_records(data: object | None) -> list[dict]:
    return data if isinstance(data, list) else []


def summarize_queue_issue(item: dict) -> str | None:
    state = str(item.get("trackedDownloadState") or item.get("status") or "").lower()
    error = item.get("errorMessage")
    if error:
        return str(error)
    messages = item.get("statusMessages")
    if isinstance(messages, list):
        texts: list[str] = []
        for group in messages:
            if isinstance(group, dict):
                for message in group.get("messages", []) or []:
                    texts.append(str(message))
        if texts:
            return "; ".join(texts[:3])
    if any(token in state for token in ("blocked", "failed", "warning", "error")):
        return state
    return None


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def recent_failure_items(data: object | None, hours: int = 24) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    failures: list[dict] = []
    for item in records_from(data):
        event_type = str(item.get("eventType") or "")
        lowered = event_type.lower()
        if not any(token in lowered for token in ("failed", "failure", "error")):
            continue
        occurred = parse_datetime(item.get("date"))
        if occurred and occurred < cutoff:
            continue
        data_field = item.get("data") if isinstance(item.get("data"), dict) else {}
        message = (
            data_field.get("message")
            or data_field.get("reason")
            or item.get("sourceTitle")
            or item.get("downloadId")
            or event_type
        )
        failures.append(
            {
                "eventType": event_type,
                "date": item.get("date"),
                "title": item.get("sourceTitle") or item.get("movie", {}).get("title") if isinstance(item.get("movie"), dict) else item.get("sourceTitle"),
                "message": str(message),
            }
        )
    return failures[:15]


def recommendation(
    code: str,
    title: str,
    priority: str,
    summary: str,
    steps: list[str],
) -> dict:
    return {"code": code, "title": title, "priority": priority, "summary": summary, "steps": steps}


def build_recommendations(report: dict) -> list[dict]:
    recommendations: list[dict] = []
    checks = {item.get("code"): item for item in report.get("checks", [])}
    doctors = report.get("doctors", {})

    if checks.get("connection", {}).get("status") == "fail":
        recommendations.append(
            recommendation(
                "fix_connection",
                "Restore the API connection",
                "high",
                "ArrMedic cannot reach this service or authenticate with its API.",
                [
                    "Confirm the service URL and port from the ArrMedic container/network.",
                    "Confirm the API key is current and belongs to this service.",
                    "If both containers use Docker, prefer a shared Docker network and the service/container name.",
                ],
            )
        )
        return recommendations

    if checks.get("storage", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_storage",
                "Free storage before imports fail",
                "high",
                "One or more root folders are below ArrMedic's 10 GiB warning threshold.",
                [
                    "Free space on the affected filesystem or expand the volume.",
                    "Check download-client incomplete/complete directories for abandoned data.",
                    "Confirm the *Arr root folder still points to the intended storage.",
                ],
            )
        )

    if checks.get("queue", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_queue",
                "Resolve blocked queue/import items",
                "high",
                "The queue contains items with blocked, failed, warning or error state.",
                [
                    "Open the queue details below and read the extracted status message.",
                    "Verify the download path is visible to both the download client and *Arr app.",
                    "Check remote-path mappings when the download client is on another host or uses different paths.",
                ],
            )
        )

    if checks.get("download_clients", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_download_client",
                "Configure an enabled download client",
                "medium",
                "No enabled download client was found through the service API.",
                [
                    "Open the service's Download Clients settings.",
                    "Enable a configured client or add qBittorrent, SABnzbd, Transmission, or another supported client.",
                    "Use the service's built-in Test button before saving.",
                ],
            )
        )

    if checks.get("indexers", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_indexers",
                "Enable at least one working indexer",
                "medium",
                "Prowlarr did not report an enabled indexer.",
                [
                    "Open Prowlarr Indexers and enable or add an indexer.",
                    "Run Prowlarr's Test action for each configured indexer.",
                    "Check DNS, proxy, VPN and rate-limit errors if tests fail.",
                ],
            )
        )

    if checks.get("app_health", {}).get("status") in {"warn", "fail"}:
        recommendations.append(
            recommendation(
                "fix_app_health",
                "Review native application health warnings",
                "medium",
                "The service itself is reporting one or more health warnings.",
                [
                    "Open System → Status/Health in the affected *Arr app.",
                    "Resolve the native warning first because it often points directly to the root cause.",
                    "Run ArrMedic again after the native warning is cleared.",
                ],
            )
        )

    if checks.get("recent_failures", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_recent_failures",
                "Review failures from the last 24 hours",
                "medium",
                "Recent *Arr history contains failed/error events.",
                [
                    "Compare the recent failures with queue messages and application health warnings.",
                    "Look for repeated titles, indexers, download clients or paths.",
                    "Re-run the affected action after correcting the underlying issue.",
                ],
            )
        )

    path_doctor = doctors.get("path", {})
    if path_doctor.get("status") == "info" and report.get("rootFolders"):
        recommendations.append(
            recommendation(
                "enable_path_visibility",
                "Mount media paths into ArrMedic for deeper checks",
                "low",
                "ArrMedic can see the path names through the API but not the same filesystem paths inside its own container.",
                [
                    "Bind-mount the same host media path at the same container path used by the *Arr app.",
                    "A read-only mount is enough for current ArrMedic filesystem diagnostics.",
                    "Recreate ArrMedic with the mount and run a new scan.",
                ],
            )
        )

    if doctors.get("hardlink", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_hardlink_layout",
                "Keep download and library paths on one filesystem",
                "high",
                "Visible paths span multiple filesystem devices, so hardlinks cannot cross those boundaries.",
                [
                    "Use one shared filesystem/root for downloads and media whenever possible.",
                    "Prefer a common mount such as /data with /data/downloads and /data/media beneath it.",
                    "Update container mounts and *Arr/download-client paths consistently before retesting.",
                ],
            )
        )

    if doctors.get("permission", {}).get("status") == "warn":
        recommendations.append(
            recommendation(
                "fix_arrmedic_path_access",
                "Make diagnostic mounts readable by ArrMedic",
                "low",
                "ArrMedic can see a mounted root path but cannot read it.",
                [
                    "Confirm the host path permissions allow the ArrMedic container to read the mount.",
                    "This warning describes ArrMedic access only; verify the actual *Arr container UID/GID separately if imports fail.",
                    "A read-only but readable mount is sufficient for ArrMedic.",
                ],
            )
        )

    # Stable order: high, medium, low.
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda item: (priority_order.get(item["priority"], 9), item["title"]))
    return recommendations


def save_scan(summary: dict) -> int:
    created_at = summary.get("checkedAt") or datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO diagnostic_runs(score, service_count, online_count, issue_count, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                summary.get("score"),
                summary.get("serviceCount", 0),
                summary.get("onlineCount", 0),
                summary.get("issueCount", 0),
                json.dumps(summary, separators=(",", ":")),
                created_at,
            ),
        )
        conn.execute(
            "DELETE FROM diagnostic_runs WHERE id NOT IN (SELECT id FROM diagnostic_runs ORDER BY id DESC LIMIT ?)",
            (MAX_SAVED_SCANS,),
        )
        return int(cursor.lastrowid)


def latest_scan() -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM diagnostic_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    try:
        result = json.loads(row["result_json"])
    except json.JSONDecodeError:
        return None
    result["runId"] = row["id"]
    result["savedAt"] = row["created_at"]
    return result


def scan_history(limit: int = 20) -> list[dict]:
    limit = max(1, min(50, limit))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, score, service_count, online_count, issue_count, created_at
            FROM diagnostic_runs ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "score": row["score"],
            "serviceCount": row["service_count"],
            "onlineCount": row["online_count"],
            "issueCount": row["issue_count"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


async def build_instance_diagnostics(row: sqlite3.Row) -> dict:
    payload = instance_payload(row)
    checks: list[dict] = []
    preferred = row["api_version"] if "api_version" in row.keys() else None

    try:
        status = await probe_instance(payload, preferred)
        api_version = status.get("apiVersion")
        checks.append(check("connection", "Connection", "pass", f"Connected to {status['appName']} {status['version']}"))
    except HTTPException as exc:
        checks.append(check("connection", "Connection", "fail", str(exc.detail)))
        report = {
            "instanceId": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "url": row["url"],
            "score": score_checks(checks),
            "status": "offline",
            "checks": checks,
            "doctors": {
                "path": {"status": "info", "message": "Path checks require a working API connection."},
                "permission": {"status": "info", "message": "Permission checks require a working API connection."},
                "hardlink": {"status": "info", "message": "Hardlink checks require a working API connection."},
                "queue": {"status": "info", "message": "Queue checks require a working API connection."},
            },
            "rootFolders": [],
            "queue": [],
            "downloadClients": [],
            "remotePathMappings": [],
            "health": [],
            "recentFailures": [],
            "checkedAt": datetime.now(timezone.utc).isoformat(),
        }
        report["recommendations"] = build_recommendations(report)
        return report

    async def optional(endpoint: str, params: dict | None = None):
        try:
            data, _ = await arr_get(
                payload,
                endpoint,
                preferred_version=api_version,
                params=params,
                allow_missing=True,
            )
            return data
        except HTTPException:
            return None

    health_data, roots_data, queue_data, clients_data, mappings_data, indexers_data, history_data = await asyncio.gather(
        optional("health"),
        optional("rootfolder"),
        optional("queue", {"page": 1, "pageSize": 50}),
        optional("downloadclient"),
        optional("remotepathmapping"),
        optional("indexer"),
        optional("history", {"page": 1, "pageSize": 50, "sortKey": "date", "sortDirection": "descending"}),
    )

    health_items = health_records(health_data)
    if health_data is not None:
        if not health_items:
            checks.append(check("app_health", "Application health", "pass", "No health warnings reported by the service."))
        else:
            serious = [h for h in health_items if str(h.get("type", "")).lower() == "error"]
            level = "fail" if serious else "warn"
            checks.append(
                check(
                    "app_health",
                    "Application health",
                    level,
                    f"{len(health_items)} health warning(s) reported.",
                    health_items[:10],
                )
            )

    roots = roots_data if isinstance(roots_data, list) else []
    root_details: list[dict] = []
    for root in roots:
        path_value = str(root.get("path") or "")
        local = local_path_info(path_value) if path_value else {"path": path_value, "visible": False}
        root_details.append(
            {
                "id": root.get("id"),
                "path": path_value,
                "freeSpace": root.get("freeSpace"),
                "unmappedFolders": root.get("unmappedFolders"),
                "local": local,
            }
        )

    if roots_data is not None:
        low_space = []
        for root in root_details:
            free = root.get("freeSpace")
            if isinstance(free, (int, float)) and free < 10 * 1024**3:
                low_space.append(root["path"])
        if low_space:
            checks.append(check("storage", "Storage", "warn", f"Low free space on {len(low_space)} root folder(s).", low_space))
        elif roots:
            checks.append(check("storage", "Storage", "pass", f"{len(roots)} root folder(s) reported."))

    queue = records_from(queue_data)
    queue_issues = []
    for item in queue:
        issue = summarize_queue_issue(item)
        if issue:
            queue_issues.append(
                {
                    "title": item.get("title") or item.get("downloadId") or "Queue item",
                    "status": item.get("status"),
                    "trackedDownloadState": item.get("trackedDownloadState"),
                    "message": issue,
                    "outputPath": item.get("outputPath"),
                }
            )
    if queue_data is not None:
        if queue_issues:
            checks.append(check("queue", "Queue", "warn", f"{len(queue_issues)} queue item(s) need attention.", queue_issues[:15]))
        else:
            checks.append(check("queue", "Queue", "pass", f"Queue checked ({len(queue)} item(s))."))

    clients = clients_data if isinstance(clients_data, list) else []
    if clients_data is not None:
        enabled_clients = [client for client in clients if client.get("enable", True)]
        if not enabled_clients:
            checks.append(check("download_clients", "Download clients", "warn", "No enabled download client was found."))
        else:
            checks.append(check("download_clients", "Download clients", "pass", f"{len(enabled_clients)} enabled download client(s)."))

    mappings = mappings_data if isinstance(mappings_data, list) else []
    indexers = indexers_data if isinstance(indexers_data, list) else []
    if row["kind"] == "prowlarr" and indexers_data is not None:
        enabled_indexers = [indexer for indexer in indexers if indexer.get("enable", True)]
        if not enabled_indexers:
            checks.append(check("indexers", "Indexers", "warn", "No enabled Prowlarr indexer was found."))
        else:
            checks.append(check("indexers", "Indexers", "pass", f"{len(enabled_indexers)} enabled indexer(s)."))

    recent_failures = recent_failure_items(history_data)
    if history_data is not None:
        if recent_failures:
            checks.append(
                check(
                    "recent_failures",
                    "Recent failures",
                    "warn",
                    f"{len(recent_failures)} failure/error event(s) found in recent history (up to 24 hours).",
                    recent_failures,
                )
            )
        else:
            checks.append(check("recent_failures", "Recent failures", "pass", "No recent failure/error events found in the inspected history."))

    visible_roots = [root for root in root_details if root.get("local", {}).get("visible")]
    if roots and not visible_roots:
        path_doctor = {
            "status": "info",
            "message": "API paths were found, but they are not mounted inside ArrMedic. Mount the same media paths into ArrMedic to unlock filesystem checks.",
        }
    elif visible_roots:
        path_doctor = {
            "status": "pass",
            "message": f"{len(visible_roots)} root path(s) are visible inside the ArrMedic container.",
        }
    else:
        path_doctor = {"status": "info", "message": "This service does not expose root folders through the API."}

    unreadable = [root["path"] for root in visible_roots if not root.get("local", {}).get("readable")]
    if unreadable:
        permission_doctor = {
            "status": "warn",
            "message": f"ArrMedic cannot read {len(unreadable)} visible root path(s). This checks ArrMedic access, not the service container's UID/GID.",
            "paths": unreadable,
        }
    elif visible_roots:
        permission_doctor = {"status": "pass", "message": "All visible root paths are readable by ArrMedic."}
    else:
        permission_doctor = {
            "status": "info",
            "message": "Mount media paths into ArrMedic to inspect container-level path visibility and read access.",
        }

    devices = {root.get("local", {}).get("device") for root in visible_roots if root.get("local", {}).get("device") is not None}
    if len(devices) > 1:
        hardlink_doctor = {
            "status": "warn",
            "message": "Visible root paths span multiple filesystems. Hardlinks cannot cross filesystem/device boundaries.",
            "deviceCount": len(devices),
        }
    elif visible_roots:
        hardlink_doctor = {
            "status": "pass",
            "message": "Visible root paths are on one filesystem. This is compatible with hardlinks, although ArrMedic has not created a test link.",
        }
    else:
        hardlink_doctor = {
            "status": "info",
            "message": "Mount media/download paths into ArrMedic before evaluating hardlink filesystem boundaries.",
        }

    if queue_data is None:
        queue_doctor = {"status": "info", "message": "Queue endpoint is not available for this service."}
    elif queue_issues:
        queue_doctor = {"status": "warn", "message": f"{len(queue_issues)} queue/import issue(s) found.", "issues": queue_issues[:15]}
    else:
        queue_doctor = {"status": "pass", "message": f"No blocked imports detected in {len(queue)} queue item(s)."}

    checked_at = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            "UPDATE instances SET version = ?, os_name = ?, api_version = ?, last_checked = ? WHERE id = ?",
            (status["version"], status["osName"], api_version, checked_at, row["id"]),
        )

    report = {
        "instanceId": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "url": row["url"],
        "version": status["version"],
        "apiVersion": api_version,
        "score": score_checks(checks),
        "status": "online",
        "checks": checks,
        "doctors": {
            "path": path_doctor,
            "permission": permission_doctor,
            "hardlink": hardlink_doctor,
            "queue": queue_doctor,
        },
        "rootFolders": root_details,
        "queue": queue,
        "queueIssues": queue_issues,
        "downloadClients": clients,
        "remotePathMappings": mappings,
        "indexers": indexers,
        "health": health_items,
        "recentFailures": recent_failures,
        "checkedAt": checked_at,
    }
    report["recommendations"] = build_recommendations(report)
    return report


async def build_summary() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT * FROM instances ORDER BY id").fetchall()
    if not rows:
        return {
            "score": None,
            "status": "empty",
            "instances": [],
            "serviceCount": 0,
            "onlineCount": 0,
            "issueCount": 0,
            "recommendationCount": 0,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
        }

    reports = await asyncio.gather(*(build_instance_diagnostics(row) for row in rows))
    online = sum(1 for report in reports if report["status"] == "online")
    issue_count = sum(
        1
        for report in reports
        for item in report["checks"]
        if item.get("status") in {"warn", "fail"}
    )
    recommendation_count = sum(len(report.get("recommendations", [])) for report in reports)
    score = round(sum(report["score"] for report in reports) / len(reports))
    return {
        "score": score,
        "status": "healthy" if issue_count == 0 and online == len(reports) else "attention",
        "instances": reports,
        "serviceCount": len(reports),
        "onlineCount": online,
        "issueCount": issue_count,
        "recommendationCount": recommendation_count,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


init_db()


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/health")
async def health() -> dict:
    return {"status": "healthy", "name": "ArrMedic", "version": APP_VERSION}


@app.get("/api/setup/status")
async def setup_status(arrmedic_session: str | None = Cookie(default=None)) -> dict:
    with db() as conn:
        configured = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    authenticated = False
    username = None
    if configured and arrmedic_session:
        try:
            user = require_user(arrmedic_session)
            authenticated = True
            username = user["username"]
        except HTTPException:
            pass
    return {"configured": configured, "authenticated": authenticated, "username": username}


@app.post("/api/setup/admin")
async def create_admin(payload: SetupRequest, response: Response) -> dict:
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    with db() as conn:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(status_code=409, detail="ArrMedic is already configured")
        conn.execute(
            "INSERT INTO users(id, username, password_hash, created_at) VALUES (1, ?, ?, ?)",
            (payload.username, hash_password(payload.password), datetime.now(timezone.utc).isoformat()),
        )
    issue_session(response, 1)
    return {"ok": True, "username": payload.username}


@app.post("/api/auth/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username.strip(),)).fetchone()
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    issue_session(response, user["id"])
    return {"ok": True, "username": user["username"]}


@app.post("/api/auth/logout")
async def logout(response: Response, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    if arrmedic_session:
        token_hash = hashlib.sha256(arrmedic_session.encode()).hexdigest()
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.post("/api/instances/test")
async def test_instance(payload: InstanceRequest, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    return await probe_instance(payload)


@app.get("/api/instances")
async def list_instances(arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, kind, url, version, os_name, api_version, last_checked, created_at FROM instances ORDER BY id"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/instances")
async def add_instance(payload: InstanceRequest, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    status = await probe_instance(payload)
    encrypted_key = cipher().encrypt(payload.api_key.encode()).decode()
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO instances(name, kind, url, api_key_enc, version, os_name, api_version, last_checked, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.kind,
                str(payload.url).rstrip("/"),
                encrypted_key,
                status["version"],
                status["osName"],
                status.get("apiVersion"),
                status["checkedAt"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        instance_id = cursor.lastrowid
    return {"ok": True, "id": instance_id, **status}


@app.post("/api/instances/{instance_id}/check")
async def check_instance(instance_id: int, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    row = get_instance(instance_id)
    payload = instance_payload(row)
    status = await probe_instance(payload, row["api_version"])
    with db() as conn:
        conn.execute(
            "UPDATE instances SET version = ?, os_name = ?, api_version = ?, last_checked = ? WHERE id = ?",
            (status["version"], status["osName"], status.get("apiVersion"), status["checkedAt"], instance_id),
        )
    return status


@app.put("/api/instances/{instance_id}")
async def update_instance(
    instance_id: int,
    payload: InstanceUpdateRequest,
    arrmedic_session: str | None = Cookie(default=None),
) -> dict:
    require_user(arrmedic_session)
    row = get_instance(instance_id)
    api_key = (payload.api_key or "").strip() or cipher().decrypt(row["api_key_enc"].encode()).decode()
    probe_payload = InstanceRequest(name=payload.name, kind=payload.kind, url=payload.url, api_key=api_key)
    status = await probe_instance(probe_payload)
    encrypted_key = cipher().encrypt(api_key.encode()).decode()
    with db() as conn:
        conn.execute(
            """
            UPDATE instances
            SET name = ?, kind = ?, url = ?, api_key_enc = ?, version = ?, os_name = ?, api_version = ?, last_checked = ?
            WHERE id = ?
            """,
            (
                payload.name,
                payload.kind,
                str(payload.url).rstrip("/"),
                encrypted_key,
                status["version"],
                status["osName"],
                status.get("apiVersion"),
                status["checkedAt"],
                instance_id,
            ),
        )
    return {"ok": True, "id": instance_id, **status}


@app.delete("/api/instances/{instance_id}")
async def delete_instance(instance_id: int, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    with db() as conn:
        cursor = conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"ok": True}


@app.get("/api/instances/{instance_id}/diagnostics")
async def instance_diagnostics(instance_id: int, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    return await build_instance_diagnostics(get_instance(instance_id))


@app.get("/api/diagnostics/summary")
async def diagnostics_summary(arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    return await build_summary()


@app.post("/api/diagnostics/run")
async def run_diagnostics(arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    summary = await build_summary()
    run_id = save_scan(summary)
    summary["runId"] = run_id
    summary["savedAt"] = summary["checkedAt"]
    return summary


@app.get("/api/diagnostics/latest")
async def latest_diagnostics(arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    saved = latest_scan()
    if saved is not None:
        return saved
    return {
        "score": None,
        "status": "empty",
        "instances": [],
        "serviceCount": 0,
        "onlineCount": 0,
        "issueCount": 0,
        "recommendationCount": 0,
        "checkedAt": None,
        "savedAt": None,
    }


@app.get("/api/diagnostics/history")
async def diagnostics_history(limit: int = 20, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    return {"items": scan_history(limit)}
