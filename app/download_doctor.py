from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, HTTPException

from .doctor import ensure_tables as ensure_doctor_tables
from .main import SESSION_COOKIE, arr_get, db, get_instance, instance_payload, records_from, require_user

router = APIRouter(prefix="/api/doctors/download-clients", tags=["download-client-doctor"])

SUPPORTED_KINDS = {"radarr", "sonarr"}


def _field_value(client: dict[str, Any], *names: str) -> Any:
    wanted = {name.lower() for name in names}
    for field in client.get("fields", []) or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").lower()
        if name in wanted:
            return field.get("value")
    return None


def _client_summary(client: dict[str, Any]) -> dict[str, Any]:
    implementation = str(client.get("implementation") or client.get("implementationName") or "Unknown")
    host = _field_value(client, "host")
    port = _field_value(client, "port")
    category = _field_value(client, "category")
    url_base = _field_value(client, "urlBase", "urlbase")
    return {
        "id": client.get("id"),
        "name": client.get("name") or implementation,
        "implementation": implementation,
        "protocol": client.get("protocol"),
        "enabled": bool(client.get("enable", True)),
        "host": host,
        "port": port,
        "category": category,
        "urlBase": url_base,
    }


def _path_mappings() -> list[dict[str, Any]]:
    ensure_doctor_tables()
    with db() as conn:
        rows = conn.execute("SELECT id, name, host_path, container_path FROM path_mappings ORDER BY id").fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "hostPath": row["host_path"],
            "containerPath": row["container_path"],
        }
        for row in rows
    ]


def _remote_mapping_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "host": item.get("host"),
        "remotePath": item.get("remotePath"),
        "localPath": item.get("localPath"),
    }


