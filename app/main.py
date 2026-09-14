from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
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

app = FastAPI(
    title="ArrMedic",
    version="0.2.0",
    description="Open-source diagnostics and health monitoring for the *Arr media stack.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
                created_at TEXT NOT NULL
            );
            """
        )


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


async def probe_instance(payload: InstanceRequest) -> dict:
    base_url = str(payload.url).rstrip("/")
    headers = {"X-Api-Key": payload.api_key}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            response = await client.get(f"{base_url}/api/v3/system/status", headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail=f"{payload.kind.title()} returned HTTP {exc.response.status_code}") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Unable to connect to {payload.kind.title()}: {exc}") from exc

    return {
        "ok": True,
        "kind": payload.kind,
        "appName": data.get("appName", payload.kind.title()),
        "version": data.get("version", "unknown"),
        "osName": data.get("osName", "unknown"),
        "runtimeVersion": data.get("runtimeVersion", "unknown"),
    }


init_db()


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "healthy", "name": "ArrMedic", "version": "0.2.0"}


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
            "SELECT id, name, kind, url, version, os_name, created_at FROM instances ORDER BY id"
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
            INSERT INTO instances(name, kind, url, api_key_enc, version, os_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.kind,
                str(payload.url).rstrip("/"),
                encrypted_key,
                status["version"],
                status["osName"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        instance_id = cursor.lastrowid
    return {"ok": True, "id": instance_id, **status}


@app.delete("/api/instances/{instance_id}")
async def delete_instance(instance_id: int, arrmedic_session: str | None = Cookie(default=None)) -> dict:
    require_user(arrmedic_session)
    with db() as conn:
        cursor = conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"ok": True}
