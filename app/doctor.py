from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from .main import SESSION_COOKIE, db, local_path_info, require_user

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


class PathMappingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    host_path: str = Field(min_length=1, max_length=1000)
    container_path: str = Field(min_length=1, max_length=1000)
    notes: str = Field(default="", max_length=500)


def ensure_tables() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS path_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                host_path TEXT NOT NULL,
                container_path TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def mapping_status(row) -> dict:
    container_path = str(row["container_path"])
    info = local_path_info(container_path)
    host_path = str(row["host_path"])
    same_text = os.path.normpath(host_path) == os.path.normpath(container_path)
    if info.get("visible"):
        status = "ok"
        message = "Container path is visible to ArrMedic."
    else:
        status = "missing"
        message = "Container path is not visible to ArrMedic. Add the host path as a Docker bind mount using this container path."
    return {
        "id": row["id"],
        "name": row["name"],
        "hostPath": host_path,
        "containerPath": container_path,
        "notes": row["notes"],
        "status": status,
        "message": message,
        "samePath": same_text,
        "local": info,
        "dockerMount": f"--mount type=bind,source={host_path},target={container_path},readonly",
    }


@router.get("/mappings")
async def list_mappings(arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    ensure_tables()
    with db() as conn:
        rows = conn.execute("SELECT * FROM path_mappings ORDER BY id DESC").fetchall()
    return {"items": [mapping_status(row) for row in rows]}


@router.post("/mappings")
async def create_mapping(request: PathMappingCreate, arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    ensure_tables()
    name = request.name.strip()
    host_path = request.host_path.strip()
    container_path = request.container_path.strip()
    if not host_path.startswith("/") or not container_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Host and container paths must be absolute Linux paths starting with /")
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO path_mappings(name, host_path, container_path, notes) VALUES (?, ?, ?, ?)",
            (name, host_path, container_path, request.notes.strip()),
        )
        row = conn.execute("SELECT * FROM path_mappings WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return mapping_status(row)


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(mapping_id: int, arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    ensure_tables()
    with db() as conn:
        row = conn.execute("SELECT id FROM path_mappings WHERE id = ?", (mapping_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Path mapping not found")
        conn.execute("DELETE FROM path_mappings WHERE id = ?", (mapping_id,))
    return {"ok": True}


@router.get("/runtime")
async def doctor_runtime(arrmedic_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(arrmedic_session)
    cwd = Path.cwd()
    return {
        "workingDirectory": str(cwd),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "dockerSocketVisible": Path("/var/run/docker.sock").exists(),
        "dockerSocketEnabled": False,
        "message": "Docker socket access is intentionally disabled by default. ArrMedic uses safe manual path mappings unless an optional Docker integration is added later.",
    }
