import shutil
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, Security, UploadFile
from fastapi.responses import JSONResponse

from ..legacy_storage import assemble_chunks, build_unique_path, chunk_part_path, cleanup_chunks, get_upload_key
from ..security import require_token
from ..state import completed_uploads, upload_tracker
from ..utils import extract_filename, normalize_file_id

router = APIRouter()


@router.post("/api/upload")
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


@router.post("/api/chunked")
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


@router.get("/api/status/{file_id}/{filename}")
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


@router.delete("/api/status/{file_id}/{filename}")
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
