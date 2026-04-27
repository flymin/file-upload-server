#!/usr/bin/env python3
"""FastAPI file upload server with stable token API + redesigned multi-user web workspace."""

import asyncio
import base64
import hashlib
import hmac
import html
import json
import math
import mimetypes
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import uvicorn
import yaml
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Request, Security, UploadFile
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

# ─── Config ──────────────────────────────────────────────────────────────────

PORT = int((os.environ.get("PORT") or "8091").strip())
TOKEN_HEADER_NAME = "X-Upload-Token"
UPLOAD_TOKEN = (os.environ.get("UPLOAD_TOKEN") or "").strip()
SESSION_COOKIE_NAME = "file_upload_session"
PBKDF2_ALGORITHM = "pbkdf2_sha256"

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">\n  <defs>\n    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">\n      <stop offset="0%" stop-color="#60a5fa"/>\n      <stop offset="100%" stop-color="#6366f1"/>\n    </linearGradient>\n  </defs>\n  <rect x="10" y="6" width="44" height="52" rx="10" fill="url(#g)"/>\n  <rect x="22" y="2" width="20" height="10" rx="5" fill="#1e293b" opacity="0.9"/>\n  <rect x="18" y="18" width="28" height="4" rx="2" fill="white" opacity="0.95"/>\n  <rect x="18" y="28" width="20" height="4" rx="2" fill="white" opacity="0.95"/>\n  <rect x="18" y="38" width="24" height="4" rx="2" fill="white" opacity="0.95"/>\n</svg>"""
FAVICON_DATA_URI = "data:image/svg+xml," + quote(FAVICON_SVG)

BASE_DIR = Path(__file__).parent
CONFIG_PATH = Path((os.environ.get("CONFIG_PATH") or str(BASE_DIR / "config.yaml")).strip())
DATA_DIR = BASE_DIR / "data"
API_CHUNKS_DIR = DATA_DIR / ".chunks"
WEB_ROOT_DIR = DATA_DIR / "web"
WEB_USERS_DIR = WEB_ROOT_DIR / "users"

DATA_DIR.mkdir(exist_ok=True)
API_CHUNKS_DIR.mkdir(exist_ok=True)
WEB_USERS_DIR.mkdir(parents=True, exist_ok=True)

# Legacy API upload state, kept for interface compatibility.
upload_tracker: Dict[str, dict] = {}
completed_uploads: Dict[str, dict] = {}

# Web upload concurrency guards.
web_upload_locks: Dict[str, asyncio.Lock] = {}
user_state_locks: Dict[str, asyncio.Lock] = {}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"config file not found: {CONFIG_PATH}")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    app_cfg = raw.get("app") or {}
    users_cfg = raw.get("users") or []

    session_secret = str(app_cfg.get("session_secret") or "").strip()
    if not session_secret:
        raise RuntimeError("config.yaml: app.session_secret is required")

    users: Dict[str, dict] = {}
    for entry in users_cfg:
        if not isinstance(entry, dict):
            continue
        username = str(entry.get("username") or "").strip()
        password_hash = str(entry.get("password_hash") or "").strip()
        display_name = str(entry.get("display_name") or username).strip() or username
        if username and password_hash:
            users[username] = {
                "username": username,
                "display_name": display_name,
                "password_hash": password_hash,
            }

    if not users:
        raise RuntimeError("config.yaml: at least one user with username/password_hash is required")

    return {
        "session_secret": session_secret.encode("utf-8"),
        "session_max_age_seconds": int(app_cfg.get("session_max_age_seconds") or 2592000),
        "clipboard_history_limit": int(app_cfg.get("clipboard_history_limit") or 100),
        "clipboard_max_chars": int(app_cfg.get("clipboard_max_chars") or 200000),
        "web_file_retention_days": int(app_cfg.get("web_file_retention_days") or 7),
        "web_upload_parallelism": max(1, int(app_cfg.get("web_upload_parallelism") or 4)),
        "users": users,
    }


SETTINGS = load_config()

app = FastAPI(
    title="File Upload Server",
    description="Stable token upload API plus multi-user web workspace.",
    version="3.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

api_key_header = APIKeyHeader(name=TOKEN_HEADER_NAME, auto_error=False)


class ClipboardPayload(BaseModel):
    text: str


class WebUploadInitPayload(BaseModel):
    filename: str
    size: int
    content_type: Optional[str] = None
    last_modified_ms: Optional[int] = None


# ─── Auth ────────────────────────────────────────────────────────────────────

class SilentReject(Exception):
    """Best-effort silent reject for unauthorized requests."""


class RangeNotSatisfiable(Exception):
    pass


def require_token(token: Optional[str] = Security(api_key_header)) -> str:
    if not UPLOAD_TOKEN:
        return ""
    if not token or not secrets.compare_digest(token, UPLOAD_TOKEN):
        raise SilentReject()
    return token


@app.exception_handler(SilentReject)
async def silent_reject_handler(request, exc):
    return Response(status_code=404, content=b"", headers={"Connection": "close"})


# ─── Common helpers ──────────────────────────────────────────────────────────


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def extract_filename(name: str) -> str:
    raw = (name or "").replace("\\", "/").strip()
    base = os.path.basename(raw)
    if base in ("", ".", ".."):
        return "unnamed"
    return base


def safe_temp_component(name: str) -> str:
    base = extract_filename(name)
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)
    return cleaned or "unnamed"


def normalize_file_id(file_id: Optional[str]) -> str:
    raw = (file_id or uuid.uuid4().hex).strip()
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)
    return cleaned or uuid.uuid4().hex


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_password(password: str, encoded_hash: str) -> bool:
    if not encoded_hash:
        return False
    try:
        algorithm, iterations_text, salt_hex, digest_hex = encoded_hash.split("$", 3)
        if algorithm != PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
    except (TypeError, ValueError):
        return False

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    ).hex()
    return secrets.compare_digest(derived, digest_hex.lower())


def auth_configured() -> bool:
    return bool(SETTINGS["users"])


def create_session_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + max(60, SETTINGS["session_max_age_seconds"]),
    }
    payload_b64 = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        SETTINGS["session_secret"],
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or "." not in token:
        return None

    payload_b64, provided_signature = token.rsplit(".", 1)
    expected_signature = hmac.new(
        SETTINGS["session_secret"],
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not secrets.compare_digest(expected_signature, provided_signature):
        return None

    try:
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    if int(payload.get("exp", 0)) < int(time.time()):
        return None

    username = str(payload.get("sub") or "").strip()
    if not username or username not in SETTINGS["users"]:
        return None
    return username


def sanitize_next_url(next_url: Optional[str]) -> str:
    if not next_url:
        return "/app"
    cleaned = next_url.strip()
    if not cleaned.startswith("/") or cleaned.startswith("//"):
        return "/app"
    return cleaned


def build_login_redirect(request: Request) -> RedirectResponse:
    next_url = quote(str(request.url.path or "/app"), safe="/?=&%")
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


def require_page_login(request: Request):
    username = get_current_user(request)
    if not username:
        return None, build_login_redirect(request)
    return username, None


def require_json_login(request: Request) -> str:
    username = get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Login required")
    return username


def get_user_state_lock(username: str) -> asyncio.Lock:
    if username not in user_state_locks:
        user_state_locks[username] = asyncio.Lock()
    return user_state_locks[username]


def get_web_upload_lock(upload_id: str) -> asyncio.Lock:
    if upload_id not in web_upload_locks:
        web_upload_locks[upload_id] = asyncio.Lock()
    return web_upload_locks[upload_id]


# ─── Legacy API helpers ──────────────────────────────────────────────────────


def get_upload_key(file_id: str, filename: str) -> str:
    return f"{file_id}:{filename}"


def build_unique_path(filename: str) -> Path:
    filename = extract_filename(filename)
    dest = DATA_DIR / filename
    if not dest.exists():
        return dest

    name, ext = os.path.splitext(filename)
    index = 1
    while True:
        candidate = DATA_DIR / f"{name}_{index}{ext}"
        if not candidate.exists():
            return candidate
        index += 1


def chunk_part_path(file_id: str, filename: str, chunk_index: int) -> Path:
    prefix = f"{normalize_file_id(file_id)}__{safe_temp_component(filename)}"
    return API_CHUNKS_DIR / f"{prefix}.part{chunk_index:06d}"


def cleanup_chunks(file_id: str, filename: str) -> None:
    prefix = f"{normalize_file_id(file_id)}__{safe_temp_component(filename)}"
    for part in API_CHUNKS_DIR.glob(f"{prefix}.part*"):
        try:
            part.unlink()
        except FileNotFoundError:
            pass


def serialize_tracker() -> Dict[str, dict]:
    data: Dict[str, dict] = {}
    for key, meta in upload_tracker.items():
        data[key] = {
            "file_id": meta["file_id"],
            "filename": meta["filename"],
            "total": meta["total"],
            "received": sorted(meta["received"]),
            "size": meta["size"],
        }
    return data


def assemble_chunks(file_id: str, filename: str, total: int, received: Set[int]) -> Optional[Path]:
    if len(received) != total:
        return None

    final_path = build_unique_path(filename)
    with open(final_path, "wb") as out:
        for idx in range(1, total + 1):
            part = chunk_part_path(file_id, filename, idx)
            if not part.exists():
                return None
            with open(part, "rb") as inp:
                shutil.copyfileobj(inp, out)

    cleanup_chunks(file_id, filename)
    return final_path


# ─── Web workspace helpers ───────────────────────────────────────────────────


def user_slug(username: str) -> str:
    return safe_temp_component(username)


def user_root_dir(username: str) -> Path:
    path = WEB_USERS_DIR / user_slug(username)
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_files_dir(username: str) -> Path:
    path = user_root_dir(username) / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_uploads_dir(username: str) -> Path:
    path = user_root_dir(username) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_clipboard_file(username: str) -> Path:
    return user_root_dir(username) / "clipboard-history.json"


def user_files_index_file(username: str) -> Path:
    return user_root_dir(username) / "files-index.json"


def read_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_file(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_clipboard_items(username: str) -> List[dict]:
    data = read_json_file(user_clipboard_file(username), {"items": []})
    items = data.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def save_clipboard_items(username: str, items: List[dict]) -> None:
    limit = SETTINGS["clipboard_history_limit"]
    write_json_file(user_clipboard_file(username), {"items": items[:limit]})


def upsert_clipboard_item(username: str, text: str) -> dict:
    cleaned = (text or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    if len(cleaned) > SETTINGS["clipboard_max_chars"]:
        raise HTTPException(status_code=400, detail="Text too long")

    now = now_iso()
    items = load_clipboard_items(username)
    for item in items:
        if item.get("text") == cleaned:
            item["updated_at"] = now
            item["created_at"] = item.get("created_at") or now
            save_clipboard_items(username, sorted(items, key=lambda x: x.get("updated_at") or "", reverse=True))
            return item

    item = {
        "id": uuid.uuid4().hex,
        "text": cleaned,
        "created_at": now,
        "updated_at": now,
    }
    items.insert(0, item)
    save_clipboard_items(username, items)
    return item


def delete_clipboard_item(username: str, item_id: str) -> bool:
    item_id = (item_id or "").strip()
    if not item_id:
        return False
    items = load_clipboard_items(username)
    new_items = [item for item in items if item.get("id") != item_id]
    if len(new_items) == len(items):
        return False
    save_clipboard_items(username, new_items)
    return True


def load_user_files(username: str) -> List[dict]:
    data = read_json_file(user_files_index_file(username), {"items": []})
    items = data.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def save_user_files(username: str, items: List[dict]) -> None:
    write_json_file(user_files_index_file(username), {"items": items})


def get_user_file_item(username: str, file_id: str) -> Optional[dict]:
    for item in load_user_files(username):
        if item.get("file_id") == file_id:
            return item
    return None


def determine_chunk_size(total_size: int) -> int:
    mib = 1024 * 1024
    if total_size <= 64 * mib:
        base = 2 * mib
    elif total_size <= 512 * mib:
        base = 8 * mib
    elif total_size <= 4 * 1024 * mib:
        base = 16 * mib
    else:
        base = 32 * mib

    target_max_chunks = 2048
    adaptive = max(mib, math.ceil(total_size / target_max_chunks / mib) * mib)
    return max(base, adaptive)


def compute_upload_fingerprint(filename: str, size: int, last_modified_ms: Optional[int]) -> str:
    raw = f"{extract_filename(filename)}\0{size}\0{last_modified_ms or 0}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def upload_dir(username: str, upload_id: str) -> Path:
    return user_uploads_dir(username) / normalize_file_id(upload_id)


def upload_meta_path(username: str, upload_id: str) -> Path:
    return upload_dir(username, upload_id) / "meta.json"


def upload_chunk_path(username: str, upload_id: str, chunk_index: int) -> Path:
    return upload_dir(username, upload_id) / "chunks" / f"part{chunk_index:06d}"


def list_active_upload_metas(username: str) -> List[dict]:
    metas: List[dict] = []
    for meta_path in sorted(user_uploads_dir(username).glob("*/meta.json")):
        meta = read_json_file(meta_path, None)
        if isinstance(meta, dict):
            metas.append(meta)
    return metas


def load_upload_meta(username: str, upload_id: str) -> Optional[dict]:
    meta = read_json_file(upload_meta_path(username, upload_id), None)
    if not isinstance(meta, dict):
        return None
    return meta


def save_upload_meta(username: str, upload_id: str, meta: dict) -> None:
    write_json_file(upload_meta_path(username, upload_id), meta)


def delete_upload_session(username: str, upload_id: str) -> None:
    shutil.rmtree(upload_dir(username, upload_id), ignore_errors=True)
    web_upload_locks.pop(normalize_file_id(upload_id), None)


def build_user_file_storage_name(file_id: str, filename: str) -> str:
    return f"{normalize_file_id(file_id)}__{safe_temp_component(filename)}"


def cleanup_expired_user_files(username: str) -> int:
    now = now_utc()
    kept: List[dict] = []
    removed = 0
    for item in load_user_files(username):
        expires_at = item.get("expires_at")
        file_path = user_files_dir(username) / str(item.get("stored_name") or "")
        expired = False
        if expires_at:
            try:
                expired = parse_iso(expires_at) <= now
            except ValueError:
                expired = True
        if expired or not file_path.exists():
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass
            removed += 1
            continue
        kept.append(item)
    if removed:
        save_user_files(username, kept)
    return removed


def cleanup_stale_upload_sessions(username: str) -> int:
    now = now_utc()
    removed = 0
    retention_days = SETTINGS["web_file_retention_days"]
    cutoff = now - timedelta(days=retention_days)
    for meta in list_active_upload_metas(username):
        updated_at = meta.get("updated_at") or meta.get("created_at")
        upload_id = str(meta.get("upload_id") or "").strip()
        if not updated_at or not upload_id:
            continue
        try:
            stale = parse_iso(updated_at) < cutoff
        except ValueError:
            stale = True
        if stale:
            delete_upload_session(username, upload_id)
            removed += 1
    return removed


def find_active_upload_by_fingerprint(username: str, fingerprint: str) -> Optional[dict]:
    candidates = []
    for meta in list_active_upload_metas(username):
        if meta.get("fingerprint") == fingerprint and not meta.get("completed"):
            candidates.append(meta)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return candidates[0]


def assemble_web_upload(username: str, upload_id: str, meta: dict) -> dict:
    total_chunks = int(meta["total_chunks"])
    received_chunks = sorted(int(x) for x in meta.get("received_chunks") or [])
    if received_chunks != list(range(1, total_chunks + 1)):
        missing = sorted(set(range(1, total_chunks + 1)) - set(received_chunks))
        raise HTTPException(status_code=400, detail={"message": "Upload incomplete", "missing": missing})

    file_id = normalize_file_id(meta.get("file_id") or upload_id)
    filename = extract_filename(meta["filename"])
    stored_name = build_user_file_storage_name(file_id, filename)
    final_path = user_files_dir(username) / stored_name

    with open(final_path, "wb") as out:
        for idx in range(1, total_chunks + 1):
            part = upload_chunk_path(username, upload_id, idx)
            if not part.exists():
                raise HTTPException(status_code=400, detail=f"Missing chunk {idx}")
            with open(part, "rb") as inp:
                shutil.copyfileobj(inp, out)

    expires_at = now_utc() + timedelta(days=SETTINGS["web_file_retention_days"])
    file_item = {
        "file_id": file_id,
        "original_name": filename,
        "stored_name": stored_name,
        "content_type": meta.get("content_type") or "application/octet-stream",
        "size": final_path.stat().st_size,
        "created_at": now_iso(),
        "expires_at": expires_at.isoformat(),
    }

    items = load_user_files(username)
    items.insert(0, file_item)
    save_user_files(username, items)
    delete_upload_session(username, upload_id)
    return file_item


def parse_range_header(range_header: Optional[str], file_size: int) -> Optional[Tuple[int, int]]:
    if not range_header:
        return None
    if not range_header.startswith("bytes="):
        raise RangeNotSatisfiable()

    ranges = range_header[6:].strip()
    if not ranges or "," in ranges:
        raise RangeNotSatisfiable()

    try:
        start_text, end_text = ranges.split("-", 1)
        if start_text == "":
            if not end_text:
                raise RangeNotSatisfiable()
            suffix = int(end_text)
            if suffix <= 0:
                raise RangeNotSatisfiable()
            start = max(file_size - suffix, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
            if start >= file_size:
                raise RangeNotSatisfiable()
            end = min(end, file_size - 1)
    except ValueError as exc:
        raise RangeNotSatisfiable() from exc

    if start < 0 or end < start:
        raise RangeNotSatisfiable()
    return start, end


def iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk_size, remaining))
            if not data:
                break
            yield data
            remaining -= len(data)


def format_bytes_for_display(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, value))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


# ─── UI ──────────────────────────────────────────────────────────────────────


def render_page(title: str, body: str) -> str:
    title_safe = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_safe}</title>
  <link rel="icon" href="{FAVICON_DATA_URI}" />
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --card: #ffffff;
      --line: #dbe4f0;
      --text: #0f172a;
      --muted: #475569;
      --accent: #2563eb;
      --accent-soft: #dbeafe;
      --danger: #dc2626;
      --success: #16a34a;
      --shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #eff6ff 0%, var(--bg) 180px);
      color: var(--text);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{ max-width: 1160px; margin: 0 auto; padding: 24px; }}
    .topbar {{
      display: flex; gap: 16px; align-items: center; justify-content: space-between;
      padding: 18px 22px; border: 1px solid var(--line); border-radius: 20px;
      background: rgba(255,255,255,0.82); backdrop-filter: blur(10px); box-shadow: var(--shadow);
      margin-bottom: 22px;
    }}
    .brand {{ display: flex; align-items: center; gap: 14px; }}
    .brand-icon {{ width: 46px; height: 46px; border-radius: 14px; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.4); }}
    .brand h1 {{ margin: 0; font-size: 20px; }}
    .brand p {{ margin: 4px 0 0; color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: 1.05fr 1.2fr; gap: 22px; }}
    .stack {{ display: flex; flex-direction: column; gap: 22px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow); padding: 22px; }}
    .card h2 {{ margin: 0 0 10px; font-size: 19px; }}
    .muted {{ color: var(--muted); font-size: 14px; }}
    textarea, input[type="text"], input[type="password"] {{
      width: 100%; border: 1px solid #cbd5e1; border-radius: 14px; padding: 14px 16px;
      font: inherit; color: var(--text); background: #fff;
    }}
    textarea {{ min-height: 160px; resize: vertical; }}
    .row {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
    button, .button-like {{
      border: 0; border-radius: 12px; padding: 11px 16px; font: inherit; cursor: pointer;
      background: var(--accent); color: #fff; font-weight: 600;
    }}
    button.secondary, .button-like.secondary {{ background: #e2e8f0; color: #0f172a; }}
    button.danger {{ background: var(--danger); }}
    button:disabled {{ opacity: 0.6; cursor: wait; }}
    .list {{ display: flex; flex-direction: column; gap: 12px; }}
    .item {{ border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; background: #f8fbff; }}
    .item-top {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; }}
    .item-title {{ font-weight: 700; word-break: break-word; }}
    .item-meta {{ margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.5; word-break: break-word; }}
    .item-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .empty {{ color: var(--muted); padding: 10px 0; }}
    .notice {{ margin-top: 12px; font-size: 14px; color: var(--muted); }}
    .status-pill {{
      display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 8px 12px;
      background: var(--accent-soft); color: #1d4ed8; font-size: 13px; font-weight: 700;
    }}
    .upload-drop {{
      border: 1.5px dashed #93c5fd; border-radius: 18px; padding: 18px; background: #f8fbff;
    }}
    .upload-drop input[type="file"] {{ width: 100%; }}
    .progress-bar {{ width: 100%; height: 10px; border-radius: 999px; background: #dbeafe; overflow: hidden; margin-top: 10px; }}
    .progress-fill {{ height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #60a5fa); }}
    .file-meta {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 14px; margin-top: 8px; font-size: 13px; color: var(--muted); }}
    .login-card {{ max-width: 460px; margin: 64px auto 0; }}
    .error {{ color: var(--danger); font-size: 14px; margin: 10px 0 0; }}
    .success {{ color: var(--success); }}
    code {{ background: #eff6ff; border-radius: 8px; padding: 2px 6px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .topbar {{ flex-direction: column; align-items: start; }} .file-meta {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="shell">{body}</div>
</body>
</html>
"""


