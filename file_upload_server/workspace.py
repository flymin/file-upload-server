import hashlib
import json
import math
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

from .config import SETTINGS, WEB_USERS_DIR
from .state import web_upload_locks
from .utils import extract_filename, normalize_file_id, now_iso, now_utc, parse_iso, safe_temp_component




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


def delete_user_file(username: str, file_id: str) -> bool:
    file_id = (file_id or "").strip()
    if not file_id:
        return False

    items = load_user_files(username)
    target: Optional[dict] = None
    kept: List[dict] = []
    for item in items:
        if item.get("file_id") == file_id and target is None:
            target = item
        else:
            kept.append(item)

    if not target:
        return False

    file_path = user_files_dir(username) / str(target.get("stored_name") or "")
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass

    save_user_files(username, kept)
    return True


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

