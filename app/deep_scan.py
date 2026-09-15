from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from .download_doctor import diagnose_instance as diagnose_download_clients

MEDIA_KINDS = {"radarr", "sonarr", "lidarr", "readarr", "whisparr"}
DOWNLOAD_DOCTOR_KINDS = {"radarr", "sonarr"}
LOW_SPACE_BYTES = 10 * 1024**3


def _status_for_issues(issues: list[dict[str, Any]]) -> str:
    if any(str(item.get("severity") or "").lower() == "error" for item in issues):
        return "fail"
    return "warn" if issues else "pass"


def _records(data: object | None) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


def _total_records(data: object | None) -> int | None:
    if isinstance(data, dict):
        for key in ("totalRecords", "total", "totalCount"):
            value = data.get(key)
            if isinstance(value, int):
                return value
    if isinstance(data, list):
        return len(data)
    return None


def _contains_permission_problem(value: object) -> bool:
    text = str(value or "").lower()
    tokens = (
        "permission denied",
        "access denied",
        "not writable",
        "not writeable",
        "not accessible",
        "access to the path",
        "unauthorizedaccessexception",
        "read-only file system",
    )
    return any(token in text for token in tokens)


def _native_permission_signals(report: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for health in report.get("health", []) or []:
        if not isinstance(health, dict):
            continue
        text = " ".join(str(health.get(key) or "") for key in ("message", "source", "type"))
        if _contains_permission_problem(text):
            messages.append(text)
    for issue in report.get("queueIssues", []) or []:
        if not isinstance(issue, dict):
            continue
        text = str(issue.get("message") or "")
        if _contains_permission_problem(text):
            messages.append(text)
    return list(dict.fromkeys(messages))[:10]


def _extra_recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    checks = {item.get("code"): item for item in report.get("checks", [])}
    recommendations: list[dict[str, Any]] = []

    if checks.get("download_path_doctor", {}).get("status") in {"warn", "fail"}:
        recommendations.append(
            {
                "code": "fix_download_paths",
                "title": "Fix downloader and import paths",
                "priority": "high",
                "summary": "The download client and Radarr/Sonarr are not agreeing on one or more download paths.",
                "steps": [
                    "Open Download Client Doctor and review the reported path, Remote Path Mapping and suggested Docker mount.",
                    "On one Docker host, prefer the same common container path in the downloader and *Arr app, such as /data/downloads.",
                    "Use Remote Path Mapping only when different hosts or intentionally different paths make it necessary.",
                    "Retest one completed download before changing a large queue.",
                ],
            }
        )

    if checks.get("native_permissions", {}).get("status") in {"warn", "fail"}:
        recommendations.append(
            {
                "code": "fix_native_permissions",
                "title": "Fix filesystem permissions seen by the app",
                "priority": "high",
                "summary": "The application is reporting a native access or permission error.",
                "steps": [
                    "Check the exact path shown in the health or queue message.",
                    "Confirm the *Arr container and download client use compatible UID/GID ownership and permissions.",
                    "Confirm the path is mounted into the container at the path the application expects.",
                    "After correcting ownership or mounts, use the application's built-in Test/Refresh and run ArrMedic again.",
                ],
            }
        )

    if checks.get("hardlinks_enabled", {}).get("status") == "warn":
        recommendations.append(
            {
                "code": "enable_hardlinks",
                "title": "Enable hardlinks when your filesystem layout supports them",
                "priority": "medium",
                "summary": "The app reports hardlink/copy-on-import support disabled.",
                "steps": [
                    "Keep downloads and media on the same filesystem and expose them through one common container mount.",
                    "Enable hardlink/copy-on-import support in Media Management if that matches your workflow.",
                    "Run Hardlink Doctor again after the path layout is corrected.",
                ],
            }
        )

    if checks.get("indexer_configuration", {}).get("status") == "warn":
        recommendations.append(
            {
                "code": "fix_indexer_configuration",
                "title": "Configure an enabled indexer",
                "priority": "medium",
                "summary": "The application exposes indexer settings but no enabled indexer was found.",
                "steps": [
                    "Enable or add at least one suitable indexer.",
                    "Use the application's Test button for the indexer.",
                    "If Prowlarr manages this app, check Prowlarr application sync and run a sync test.",
                ],
            }
        )

    return recommendations


def install_deep_scan(main_module) -> None:
    """Upgrade every existing diagnostic route to a broad read-only scan."""

    if getattr(main_module, "_ARRMEDIC_DEEP_SCAN_INSTALLED", False):
        return

    base_build_instance_diagnostics = main_module.build_instance_diagnostics

    async def deep_build_instance_diagnostics(row):
        report = await base_build_instance_diagnostics(row)
        report["scanMode"] = "deep-readonly"
        report["capabilitiesScanned"] = [
            "connection",
            "native-health",
            "root-folders",
            "storage",
            "queue-imports",
            "download-clients",
            "remote-path-mappings",
            "recent-history",
            "path-visibility",
            "permissions",
            "hardlink-filesystem",
        ]

        if report.get("status") != "online":
            return report

        payload = main_module.instance_payload(row)
        preferred = report.get("apiVersion") or (row["api_version"] if "api_version" in row.keys() else None)
        kind = str(row["kind"])

        async def optional(endpoint: str, params: dict | None = None):
            try:
                data, _ = await main_module.arr_get(
                    payload,
                    endpoint,
                    preferred_version=preferred,
                    params=params,
                    allow_missing=True,
                )
                return data
            except HTTPException:
                return None

        diskspace_data, media_management, missing_data, applications_data, indexers_data, tasks_data = await asyncio.gather(
            optional("diskspace"),
            optional("config/mediamanagement") if kind in MEDIA_KINDS else asyncio.sleep(0, result=None),
            optional("wanted/missing", {"page": 1, "pageSize": 1}) if kind in MEDIA_KINDS else asyncio.sleep(0, result=None),
            optional("applications") if kind == "prowlarr" else asyncio.sleep(0, result=None),
            optional("indexer"),
            optional("system/task"),
        )

        checks = report.setdefault("checks", [])
        capabilities = report["capabilitiesScanned"]

        if diskspace_data is not None:
            capabilities.append("disk-space")
            disks = _records(diskspace_data)
            low = []
            for disk in disks:
                free = disk.get("freeSpace")
                if isinstance(free, (int, float)) and free < LOW_SPACE_BYTES:
                    low.append({"path": disk.get("path"), "freeSpace": free, "totalSpace": disk.get("totalSpace")})
            if low:
                checks.append(main_module.check("disk_space", "Disk space", "warn", f"{len(low)} filesystem(s) have less than 10 GiB free.", low))
            elif disks:
                checks.append(main_module.check("disk_space", "Disk space", "pass", f"{len(disks)} filesystem(s) checked."))
            report["diskSpace"] = disks

        if media_management is not None and isinstance(media_management, dict):
            capabilities.append("media-management")
            report["mediaManagement"] = media_management
            hardlink_value = media_management.get("copyUsingHardlinks")
            if isinstance(hardlink_value, bool):
                checks.append(
                    main_module.check(
                        "hardlinks_enabled",
                        "Hardlink import setting",
                        "pass" if hardlink_value else "warn",
                        "Hardlink/copy-on-import support is enabled." if hardlink_value else "Hardlink/copy-on-import support is disabled in Media Management.",
                    )
                )

        if missing_data is not None:
            capabilities.append("missing-media")
            missing_count = _total_records(missing_data)
            report["missingMediaCount"] = missing_count
            if missing_count is not None:
                checks.append(
                    main_module.check(
                        "missing_media",
                        "Missing media",
                        "info" if missing_count else "pass",
                        f"{missing_count} monitored item(s) are currently reported missing." if missing_count else "No monitored missing-media items reported.",
                    )
                )

        if indexers_data is not None:
            capabilities.append("indexers")
            indexers = _records(indexers_data)
            report["indexers"] = indexers
            enabled = [item for item in indexers if item.get("enable", True)]
            # Prowlarr already has a core indexer check; avoid counting it twice.
            if kind != "prowlarr":
                checks.append(
                    main_module.check(
                        "indexer_configuration",
                        "Indexers",
                        "pass" if enabled else "warn",
                        f"{len(enabled)} enabled indexer(s) found." if enabled else "Indexer settings are available, but no enabled indexer was found.",
                    )
                )

        if tasks_data is not None:
            capabilities.append("scheduled-tasks")
            tasks = _records(tasks_data)
            report["scheduledTasks"] = tasks
            if tasks:
                checks.append(main_module.check("scheduled_tasks", "Scheduled tasks", "pass", f"{len(tasks)} application task(s) are visible to ArrMedic."))

        permission_signals = _native_permission_signals(report)
        if permission_signals:
            checks.append(
                main_module.check(
                    "native_permissions",
                    "Application filesystem permissions",
                    "fail",
                    f"{len(permission_signals)} native permission/access problem(s) were reported by the application.",
                    permission_signals,
                )
            )
            report.setdefault("doctors", {})["permission"] = {
                "status": "warn",
                "message": "The application itself reports a filesystem access/permission problem. Review the native messages below as well as ArrMedic mount visibility.",
                "nativeSignals": permission_signals,
            }

        if kind in DOWNLOAD_DOCTOR_KINDS:
            capabilities.append("download-client-path-correlation")
            try:
                download_report = await diagnose_download_clients(int(row["id"]))
                report["downloadClientDoctor"] = download_report
                issues = download_report.get("issues", []) if isinstance(download_report, dict) else []
                status = _status_for_issues(issues)
                checks.append(
                    main_module.check(
                        "download_path_doctor",
                        "Download client paths",
                        status,
                        f"{len(issues)} downloader/path issue(s) detected." if issues else "Download-client queue paths and Remote Path Mappings look consistent from the API view.",
                        issues[:15],
                    )
                )
            except Exception as exc:  # one doctor must never break the complete scan
                checks.append(main_module.check("download_path_doctor", "Download client paths", "info", f"Download Client Doctor could not complete: {exc}"))

        if kind == "prowlarr" and applications_data is not None:
            capabilities.append("prowlarr-applications")
            applications = _records(applications_data)
            report["applications"] = applications
            checks.append(
                main_module.check(
                    "prowlarr_applications",
                    "Prowlarr applications",
                    "pass" if applications else "info",
                    f"{len(applications)} connected application(s) found." if applications else "No Prowlarr application connections are configured.",
                )
            )

        report["score"] = main_module.score_checks(checks)
        report["recommendations"] = main_module.build_recommendations(report)
        existing_rec_codes = {item.get("code") for item in report["recommendations"] if isinstance(item, dict)}
        for recommendation in _extra_recommendations(report):
            if recommendation.get("code") not in existing_rec_codes:
                report["recommendations"].append(recommendation)

        priority_order = {"high": 0, "medium": 1, "low": 2}
        report["recommendations"].sort(key=lambda item: (priority_order.get(item.get("priority"), 9), str(item.get("title") or "")))
        report["deepCheckedAt"] = datetime.now(timezone.utc).isoformat()
        return report

    main_module.build_instance_diagnostics = deep_build_instance_diagnostics
    main_module._ARRMEDIC_DEEP_SCAN_INSTALLED = True


def install_auto_scan_middleware(app, main_module) -> None:
    """Run and save a full deep scan after add/edit/remove of an app."""

    if getattr(app.state, "arrmedic_auto_scan_installed", False):
        return
    app.state.arrmedic_auto_scan_installed = True

    @app.middleware("http")
    async def auto_scan_after_instance_change(request, call_next):
        response = await call_next(request)
        path = request.url.path.rstrip("/")
        method = request.method.upper()
        instance_mutation = (
            (method == "POST" and path == "/api/instances")
            or (method == "PUT" and path.startswith("/api/instances/"))
            or (method == "DELETE" and path.startswith("/api/instances/"))
        )
        if instance_mutation and 200 <= response.status_code < 300:
            try:
                summary = await main_module.build_summary()
                run_id = main_module.save_scan(summary)
                response.headers["X-ArrMedic-Auto-Scan"] = "complete"
                response.headers["X-ArrMedic-Scan-Id"] = str(run_id)
            except Exception:
                # Saving the app must not be rolled back because a later read-only
                # diagnostic endpoint is temporarily unavailable.
                response.headers["X-ArrMedic-Auto-Scan"] = "partial"
        return response
