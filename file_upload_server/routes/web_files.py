import math
import mimetypes
import uuid
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..config import SETTINGS
from ..exceptions import RangeNotSatisfiable
from ..file_streaming import iter_file_range, parse_range_header
from ..models import WebUploadInitPayload
from ..security import require_json_login
from ..state import get_user_state_lock, get_web_upload_lock
from ..utils import extract_filename, normalize_file_id, now_iso
from ..workspace import (
    assemble_web_upload,
    cleanup_expired_user_files,
    cleanup_stale_upload_sessions,
    compute_upload_fingerprint,
    delete_user_file,
    determine_chunk_size,
    find_active_upload_by_fingerprint,
    get_user_file_item,
    load_upload_meta,
    load_user_files,
    save_upload_meta,
    upload_chunk_path,
    upload_dir,
    user_files_dir,
)

router = APIRouter()


@router.post("/web/api/uploads/init")
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


@router.put("/web/api/uploads/{upload_id}/chunks/{chunk_index}")
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


@router.get("/web/api/uploads/{upload_id}")
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


@router.post("/web/api/uploads/{upload_id}/complete")
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


@router.get("/web/api/files")
async def web_files_list(request: Request):
    username = require_json_login(request)
    async with get_user_state_lock(username):
        cleanup_expired_user_files(username)
        cleanup_stale_upload_sessions(username)
        items = sorted(load_user_files(username), key=lambda x: x.get("created_at") or "", reverse=True)
    return JSONResponse(items)


@router.delete("/web/api/files/{file_id}")
async def web_file_delete(request: Request, file_id: str):
    username = require_json_login(request)
    file_id = normalize_file_id(file_id)
    async with get_user_state_lock(username):
        ok = delete_user_file(username, file_id)
    if not ok:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse({"ok": True, "deleted": True, "file_id": file_id})


@router.get("/web/api/files/{file_id}/download")
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