def _queue_path(item: dict[str, Any]) -> str | None:
    for key in ("outputPath", "path"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _queue_messages(item: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    if item.get("errorMessage"):
        messages.append(str(item["errorMessage"]))
    for group in item.get("statusMessages", []) or []:
        if not isinstance(group, dict):
            continue
        for message in group.get("messages", []) or []:
            messages.append(str(message))
    return messages


def _looks_like_path_problem(text: str) -> bool:
    lowered = text.lower()
    tokens = (
        "path does not exist",
        "path is not accessible",
        "folder does not exist",
        "directory does not exist",
        "no files found",
        "remote path",
        "unable to import",
        "not a valid local path",
        "access to the path",
        "permission denied",
    )
    return any(token in lowered for token in tokens)


def _apply_remote_mapping(path: str, mappings: list[dict[str, Any]], host: str | None = None) -> tuple[str, dict[str, Any] | None]:
    normalized_host = (host or "").lower()
    for mapping in mappings:
        mapping_host = str(mapping.get("host") or "").lower()
        remote = str(mapping.get("remotePath") or "")
        local = str(mapping.get("localPath") or "")
        if not remote or not local:
            continue
        if normalized_host and mapping_host and mapping_host != normalized_host:
            continue
        if path == remote.rstrip("/") or path.startswith(remote.rstrip("/") + "/"):
            suffix = path[len(remote.rstrip("/")):]
            return local.rstrip("/") + suffix, mapping
    return path, None


def _matching_arrmedic_mapping(path: str, mappings: list[dict[str, Any]]) -> dict[str, Any] | None:
    for mapping in mappings:
        container = str(mapping.get("containerPath") or "").rstrip("/")
        if container and (path == container or path.startswith(container + "/")):
            return mapping
    return None


async def diagnose_instance(instance_id: int) -> dict[str, Any]:
    instance = get_instance(instance_id)
    if instance["kind"] not in SUPPORTED_KINDS:
        raise HTTPException(status_code=400, detail="Download Client Doctor currently supports Radarr and Sonarr")

    payload = instance_payload(instance)
    preferred = instance["api_version"] if "api_version" in instance.keys() else None
    clients_raw, _ = await arr_get(payload, "downloadclient", preferred_version=preferred)
    remote_raw, _ = await arr_get(payload, "remotepathmapping", preferred_version=preferred, allow_missing=True)
    queue_raw, _ = await arr_get(
        payload,
        "queue",
        preferred_version=preferred,
        params={"page": 1, "pageSize": 100},
        allow_missing=True,
    )

    clients = [_client_summary(item) for item in clients_raw or [] if isinstance(item, dict)] if isinstance(clients_raw, list) else []
    remotes = [_remote_mapping_summary(item) for item in remote_raw or [] if isinstance(item, dict)] if isinstance(remote_raw, list) else []
    queue = records_from(queue_raw)
    manual_mappings = _path_mappings()
    issues: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []

    if not clients:
        issues.append({"severity": "warning", "code": "no_download_client", "title": "No download client configured", "message": f"{instance['name']} does not report a download client."})
    elif not any(client["enabled"] for client in clients):
        issues.append({"severity": "warning", "code": "no_enabled_download_client", "title": "All download clients are disabled", "message": f"Enable at least one download client in {instance['name']}."})

    for item in queue:
        raw_path = _queue_path(item)
        messages = _queue_messages(item)
        client_name = str(item.get("downloadClient") or "")
        client = next((c for c in clients if str(c.get("name") or "").lower() == client_name.lower()), None)
        client_host = str(client.get("host") or "") if client else ""
        mapped_path = raw_path
        applied = None
        if raw_path:
            mapped_path, applied = _apply_remote_mapping(raw_path, remotes, client_host or None)
            manual = _matching_arrmedic_mapping(mapped_path, manual_mappings)
            path_rows.append(
                {
                    "title": item.get("title") or item.get("movie", {}).get("title") or item.get("series", {}).get("title") or "Queue item",
                    "downloadClient": client_name or (client.get("name") if client else None),
                    "downloadClientHost": client_host or None,
                    "reportedPath": raw_path,
                    "mappedPath": mapped_path,
                    "remoteMapping": applied,
                    "arrmedicMapping": manual,
                    "status": item.get("status"),
                    "trackedDownloadState": item.get("trackedDownloadState"),
                }
            )

            if client_host and raw_path and not applied:
                remote_like = raw_path.startswith("/") and any(
                    str(mapping.get("host") or "").lower() == client_host.lower() for mapping in remotes
                )
                if remote_like:
                    issues.append({
                        "severity": "warning",
                        "code": "remote_mapping_miss",
                        "title": "Download path does not match Remote Path Mapping",
                        "message": f"{client_name or client_host} reported {raw_path}, but none of the mappings for {client_host} match that path.",
                        "path": raw_path,
                        "downloadClient": client_name or None,
                    })

        for message in messages:
            if _looks_like_path_problem(message):
                issues.append({
                    "severity": "error" if "does not exist" in message.lower() or "not accessible" in message.lower() else "warning",
                    "code": "queue_path_problem",
                    "title": "Import/download path problem",
                    "message": message,
                    "path": raw_path,
                    "downloadClient": client_name or None,
                })

    # De-duplicate repeated queue messages while preserving order.
    seen: set[tuple[str, str, str]] = set()
    unique_issues: list[dict[str, Any]] = []
    for issue in issues:
        marker = (str(issue.get("code")), str(issue.get("message")), str(issue.get("path") or ""))
        if marker in seen:
            continue
        seen.add(marker)
        unique_issues.append(issue)

    return {
        "instanceId": instance["id"],
        "instanceName": instance["name"],
        "kind": instance["kind"],
        "clients": clients,
        "remotePathMappings": remotes,
        "queuePaths": path_rows,
        "manualPathMappings": manual_mappings,
        "issues": unique_issues,
        "issueCount": len(unique_issues),
        "status": "problem" if unique_issues else "ok",
        "help": {
            "samePathRule": "If the download client and Radarr/Sonarr run in Docker on the same host, the easiest layout is to expose the same common container path to both, for example /data/downloads.",
            "remotePathRule": "Use Remote Path Mapping only when the download client reports a path that Radarr/Sonarr cannot use directly, commonly when they are on different hosts or intentionally use different container paths.",
        },
    }


@router.get("")
async def diagnose_all(arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    with db() as conn:
        rows = conn.execute("SELECT id FROM instances WHERE kind IN ('radarr','sonarr') ORDER BY kind, name").fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            results.append(await diagnose_instance(int(row["id"])))
        except HTTPException as exc:
            results.append({"instanceId": row["id"], "status": "error", "issueCount": 1, "issues": [{"severity": "error", "code": "connection", "title": "Unable to inspect download clients", "message": str(exc.detail)}]})
    return {"items": results, "issueCount": sum(int(item.get("issueCount") or 0) for item in results)}


@router.get("/{instance_id}")
async def diagnose_one(instance_id: int, arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    return await diagnose_instance(instance_id)
