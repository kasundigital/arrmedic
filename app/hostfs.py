from __future__ import annotations

import os
import shutil
from pathlib import Path

DEFAULT_HOST_ROOT = "/host"


def host_root() -> Path:
    value = os.environ.get("ARRMEDIC_HOST_ROOT", DEFAULT_HOST_ROOT).strip() or DEFAULT_HOST_ROOT
    return Path(value)


def _candidate_paths(path_value: str) -> list[tuple[str, Path]]:
    requested = Path(path_value)
    candidates: list[tuple[str, Path]] = []
    root = host_root()

    # When the host root is mounted read-only at /host, translate an absolute
    # path reported by Radarr/Sonarr/etc. into the host mirror first.
    if requested.is_absolute() and root.exists():
        relative = str(requested).lstrip("/")
        candidates.append(("host", root / relative))

    # Preserve compatibility with explicit same-path read-only mounts.
    candidates.append(("container", requested))
    return candidates


def local_path_info(path_value: str) -> dict:
    result = {
        "path": path_value,
        "visible": False,
        "readable": False,
        "writable": False,
        "permissionWritable": False,
        "mountReadOnly": None,
        "checkedPath": None,
        "source": None,
        "hostRoot": str(host_root()),
        "hostRootVisible": host_root().exists(),
    }

    for source, candidate in _candidate_paths(path_value):
        try:
            if not candidate.exists():
                continue

            stat_result = candidate.stat()
            usage = shutil.disk_usage(candidate)
            statvfs = os.statvfs(candidate)
            read_only_flag = getattr(os, "ST_RDONLY", 1)
            mount_read_only = bool(statvfs.f_flag & read_only_flag)
            permission_writable = os.access(candidate, os.W_OK)

            result.update(
                {
                    "visible": True,
                    "readable": os.access(candidate, os.R_OK),
                    # Never advertise a read-only diagnostic mount as writable.
                    "writable": bool(permission_writable and not mount_read_only),
                    "permissionWritable": permission_writable,
                    "mountReadOnly": mount_read_only,
                    "checkedPath": str(candidate),
                    "source": source,
                    "device": stat_result.st_dev,
                    "freeBytes": usage.free,
                    "totalBytes": usage.total,
                    "freePercent": round((usage.free / usage.total) * 100, 1) if usage.total else None,
                }
            )
            return result
        except OSError as exc:
            result["error"] = str(exc)
            result["checkedPath"] = str(candidate)
            result["source"] = source

    return result


def install_host_filesystem(main_module) -> None:
    """Use /host as the preferred read-only view of the host filesystem."""
    main_module.local_path_info = local_path_info

    # doctor.py imports local_path_info directly, so patch its module alias too.
    try:
        from . import doctor as doctor_module

        doctor_module.local_path_info = local_path_info
    except Exception:
        pass
