import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request

from .config import PBKDF2_ALGORITHM, SESSION_COOKIE_NAME, SETTINGS




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
