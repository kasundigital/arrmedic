from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, HTTPException

from .doctor import ensure_tables as ensure_doctor_tables
from .main import SESSION_COOKIE, arr_get, db, get_instance, instance_payload, records_from, require_user
from .path_advice import expand_mapping, mapping_for_container_path, path_visibility, suggested_same_path_mount

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
    return {
        "id": client.get("id"),
        "name": client.get("name") or implementation,
        "implementation": implementation,
        "protocol": client.get("protocol"),
        "enabled": bool(client.get("enable", True)),
        "host": _field_value(client, "host"),
        "port": _field_value(client, "port"),
        "category": _field_value(client, "category"),
        "urlBase": _field_value(client, "urlBase", "urlbase"),
    }


def _path_mappings() -> list[dict[str, Any]]:
    ensure_doctor_tables()
    with db() as conn:
        rows = conn.execute("SELECT id, name, host_path, container_path FROM path_mappings ORDER BY id").fetchall()
    return [
        {"id": row["id"], "name": row["name"], "hostPath": row["host_path"], "containerPath": row["container_path"]}
        for row in rows
    ]


def _remote_mapping_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item.get("id"), "host": item.get("host"), "remotePath": item.get("remotePath"), "localPath": item.get("localPath")}


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
    return any(token in lowered for token in (
        "path does not exist", "path is not accessible", "folder does not exist", "directory does not exist",
        "no files found", "remote path", "unable to import", "not a valid local path", "access to the path", "permission denied",
    ))


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
        remote_base = remote.rstrip("/")
        if path == remote_base or path.startswith(remote_base + "/"):
            return local.rstrip("/") + path[len(remote_base):], mapping
    return path, None


def _suggestion(raw_path: str, mapped_path: str, client_host: str, applied: dict[str, Any] | None, manual_mappings: list[dict[str, Any]]) -> dict[str, Any]:
    visibility = path_visibility(mapped_path)
    manual = mapping_for_container_path(mapped_path, manual_mappings)
    suggestion: dict[str, Any] = {"verified": False, "kind": "unknown", "message": "ArrMedic cannot determine the correct container mapping from API data alone."}

    if manual:
        expanded = expand_mapping(mapped_path, manual)
        suggestion = {
            "verified": True,
            "kind": "saved_mapping",
            "message": "A saved host↔container mapping covers this path.",
            "hostPath": expanded["hostPath"],
            "containerPath": expanded["containerPath"],
            "dockerMount": f"--mount type=bind,source={manual['hostPath']},target={manual['containerPath']}",
        }
    elif visibility.get("visible") and visibility.get("source") == "host":
        suggestion = {
            "verified": True,
            "kind": "same_path",
            "message": "The same absolute path exists on the host. Using the same path in both downloader and *Arr is the simplest layout.",
            "hostPath": mapped_path,
            "containerPath": mapped_path,
            "dockerMount": suggested_same_path_mount(mapped_path),
        }
    elif client_host and raw_path and not applied:
        suggestion = {
            "verified": False,
            "kind": "remote_path_mapping_needed",
            "message": "The downloader path is not visible at the same host path and no matching Remote Path Mapping is active. Add a verified host↔container mapping in Path Doctor first; ArrMedic can then show the exact Radarr/Sonarr mapping.",
            "remoteHost": client_host,
            "remotePath": raw_path,
        }

    if applied:
        suggestion["remotePathMapping"] = {
            "host": applied.get("host"), "remotePath": applied.get("remotePath"), "localPath": applied.get("localPath")
        }
    return {"visibility": visibility, "manualMapping": manual, "suggestion": suggestion}


async def diagnose_instance(instance_id: int) -> dict[str, Any]:
    instance = get_instance(instance_id)
    if instance["kind"] not in SUPPORTED_KINDS:
        raise HTTPException(status_code=400, detail="Download Client Doctor currently supports Radarr and Sonarr")

    payload = instance_payload(instance)
    preferred = instance["api_version"] if "api_version" in instance.keys() else None
    clients_raw, _ = await arr_get(payload, "downloadclient", preferred_version=preferred)
    remote_raw, _ = await arr_get(payload, "remotepathmapping", preferred_version=preferred, allow_missing=True)
    queue_raw, _ = await arr_get(payload, "queue", preferred_version=preferred, params={"page": 1, "pageSize": 100}, allow_missing=True)

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

        if raw_path:
            mapped_path, applied = _apply_remote_mapping(raw_path, remotes, client_host or None)
            advice = _suggestion(raw_path, mapped_path, client_host, applied, manual_mappings)
            visibility = advice["visibility"]
            path_rows.append({
                "title": item.get("title") or item.get("movie", {}).get("title") or item.get("series", {}).get("title") or "Queue item",
                "downloadClient": client_name or (client.get("name") if client else None),
                "downloadClientHost": client_host or None,
                "reportedPath": raw_path,
                "mappedPath": mapped_path,
                "remoteMapping": applied,
                "arrmedicMapping": advice["manualMapping"],
                "visibility": visibility,
                "suggestion": advice["suggestion"],
                "status": item.get("status"),
                "trackedDownloadState": item.get("trackedDownloadState"),
            })

            if not visibility.get("visible"):
                issues.append({
                    "severity": "error",
                    "code": "unmapped_download_path",
                    "title": "Download path is not mapped to a visible host path",
                    "message": f"{client_name or client_host or 'Download client'} reported {raw_path}. After Remote Path Mapping, {instance['name']} would use {mapped_path}, but ArrMedic cannot verify that path on the read-only host filesystem.",
                    "path": raw_path,
                    "mappedPath": mapped_path,
                    "downloadClient": client_name or None,
                    "suggestion": advice["suggestion"],
                })
            elif visibility.get("source") == "host" and not applied and raw_path != mapped_path:
                issues.append({
                    "severity": "warning",
                    "code": "path_mapping_review",
                    "title": "Review download path mapping",
                    "message": f"The path resolves on the host, but the downloader and {instance['name']} are not using an explicitly verified mapping.",
                    "path": raw_path,
                    "mappedPath": mapped_path,
                    "suggestion": advice["suggestion"],
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

    seen: set[tuple[str, str, str]] = set()
    unique_issues: list[dict[str, Any]] = []
    for issue in issues:
        marker = (str(issue.get("code")), str(issue.get("message")), str(issue.get("path") or ""))
        if marker not in seen:
            seen.add(marker)
            unique_issues.append(issue)

    return {
        "instanceId": instance["id"], "instanceName": instance["name"], "kind": instance["kind"],
        "clients": clients, "remotePathMappings": remotes, "queuePaths": path_rows, "manualPathMappings": manual_mappings,
        "issues": unique_issues, "issueCount": len(unique_issues), "status": "problem" if unique_issues else "ok",
        "help": {
            "samePathRule": "On one Docker host, prefer one common path in the downloader and *Arr containers, for example /data/downloads.",
            "remotePathRule": "Use Remote Path Mapping only when the downloader reports a path that Radarr/Sonarr cannot use directly. ArrMedic only shows an exact mapping when it can verify the host↔container relationship.",
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