def render_home_page() -> str:
    body = f"""
<div class="topbar">
  <div class="brand">
    <img class="brand-icon" src="{FAVICON_DATA_URI}" alt="favicon" />
    <div>
      <h1>File Upload Server</h1>
      <p>Token API stays separate. Web workspace is login-protected and user-isolated.</p>
    </div>
  </div>
  <a class="button-like" href="/login">Login</a>
</div>
<div class="card">
  <h2>Running</h2>
  <p class="muted">API endpoints under <code>/api/*</code> are unchanged. Web features live under the authenticated workspace.</p>
</div>
"""
    return render_page("File Upload Server", body)


def render_login_page(next_url: str, error: str = "") -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""
<div class="card login-card">
  <div class="brand" style="margin-bottom:18px;">
    <img class="brand-icon" src="{FAVICON_DATA_URI}" alt="favicon" />
    <div>
      <h1>Login</h1>
      <p>Each user gets their own clipboard and upload area.</p>
    </div>
  </div>
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{html.escape(next_url)}" />
    <div class="stack" style="gap:12px;">
      <div>
        <div class="muted" style="margin-bottom:8px;">Username</div>
        <input type="text" name="username" autocomplete="username" required />
      </div>
      <div>
        <div class="muted" style="margin-bottom:8px;">Password</div>
        <input type="password" name="password" autocomplete="current-password" required />
      </div>
      <button type="submit">Login</button>
    </div>
    {error_html}
  </form>
