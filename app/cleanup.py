from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from .main import SESSION_COOKIE, api_versions, get_instance, instance_payload, require_user

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


class CleanupScanRequest(BaseModel):
    instance_ids: list[int] = Field(default_factory=list)


class CleanupDeleteItem(BaseModel):
    instance_id: int
    item_id: int


class CleanupDeleteRequest(BaseModel):
    report_id: str
    items: list[CleanupDeleteItem]
    delete_files: bool = False
    add_import_exclusion: bool = False


_REMOVED_PATTERNS = (
    re.compile(r"tmdbid\s+(\d+)", re.I),
    re.compile(r"tvdbid\s+(\d+)", re.I),
)
_LIBRARY_ENDPOINTS = {"movie", "series"}
_DRY_RUN_TTL_SECONDS = 30 * 60
_DRY_RUN_REPORTS: dict[str, dict[str, Any]] = {}


def extract_removed_ids(health: list[dict[str, Any]], kind: str) -> set[int]:
    ids: set[int] = set()
    provider = "tmdb" if kind == "radarr" else "tvdb"
    for item in health:
        message = " ".join(str(item.get(key) or "") for key in ("message", "source", "type"))
        lowered = message.lower()
        if "removed" not in lowered or provider not in lowered:
            continue
        for pattern in _REMOVED_PATTERNS:
            for match in pattern.findall(message):
                ids.add(int(match))
    return ids


def item_has_media(kind: str, item: dict[str, Any]) -> bool:
    if kind == "radarr":
        return bool(item.get("hasFile"))
    if kind == "sonarr":
        stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        return int(stats.get("episodeFileCount") or 0) > 0
    return False


def cleanup_status(stale_metadata: bool, has_media: bool) -> tuple[str, str, str]:
    if stale_metadata and not has_media:
        return (
            "safe",
            "Removed metadata and no media file are reported.",
            "Safe candidate for app-record cleanup after review.",
        )
    if has_media:
        return (
            "manual_only",
            "Media is still reported for this item.",
            "Do not auto-clean. Review this item manually before removing its app record.",
        )
    return (
        "review",
        "No media file is reported, but the metadata is not known to be removed.",
        "Review first. The item may simply be waiting for a download or intentionally monitored.",
    )


def _friendly_request_error(exc: Exception, endpoint: str) -> str:
    if isinstance(exc, httpx.ReadTimeout):
        return f"Timed out while downloading {endpoint} data. Large libraries can take longer than normal."
    if isinstance(exc, httpx.ConnectTimeout):
        return "Connection timed out before the service responded."
    if isinstance(exc, httpx.ConnectError):
        text = str(exc).strip() or exc.__class__.__name__
        return f"Connection failed: {text}"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    text = str(exc).strip()
    return text or exc.__class__.__name__


async def request_json(payload, method: str, endpoint: str, *, params: dict | None = None) -> Any:
    base = str(payload.url).rstrip("/")
    headers = {"X-Api-Key": payload.api_key}
    endpoint_name = endpoint.lstrip("/").split("/", 1)[0]
    is_library_request = method.upper() == "GET" and endpoint_name in _LIBRARY_ENDPOINTS
    timeout = httpx.Timeout(connect=10.0, read=120.0 if is_library_request else 30.0, write=30.0, pool=10.0)
    attempts = 2 if is_library_request else 1
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for version in api_versions(payload.kind):
            url = f"{base}/api/{version}/{endpoint.lstrip('/')}"
            for attempt in range(attempts):
                try:
                    response = await client.request(method, url, headers=headers, params=params)
                    if response.status_code == 404:
                        last_error = RuntimeError(f"HTTP 404 for {endpoint}")
                        break
                    if response.status_code == 401:
                        raise HTTPException(status_code=400, detail=f"{payload.kind.title()} rejected the API key")
                    response.raise_for_status()
                    if not response.content:
                        return None
                    return response.json()
                except HTTPException:
                    raise
                except httpx.ReadTimeout as exc:
                    last_error = exc
                    if attempt + 1 < attempts:
                        await asyncio.sleep(1.0)
                        continue
                    break
                except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                    last_error = exc
                    break
            if isinstance(last_error, RuntimeError) and "HTTP 404" in str(last_error):
                continue
            break

    detail = _friendly_request_error(last_error or RuntimeError("Unknown request failure"), endpoint)
    raise HTTPException(status_code=400, detail=f"Unable to call {payload.kind.title()} {endpoint}: {detail}")


