from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(
    title="ArrMedic",
    version="0.1.0",
    description="Open-source diagnostics and health monitoring for the *Arr media stack.",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class InstanceTestRequest(BaseModel):
    kind: Literal["sonarr", "radarr", "prowlarr", "lidarr"]
    url: HttpUrl
    api_key: str


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "healthy",
        "name": "ArrMedic",
        "version": "0.1.0",
    }


@app.post("/api/instances/test")
async def test_instance(payload: InstanceTestRequest) -> dict:
    base_url = str(payload.url).rstrip("/")
    headers = {"X-Api-Key": payload.api_key}

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            response = await client.get(f"{base_url}/api/v3/system/status", headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{payload.kind.title()} returned HTTP {exc.response.status_code}",
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to connect to {payload.kind.title()}: {exc}",
        ) from exc

    return {
        "ok": True,
        "kind": payload.kind,
        "appName": data.get("appName", payload.kind.title()),
        "version": data.get("version", "unknown"),
        "osName": data.get("osName", "unknown"),
        "runtimeVersion": data.get("runtimeVersion", "unknown"),
    }