</div>
"""
    return render_page("Login", body)


def render_app_page(username: str) -> str:
    user = SETTINGS["users"][username]
    username_js = json.dumps(username)
    display_name = html.escape(user.get("display_name") or username)
    retention_days = SETTINGS["web_file_retention_days"]
    parallelism = SETTINGS["web_upload_parallelism"]
    body = f"""
<div class="topbar">
  <div class="brand">
    <img class="brand-icon" src="{FAVICON_DATA_URI}" alt="favicon" />
    <div>
      <h1>{display_name}</h1>
      <p>Private clipboard + private files. Web uploads auto-expire after {retention_days} days.</p>
    </div>
  </div>
  <div class="row">
    <span class="status-pill">Logged in as {html.escape(username)}</span>
    <a class="button-like secondary" href="/logout">Logout</a>
  </div>
</div>
<div class="grid">
  <div class="stack">
    <section class="card">
      <h2>Clipboard</h2>
      <p class="muted">Saved per user. Same text will be de-duplicated and bumped to the top.</p>
      <textarea id="clipboard-input" placeholder="Paste or type text here..."></textarea>
      <div class="row" style="margin-top:12px;">
        <button id="save-clipboard-btn" type="button">Save text</button>
        <span class="notice" id="clipboard-status"></span>
      </div>
    </section>
    <section class="card">
      <h2>Saved texts</h2>
      <div id="clipboard-list" class="list"></div>
    </section>
  </div>
  <div class="stack">
    <section class="card">
      <h2>File upload</h2>
      <p class="muted">Chunked + parallel + resumable. Files live in your own upload directory and do not mix with token API uploads.</p>
      <div class="upload-drop">
        <input id="file-input" type="file" multiple />
        <div class="notice">Chunk size is chosen automatically based on file size. Current browser parallelism: {parallelism}.</div>
      </div>
      <div id="upload-jobs" class="list" style="margin-top:14px;"></div>
    </section>
    <section class="card">
      <h2>Your files</h2>
      <p class="muted">File list refresh triggers cleanup of expired files. Downloads are served as complete files with HTTP range support.</p>
      <div class="row" style="margin-bottom:12px;">
        <button id="refresh-files-btn" type="button" class="secondary">Refresh files</button>
        <span class="notice" id="files-status"></span>
      </div>
      <div id="files-list" class="list"></div>
    </section>
  </div>
