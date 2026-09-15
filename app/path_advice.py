from __future__ import annotations

from typing import Any

from .hostfs import local_path_info


def path_visibility(path_value: str | None) -> dict[str, Any]:
    """Return host-mirror visibility for an app/download path."""
    if not path_value:
        return {
            "path": path_value,
            "visible": False,
            "readable": False,
            "checkedPath": None,
            "source": None,
        }
    return local_path_info(str(path_value))


def mapping_for_container_path(path_value: str, mappings: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the most-specific saved host↔container mapping for a path."""
    matches: list[tuple[int, dict[str, Any]]] = []
    for mapping in mappings:
        container = str(mapping.get("containerPath") or "").rstrip("/")
        if container and (path_value == container or path_value.startswith(container + "/")):
            matches.append((len(container), mapping))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def expand_mapping(path_value: str, mapping: dict[str, Any]) -> dict[str, str]:
    container = str(mapping.get("containerPath") or "").rstrip("/")
    host = str(mapping.get("hostPath") or "").rstrip("/")
    suffix = path_value[len(container):] if container and path_value.startswith(container) else ""
    return {
        "hostPath": host + suffix,
        "containerPath": path_value,
    }


def suggested_same_path_mount(path_value: str) -> str:
    return f"--mount type=bind,source={path_value},target={path_value},readonly"
