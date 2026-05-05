from pathlib import Path
from typing import Optional, Tuple

from .exceptions import RangeNotSatisfiable


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