</div>
<script>
const CURRENT_USER = {username_js};
const UPLOAD_PARALLELISM = {parallelism};

function escapeHtml(value) {{
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}}

function formatBytes(value) {{
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = Number(value || 0);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {{
    size /= 1024;
    index += 1;
  }}
  if (index === 0) return Math.round(size) + ' ' + units[index];
  return size.toFixed(1) + ' ' + units[index];
}}

function formatDate(value) {{
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}}

async function fetchJson(url, options) {{
  const response = await fetch(url, options || {{}});
  const text = await response.text();
  let data = null;
  try {{ data = text ? JSON.parse(text) : null; }} catch (_err) {{ data = null; }}
  if (!response.ok) {{
    const detail = data && data.detail ? data.detail : text || response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }}
  return data;
}}

async function refreshClipboard() {{
  const list = document.getElementById('clipboard-list');
  list.innerHTML = '<div class="empty">Loading…</div>';
  const items = await fetchJson('/web/api/clipboard/items');
  if (!items.length) {{
    list.innerHTML = '<div class="empty">No saved text yet.</div>';
    return;
  }}
  list.innerHTML = items.map((item) => {{
    return '<div class="item">'
      + '<div class="item-top">'
      + '<div class="item-title">' + escapeHtml((item.text || '').slice(0, 120) || '(empty)') + '</div>'
      + '<div class="item-actions">'
      + '<button type="button" class="secondary" onclick="copyClipboardItem(' + JSON.stringify(item.id) + ')">Copy</button>'
      + '<button type="button" class="danger" onclick="deleteClipboardItem(' + JSON.stringify(item.id) + ')">Delete</button>'
      + '</div></div>'
      + '<div class="item-meta">' + escapeHtml(item.text || '').replace(/\n/g, '<br>') + '</div>'
      + '<div class="item-meta">Updated: ' + escapeHtml(formatDate(item.updated_at)) + '</div>'
      + '</div>';
  }}).join('');
}}

