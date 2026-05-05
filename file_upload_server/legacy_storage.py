import shutil
from pathlib import Path
from typing import Dict, Optional, Set

from .config import API_CHUNKS_DIR, DATA_DIR
from .state import upload_tracker
from .utils import extract_filename, normalize_file_id, safe_temp_component




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