def _with_cleanup_status(row: dict[str, Any]) -> dict[str, Any]:
    status, reason, recommendation = cleanup_status(bool(row["staleMetadata"]), bool(row["hasMedia"]))
    return {**row, "cleanupStatus": status, "reason": reason, "recommendation": recommendation}


def radarr_row(instance, movie: dict, stale_ids: set[int]) -> dict:
    has_file = item_has_media("radarr", movie)
    movie_file = movie.get("movieFile") if isinstance(movie.get("movieFile"), dict) else {}
    tmdb_id = movie.get("tmdbId")
    return _with_cleanup_status({
        "instanceId": instance["id"],
        "instanceName": instance["name"],
        "kind": "radarr",
        "itemId": movie.get("id"),
        "title": movie.get("title") or "Unknown movie",
        "year": movie.get("year"),
        "externalId": tmdb_id,
        "externalProvider": "TMDb",
        "path": movie.get("path"),
        "monitored": bool(movie.get("monitored")),
        "hasMedia": has_file,
        "mediaPath": movie_file.get("path"),
        "mediaSize": movie_file.get("size"),
        "staleMetadata": isinstance(tmdb_id, int) and tmdb_id in stale_ids,
    })


def sonarr_row(instance, series: dict, stale_ids: set[int]) -> dict:
    stats = series.get("statistics") if isinstance(series.get("statistics"), dict) else {}
    file_count = int(stats.get("episodeFileCount") or 0)
    tvdb_id = series.get("tvdbId")
    return _with_cleanup_status({
        "instanceId": instance["id"],
        "instanceName": instance["name"],
        "kind": "sonarr",
        "itemId": series.get("id"),
        "title": series.get("title") or "Unknown series",
        "year": series.get("year"),
        "externalId": tvdb_id,
        "externalProvider": "TVDb",
        "path": series.get("path"),
        "monitored": bool(series.get("monitored")),
        "hasMedia": file_count > 0,
        "mediaCount": file_count,
        "staleMetadata": isinstance(tvdb_id, int) and tvdb_id in stale_ids,
    })


async def scan_instance(instance) -> dict:
    payload = instance_payload(instance)
    health = await request_json(payload, "GET", "health") or []
    health = health if isinstance(health, list) else []
    stale_ids = extract_removed_ids(health, instance["kind"])
    endpoint = "movie" if instance["kind"] == "radarr" else "series"
    library = await request_json(payload, "GET", endpoint) or []
    if not isinstance(library, list):
        library = []
    rows = (
        [radarr_row(instance, item, stale_ids) for item in library if isinstance(item, dict)]
        if instance["kind"] == "radarr"
        else [sonarr_row(instance, item, stale_ids) for item in library if isinstance(item, dict)]
    )
    candidates = [row for row in rows if row["staleMetadata"] or not row["hasMedia"]]
    order = {"safe": 0, "review": 1, "manual_only": 2}
    candidates.sort(key=lambda row: (order.get(row["cleanupStatus"], 9), str(row["title"]).lower()))
    return {
        "instanceId": instance["id"],
        "instanceName": instance["name"],
        "kind": instance["kind"],
        "libraryCount": len(rows),
        "staleCount": sum(1 for row in rows if row["staleMetadata"]),
        "missingMediaCount": sum(1 for row in rows if not row["hasMedia"]),
        "candidateCount": len(candidates),
        "items": candidates,
    }


def _purge_expired_reports() -> None:
    now = time.time()
    expired = [key for key, report in _DRY_RUN_REPORTS.items() if report["expires_at"] <= now]
    for key in expired:
        _DRY_RUN_REPORTS.pop(key, None)