async function saveClipboard() {{
  const button = document.getElementById('save-clipboard-btn');
  const status = document.getElementById('clipboard-status');
  const text = document.getElementById('clipboard-input').value;
  button.disabled = true;
  status.textContent = 'Saving…';
  try {{
    await fetchJson('/web/api/clipboard/items', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ text }}),
    }});
    status.textContent = 'Saved.';
    document.getElementById('clipboard-input').value = '';
    await refreshClipboard();
  }} catch (err) {{
    status.textContent = 'Save failed: ' + err.message;
  }} finally {{
    button.disabled = false;
  }}
}}

async function copyClipboardItem(id) {{
  const items = await fetchJson('/web/api/clipboard/items');
  const item = items.find((entry) => entry.id === id);
  if (!item) return;
  await navigator.clipboard.writeText(item.text || '');
}}

async function deleteClipboardItem(id) {{
  await fetchJson('/web/api/clipboard/items/' + encodeURIComponent(id), {{ method: 'DELETE' }});
  await refreshClipboard();
}}

function createUploadJobCard(file) {{
  const job = document.createElement('div');
  job.className = 'item';
  job.innerHTML = ''
    + '<div class="item-title">' + escapeHtml(file.name) + '</div>'
    + '<div class="file-meta">'
    + '<div>Size: ' + escapeHtml(formatBytes(file.size)) + '</div>'
    + '<div>Status: <span class="job-status">Preparing…</span></div>'
    + '<div>Uploaded: <span class="job-uploaded">0%</span></div>'
    + '<div>Chunking: <span class="job-chunking">—</span></div>'
    + '</div>'
    + '<div class="progress-bar"><div class="progress-fill"></div></div>';
  document.getElementById('upload-jobs').prepend(job);
  return job;
}}

function updateJobProgress(job, percent, statusText, chunkingText) {{
  job.querySelector('.progress-fill').style.width = String(Math.max(0, Math.min(100, percent))) + '%';
  job.querySelector('.job-uploaded').textContent = percent.toFixed(1) + '%';
  if (statusText) job.querySelector('.job-status').textContent = statusText;
  if (chunkingText) job.querySelector('.job-chunking').textContent = chunkingText;
}}

async function initUpload(file) {{
  return fetchJson('/web/api/uploads/init', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{
      filename: file.name,
      size: file.size,
      content_type: file.type || 'application/octet-stream',
      last_modified_ms: file.lastModified || 0,
    }}),
  }});
}}

async function uploadChunk(uploadId, chunkIndex, blob) {{
  const response = await fetch('/web/api/uploads/' + encodeURIComponent(uploadId) + '/chunks/' + chunkIndex, {{
    method: 'PUT',
    headers: {{ 'Content-Type': 'application/octet-stream' }},
    body: blob,
  }});
  if (!response.ok) {{
    const text = await response.text();
    throw new Error(text || ('Chunk upload failed (' + response.status + ')'));
  }}
  return response.json();
}}

async function completeUpload(uploadId) {{
  return fetchJson('/web/api/uploads/' + encodeURIComponent(uploadId) + '/complete', {{ method: 'POST' }});
}}

