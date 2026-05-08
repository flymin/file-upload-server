import os
from pathlib import Path
from typing import Dict

import yaml


PORT = int((os.environ.get("PORT") or "8091").strip())
TOKEN_HEADER_NAME = "X-Upload-Token"
UPLOAD_TOKEN = (os.environ.get("UPLOAD_TOKEN") or "").strip()
SESSION_COOKIE_NAME = "file_upload_session"
PBKDF2_ALGORITHM = "pbkdf2_sha256"
LONG_SESSION_MAX_AGE_SECONDS = 10 * 365 * 24 * 60 * 60

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path((os.environ.get("CONFIG_PATH") or str(BASE_DIR / "config.yaml")).strip())
DATA_DIR = BASE_DIR / "data"
API_CHUNKS_DIR = DATA_DIR / ".chunks"
WEB_ROOT_DIR = DATA_DIR / "web"
WEB_USERS_DIR = WEB_ROOT_DIR / "users"

DATA_DIR.mkdir(exist_ok=True)
API_CHUNKS_DIR.mkdir(exist_ok=True)
WEB_USERS_DIR.mkdir(parents=True, exist_ok=True)


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

    session_max_age = int(app_cfg.get("session_max_age_seconds", 0) or 0)

    return {
        "session_secret": session_secret.encode("utf-8"),
        "session_max_age_seconds": session_max_age,
        "clipboard_history_limit": int(app_cfg.get("clipboard_history_limit") or 100),
        "clipboard_max_chars": int(app_cfg.get("clipboard_max_chars") or 200000),
        "web_file_retention_days": int(app_cfg.get("web_file_retention_days") or 7),
        "web_upload_parallelism": max(1, int(app_cfg.get("web_upload_parallelism") or 4)),
        "users": users,
    }


SETTINGS = load_config()