def _store_report(items: list[dict[str, Any]]) -> tuple[str, str]:
    _purge_expired_reports()
    report_id = uuid.uuid4().hex
    expires_at = time.time() + _DRY_RUN_TTL_SECONDS
    _DRY_RUN_REPORTS[report_id] = {
        "expires_at": expires_at,
        "allowed": {(int(item["instanceId"]), int(item["itemId"])) for item in items if item.get("itemId") is not None},
    }
    expires_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
    return report_id, expires_iso


def _validate_report(report_id: str, items: list[CleanupDeleteItem]) -> None:
    _purge_expired_reports()
    report = _DRY_RUN_REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=409, detail="Dry-run report is missing or expired. Run Dry Run again before cleanup.")
    allowed = report["allowed"]
    invalid = [(item.instance_id, item.item_id) for item in items if (item.instance_id, item.item_id) not in allowed]
    if invalid:
        raise HTTPException(status_code=409, detail="Selection changed after the dry run. Run Dry Run again before cleanup.")


@router.get("/instances")
async def cleanup_instances(arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    from .main import db
    with db() as conn:
        rows = conn.execute("SELECT id, name, kind, url FROM instances WHERE kind IN ('radarr','sonarr') ORDER BY kind, name").fetchall()
    return {"items": [{"id": row["id"], "name": row["name"], "kind": row["kind"], "url": row["url"]} for row in rows]}


@router.post("/scan")
async def cleanup_scan(request: CleanupScanRequest, arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    ids = list(dict.fromkeys(int(value) for value in request.instance_ids))
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one Radarr or Sonarr instance")
    results = []
    all_items = []
    for instance_id in ids:
        instance = get_instance(instance_id)
        if instance["kind"] not in {"radarr", "sonarr"}:
            continue
        result = await scan_instance(instance)
        results.append(result)
        all_items.extend(result["items"])

    report_id, expires_at = _store_report(all_items)
    return {
        "dryRun": True,
        "reportId": report_id,
        "expiresAt": expires_at,
        "instances": results,
        "items": all_items,
        "totalCandidates": len(all_items),
        "staleCount": sum(1 for item in all_items if item["staleMetadata"]),
        "missingMediaCount": sum(1 for item in all_items if not item["hasMedia"]),
        "safeCount": sum(1 for item in all_items if item["cleanupStatus"] == "safe"),
        "reviewCount": sum(1 for item in all_items if item["cleanupStatus"] == "review"),
        "manualOnlyCount": sum(1 for item in all_items if item["cleanupStatus"] == "manual_only"),
    }


@router.post("/remove")
async def cleanup_remove(request: CleanupDeleteRequest, arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    if not request.items:
        raise HTTPException(status_code=400, detail="Select at least one library item")
    _validate_report(request.report_id, request.items)

    removed: list[dict] = []
    failed: list[dict] = []
    for selected in request.items:
        try:
            instance = get_instance(selected.instance_id)
            if instance["kind"] not in {"radarr", "sonarr"}:
                raise HTTPException(status_code=400, detail="Only Radarr and Sonarr records can be removed here")
            payload = instance_payload(instance)
            endpoint = "movie" if instance["kind"] == "radarr" else "series"

            if request.delete_files:
                current = await request_json(payload, "GET", f"{endpoint}/{selected.item_id}")
                if not isinstance(current, dict):
                    raise HTTPException(status_code=400, detail="Unable to verify media state before destructive cleanup")
                if item_has_media(instance["kind"], current):
                    raise HTTPException(
                        status_code=400,
                        detail="Blocked for safety: this item currently has media files. Use 'Remove from app only' instead.",
                    )

            await request_json(
                payload,
                "DELETE",
                f"{endpoint}/{selected.item_id}",
                params={
                    "deleteFiles": "true" if request.delete_files else "false",
                    "addImportExclusion": "true" if request.add_import_exclusion else "false",
                },
            )
            removed.append({"instanceId": selected.instance_id, "itemId": selected.item_id, "deleteFiles": request.delete_files})
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            failed.append({"instanceId": selected.instance_id, "itemId": selected.item_id, "error": detail})

    return {
        "removed": removed,
        "failed": failed,
        "removedCount": len(removed),
        "failedCount": len(failed),
        "deleteFiles": request.delete_files,
    }