async function processFile(file) {{
  const job = createUploadJobCard(file);
  try {{
    const init = await initUpload(file);
    const uploadId = init.upload_id;
    const chunkSize = init.chunk_size;
    const totalChunks = init.total_chunks;
    const received = new Set((init.received_chunks || []).map((value) => Number(value)));
    let uploadedBytes = Number(init.received_bytes || 0);
    updateJobProgress(job, file.size ? uploadedBytes / file.size * 100 : 100, 'Uploading…', formatBytes(chunkSize) + ' × ' + totalChunks);

    const pending = [];
    for (let index = 1; index <= totalChunks; index += 1) {{
      if (!received.has(index)) pending.push(index);
    }}

    let cursor = 0;
    async function worker() {{
      while (cursor < pending.length) {{
        const current = pending[cursor];
        cursor += 1;
        const start = (current - 1) * chunkSize;
        const end = Math.min(file.size, start + chunkSize);
        const blob = file.slice(start, end);
        const result = await uploadChunk(uploadId, current, blob);
        uploadedBytes = Number(result.received_bytes || uploadedBytes + blob.size);
        const percent = file.size ? uploadedBytes / file.size * 100 : 100;
        updateJobProgress(job, percent, 'Uploading…', result.received_count + ' / ' + totalChunks + ' chunks');
      }}
    }}

    const workers = [];
    const workerCount = Math.max(1, Math.min(UPLOAD_PARALLELISM, pending.length || 1));
    for (let i = 0; i < workerCount; i += 1) workers.push(worker());
    await Promise.all(workers);

    const finalInfo = await completeUpload(uploadId);
    updateJobProgress(job, 100, 'Completed', 'Ready');
    const meta = job.querySelector('.file-meta');
    meta.innerHTML += '<div class="success">Expires: ' + escapeHtml(formatDate(finalInfo.expires_at)) + '</div>';
    await refreshFiles();
  }} catch (err) {{
    updateJobProgress(job, 0, 'Failed', err.message || 'Upload failed');
    throw err;
  }}
}}

async function handleFileSelection(event) {{
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  for (const file of files) {{
    try {{
      await processFile(file);
    }} catch (_err) {{
      // Status already rendered on the upload card.
    }}
  }}
  event.target.value = '';
}}

async function refreshFiles() {{
  const status = document.getElementById('files-status');
  const list = document.getElementById('files-list');
  status.textContent = 'Refreshing…';
  list.innerHTML = '<div class="empty">Loading…</div>';
  try {{
    const files = await fetchJson('/web/api/files');
    status.textContent = files.length ? ('Loaded ' + files.length + ' file(s).') : 'No files.';
    if (!files.length) {{
      list.innerHTML = '<div class="empty">No files available.</div>';
      return;
    }}
    list.innerHTML = files.map((item) => {{
      const downloadUrl = '/web/api/files/' + encodeURIComponent(item.file_id) + '/download';
      return '<div class="item">'
        + '<div class="item-top">'
        + '<div><div class="item-title">' + escapeHtml(item.original_name) + '</div>'
        + '<div class="item-meta">Uploaded: ' + escapeHtml(formatDate(item.created_at)) + '</div></div>'
        + '<div class="item-actions"><a class="button-like secondary" href="' + downloadUrl + '">Download</a></div>'
        + '</div>'
        + '<div class="file-meta">'
        + '<div>Size: ' + escapeHtml(formatBytes(item.size)) + '</div>'
        + '<div>Type: ' + escapeHtml(item.content_type || 'application/octet-stream') + '</div>'
        + '<div>Delete on: ' + escapeHtml(formatDate(item.expires_at)) + '</div>'
        + '<div>File ID: ' + escapeHtml(item.file_id) + '</div>'
        + '</div>'
        + '</div>';
    }}).join('');
  }} catch (err) {{
    status.textContent = 'Refresh failed: ' + err.message;
    list.innerHTML = '<div class="empty">Failed to load files.</div>';
  }}
}}

window.addEventListener('DOMContentLoaded', async () => {{
  document.getElementById('save-clipboard-btn').addEventListener('click', saveClipboard);
  document.getElementById('file-input').addEventListener('change', handleFileSelection);
  document.getElementById('refresh-files-btn').addEventListener('click', refreshFiles);
  try {{ await refreshClipboard(); }} catch (err) {{ document.getElementById('clipboard-list').innerHTML = '<div class="empty">Failed to load saved texts.</div>'; }}
  await refreshFiles();
}});
</script>
"""
    return render_page("Workspace", body)


# ─── Routes: page + auth ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root_page():
    return render_home_page()


@app.get("/login", response_class=HTMLResponse)
async def login_page(next: Optional[str] = None):
    return render_login_page(sanitize_next_url(next))


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
):
    desired_next = sanitize_next_url(next)
    user = SETTINGS["users"].get(username.strip())
    if not user or not verify_password(password, user["password_hash"]):
        return HTMLResponse(render_login_page(desired_next, "Invalid username or password."), status_code=401)

    response = RedirectResponse(url=desired_next, status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user["username"]),
        max_age=SETTINGS["session_max_age_seconds"],
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@app.get("/logout")
async def logout_page():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/home")
async def home_redirect():
    return RedirectResponse(url="/app", status_code=303)


@app.get("/app", response_class=HTMLResponse)
async def app_page(request: Request):
    username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return render_app_page(username)


@app.get("/clipboard")
async def clipboard_page_redirect():
    return RedirectResponse(url="/app", status_code=303)


@app.get("/upload")
async def upload_page_redirect():
    return RedirectResponse(url="/app", status_code=303)


@app.get("/chunked-upload")
async def chunked_upload_page_redirect():
    return RedirectResponse(url="/app", status_code=303)


@app.get("/status")
async def global_status(request: Request):
    username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return JSONResponse({
        "port": PORT,
        "config_path": str(CONFIG_PATH),
        "data_dir": str(DATA_DIR),
        "web_root": str(WEB_ROOT_DIR),
        "current_user": username,
        "tracked_api_uploads": len(upload_tracker),
        "completed_api_uploads": len(completed_uploads),
        "auth_configured": auth_configured(),
        "web_file_retention_days": SETTINGS["web_file_retention_days"],
    })


@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    _username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Docs")


@app.get("/openapi.json")
async def openapi_json(request: Request):
    _username, redirect = require_page_login(request)
    if redirect:
        return redirect
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes, description=app.description)
    return JSONResponse(schema)


@app.get("/docs/oauth2-redirect", response_class=HTMLResponse)
async def swagger_oauth2_redirect(request: Request):
    _username, redirect = require_page_login(request)
    if redirect:
        return redirect
    return get_swagger_ui_oauth2_redirect_html()


# ─── Routes: web clipboard ───────────────────────────────────────────────────

@app.get("/web/api/clipboard/items")
async def clipboard_items(request: Request):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        items = sorted(load_clipboard_items(username), key=lambda x: x.get("updated_at") or "", reverse=True)
    return JSONResponse(items)


@app.post("/web/api/clipboard/items")
async def clipboard_add(request: Request, payload: ClipboardPayload):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        item = upsert_clipboard_item(username, payload.text)
    return JSONResponse(item)


@app.delete("/web/api/clipboard/items/{item_id}")
async def clipboard_remove(request: Request, item_id: str):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        ok = delete_clipboard_item(username, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Clipboard item not found")
    return JSONResponse({"ok": True, "deleted": True})


# ─── Routes: web uploads/files ───────────────────────────────────────────────

@app.post("/web/api/uploads/init")
async def web_upload_init(request: Request, payload: WebUploadInitPayload):
    username = require_json_login(request)
    filename = extract_filename(payload.filename)
    size = int(payload.size)
    if size < 0:
        raise HTTPException(status_code=400, detail="Invalid file size")

    fingerprint = compute_upload_fingerprint(filename, size, payload.last_modified_ms)
    async with get_user_state_lock(username):
        cleanup_stale_upload_sessions(username)
        existing = find_active_upload_by_fingerprint(username, fingerprint)
        if existing:
            return JSONResponse({
                "upload_id": existing["upload_id"],
                "file_id": existing["file_id"],
                "filename": existing["filename"],
                "size": existing["size"],
                "chunk_size": existing["chunk_size"],
                "total_chunks": existing["total_chunks"],
                "received_chunks": existing.get("received_chunks") or [],
                "received_bytes": existing.get("received_bytes") or 0,
                "resumed": True,
            })

        upload_id = uuid.uuid4().hex
        chunk_size = determine_chunk_size(max(1, size))
        total_chunks = max(1, math.ceil(size / chunk_size)) if size else 1
        meta = {
            "upload_id": upload_id,
            "file_id": upload_id,
            "username": username,
            "filename": filename,
            "size": size,
            "content_type": payload.content_type or "application/octet-stream",
            "last_modified_ms": payload.last_modified_ms or 0,
            "fingerprint": fingerprint,
            "chunk_size": chunk_size,
            "total_chunks": total_chunks,
            "received_chunks": [],
            "part_sizes": {},
            "received_bytes": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "completed": False,
        }
        upload_dir(username, upload_id).mkdir(parents=True, exist_ok=True)
        (upload_dir(username, upload_id) / "chunks").mkdir(parents=True, exist_ok=True)
        save_upload_meta(username, upload_id, meta)

    return JSONResponse({
        "upload_id": upload_id,
        "file_id": upload_id,
        "filename": filename,
        "size": size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "received_chunks": [],
        "received_bytes": 0,
        "resumed": False,
    })


@app.put("/web/api/uploads/{upload_id}/chunks/{chunk_index}")
async def web_upload_chunk(request: Request, upload_id: str, chunk_index: int, body: bytes = Body(...)):
    username = require_json_login(request)
    upload_id = normalize_file_id(upload_id)
    lock = get_web_upload_lock(upload_id)
    async with lock:
        meta = load_upload_meta(username, upload_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Upload session not found")
        total_chunks = int(meta["total_chunks"])
        if chunk_index < 1 or chunk_index > total_chunks:
            raise HTTPException(status_code=400, detail="Invalid chunk index")

        part_path = upload_chunk_path(username, upload_id, chunk_index)
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(body)

        received_chunks = {int(x) for x in (meta.get("received_chunks") or [])}
        part_sizes = {str(k): int(v) for k, v in (meta.get("part_sizes") or {}).items()}
        part_sizes[str(chunk_index)] = len(body)
        received_chunks.add(chunk_index)

        meta["part_sizes"] = part_sizes
        meta["received_chunks"] = sorted(received_chunks)
        meta["received_bytes"] = sum(part_sizes.values())
        meta["updated_at"] = now_iso()
        save_upload_meta(username, upload_id, meta)

    return JSONResponse({
        "ok": True,
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "received_count": len(meta["received_chunks"]),
        "received_chunks": meta["received_chunks"],
        "received_bytes": meta["received_bytes"],
    })


@app.get("/web/api/uploads/{upload_id}")
async def web_upload_status(request: Request, upload_id: str):
    username = require_json_login(request)
    upload_id = normalize_file_id(upload_id)
    meta = load_upload_meta(username, upload_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Upload session not found")

    total_chunks = int(meta["total_chunks"])
    received_chunks = sorted(int(x) for x in (meta.get("received_chunks") or []))
    missing = sorted(set(range(1, total_chunks + 1)) - set(received_chunks))
    return JSONResponse({
        "upload_id": upload_id,
        "filename": meta["filename"],
        "size": meta["size"],
        "chunk_size": meta["chunk_size"],
        "total_chunks": total_chunks,
        "received_chunks": received_chunks,
        "received_count": len(received_chunks),
        "received_bytes": meta.get("received_bytes") or 0,
        "missing_chunks": missing,
    })


@app.post("/web/api/uploads/{upload_id}/complete")
async def web_upload_complete(request: Request, upload_id: str):
    username = require_json_login(request)
    upload_id = normalize_file_id(upload_id)
    lock = get_web_upload_lock(upload_id)
    async with lock:
        meta = load_upload_meta(username, upload_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Upload session not found")
        async with get_user_state_lock(username):
            file_item = assemble_web_upload(username, upload_id, meta)
    return JSONResponse(file_item)


@app.get("/web/api/files")
async def web_files_list(request: Request):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        cleanup_expired_user_files(username)
        cleanup_stale_upload_sessions(username)
        items = sorted(load_user_files(username), key=lambda x: x.get("created_at") or "", reverse=True)
    return JSONResponse(items)


@app.get("/web/api/files/{file_id}/download")
async def web_file_download(request: Request, file_id: str):
    username = require_json_login(request)
    file_id = normalize_file_id(file_id)
    async with get_user_state_lock(username):
        cleanup_expired_user_files(username)
        item = get_user_file_item(username, file_id)
    if not item:
        raise HTTPException(status_code=404, detail="File not found")

    path = user_files_dir(username) / item["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    file_size = path.stat().st_size
    content_type = item.get("content_type") or mimetypes.guess_type(item.get("original_name") or "")[0] or "application/octet-stream"
    filename = extract_filename(item.get("original_name") or path.name)
    filename_q = quote(filename)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename_q}",
    }
    if file_size == 0:
        headers["Content-Length"] = "0"
        return Response(content=b"", media_type=content_type, headers=headers)

    try:
        byte_range = parse_range_header(request.headers.get("range"), file_size)
    except RangeNotSatisfiable:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    if byte_range is None:
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(iter_file_range(path, 0, file_size - 1), media_type=content_type, headers=headers)

    start, end = byte_range
    headers["Content-Length"] = str(end - start + 1)
    headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return StreamingResponse(
        iter_file_range(path, start, end),
        status_code=206,
        media_type=content_type,
        headers=headers,
    )


# ─── Stable API (unchanged paths/shape) ──────────────────────────────────────

@app.post("/api/upload")
async def upload_single(
    file: UploadFile = File(...),
    _token: str = Security(require_token),
):
    original_name = extract_filename(file.filename or "unnamed")
    dest = build_unique_path(original_name)

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    size = dest.stat().st_size
    return JSONResponse({
        "ok": True,
        "name": original_name,
        "saved": dest.name,
        "size": size,
        "path": str(dest),
    })


@app.post("/api/chunked")
async def upload_chunk(
    file: UploadFile = File(...),
    x_chunk_index: int = Header(..., alias="X-Chunk-Index"),
    x_chunk_total: int = Header(..., alias="X-Chunk-Total"),
    x_file_name: str = Header(..., alias="X-File-Name"),
    x_file_id: Optional[str] = Header(None, alias="X-File-Id"),
    _token: str = Security(require_token),
):
    if x_chunk_total < 1 or x_chunk_index < 1 or x_chunk_index > x_chunk_total:
        raise HTTPException(status_code=400, detail="Invalid chunk index or total")

    filename = extract_filename(x_file_name)
    file_id = normalize_file_id(x_file_id)
    key = get_upload_key(file_id, filename)

    if key not in upload_tracker:
        upload_tracker[key] = {
            "file_id": file_id,
            "filename": filename,
            "total": x_chunk_total,
            "received": set(),
            "chunk_sizes": {},
            "size": 0,
        }

    meta = upload_tracker[key]
    if meta["total"] != x_chunk_total:
        raise HTTPException(status_code=400, detail="Chunk total mismatch with existing upload session")

    part_file = chunk_part_path(file_id, filename, x_chunk_index)
    with open(part_file, "wb") as f:
        shutil.copyfileobj(file.file, f)

    chunk_size = part_file.stat().st_size
    prev_size = meta["chunk_sizes"].get(x_chunk_index, 0)
    meta["chunk_sizes"][x_chunk_index] = chunk_size
    meta["received"].add(x_chunk_index)
    meta["size"] = meta["size"] - prev_size + chunk_size

    if meta["received"] == set(range(1, x_chunk_total + 1)):
        final_path = assemble_chunks(file_id, filename, x_chunk_total, meta["received"])
        if final_path is not None:
            completed_uploads[key] = {
                "assembled": True,
                "saved": final_path.name,
                "path": str(final_path),
                "size": meta["size"],
            }
            response = {
                "ok": True,
                "assembled": True,
                "name": filename,
                "saved": final_path.name,
                "path": str(final_path),
                "size": meta["size"],
            }
            del upload_tracker[key]
            return JSONResponse(response)

    return JSONResponse({
        "ok": True,
        "assembled": False,
        "file_id": file_id,
        "filename": filename,
        "chunk_index": x_chunk_index,
        "chunk_total": x_chunk_total,
        "received_chunks": sorted(meta["received"]),
        "progress": f"{len(meta['received'])}/{x_chunk_total}",
    })


@app.get("/api/status/{file_id}/{filename}")
async def check_status(
    file_id: str,
    filename: str,
    _token: str = Security(require_token),
):
    normalized_file_id = normalize_file_id(file_id)
    normalized_filename = extract_filename(filename)
    key = get_upload_key(normalized_file_id, normalized_filename)

    if key in completed_uploads:
        return JSONResponse({"ok": True, **completed_uploads[key], "filename": normalized_filename})

    if key not in upload_tracker:
        raise HTTPException(status_code=404, detail="Upload session not found")

    meta = upload_tracker[key]
    total = meta["total"]
    missing = sorted(set(range(1, total + 1)) - meta["received"])
    return JSONResponse({
        "ok": True,
        "assembled": False,
        "filename": normalized_filename,
        "total": total,
        "received": len(meta["received"]),
        "received_chunks": sorted(meta["received"]),
        "progress": f"{len(meta['received'])}/{total}",
        "missing": missing,
    })


@app.delete("/api/status/{file_id}/{filename}")
async def cancel_upload(
    file_id: str,
    filename: str,
    _token: str = Security(require_token),
):
    normalized_file_id = normalize_file_id(file_id)
    normalized_filename = extract_filename(filename)
    key = get_upload_key(normalized_file_id, normalized_filename)
    if key in upload_tracker:
        del upload_tracker[key]
    cleanup_chunks(normalized_file_id, normalized_filename)
    return JSONResponse({"ok": True, "cancelled": True})


# ─── Entry ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Port           : {PORT}")
    print(f"Config         : {CONFIG_PATH}")
    print(f"Data dir       : {DATA_DIR}")
    print(f"API chunk dir  : {API_CHUNKS_DIR}")
    print(f"Web root dir   : {WEB_ROOT_DIR}")
    print(f"Docs           : http://localhost:{PORT}/docs")
    print(f"Token header   : {TOKEN_HEADER_NAME}")
    print(f"API auth       : {'enabled' if UPLOAD_TOKEN else 'disabled'}")
    print(f"Web users      : {', '.join(sorted(SETTINGS['users'].keys()))}")
    print(f"File retention : {SETTINGS['web_file_retention_days']} day(s)")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
