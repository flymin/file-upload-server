import json
import struct
import zlib
from functools import lru_cache
from typing import Iterable, Tuple


APP_NAME = "File Upload"
THEME_COLOR = "#2563eb"
BACKGROUND_COLOR = "#f4f7fb"

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#60a5fa"/>
      <stop offset="100%" stop-color="#6366f1"/>
    </linearGradient>
  </defs>
  <rect x="10" y="6" width="44" height="52" rx="10" fill="url(#g)"/>
  <rect x="22" y="2" width="20" height="10" rx="5" fill="#1e293b" opacity="0.9"/>
  <rect x="18" y="18" width="28" height="4" rx="2" fill="white" opacity="0.95"/>
  <rect x="18" y="28" width="20" height="4" rx="2" fill="white" opacity="0.95"/>
  <rect x="18" y="38" width="24" height="4" rx="2" fill="white" opacity="0.95"/>
</svg>"""


def manifest_json() -> str:
    return json.dumps(
        {
            "name": APP_NAME,
            "short_name": APP_NAME,
            "start_url": "/app",
            "scope": "/",
            "display": "standalone",
            "background_color": BACKGROUND_COLOR,
            "theme_color": THEME_COLOR,
            "icons": [
                {
                    "src": "/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": "/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        },
        separators=(",", ":"),
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _encode_png_rgba(width: int, height: int, pixels: Iterable[Tuple[int, int, int, int]]) -> bytes:
    raw_rows = []
    iterator = iter(pixels)
    for _y in range(height):
        row = bytearray([0])
        for _x in range(width):
            row.extend(next(iterator))
        raw_rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows), 9)) + _png_chunk(b"IEND", b"")


def _hex_color(value: str) -> Tuple[int, int, int]:
    cleaned = value.lstrip("#")
    return int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16)


def _blend(top: Tuple[int, int, int, int], bottom: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    alpha = top[3] / 255
    inverse = 1 - alpha
    return (
        round(top[0] * alpha + bottom[0] * inverse),
        round(top[1] * alpha + bottom[1] * inverse),
        round(top[2] * alpha + bottom[2] * inverse),
        255,
    )


def _inside_round_rect(x: int, y: int, left: int, top: int, right: int, bottom: int, radius: int) -> bool:
    if left + radius <= x < right - radius or top + radius <= y < bottom - radius:
        return left <= x < right and top <= y < bottom
    cx = left + radius if x < left + radius else right - radius - 1
    cy = top + radius if y < top + radius else bottom - radius - 1
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _icon_png(size: int) -> bytes:
    bg = (*_hex_color(BACKGROUND_COLOR), 255)
    blue = _hex_color("#60a5fa")
    indigo = _hex_color("#6366f1")
    slate = (*_hex_color("#1e293b"), 242)
    white = (255, 255, 255, 242)

    pixels = []
    card_left = round(size * 0.18)
    card_top = round(size * 0.12)
    card_right = round(size * 0.82)
    card_bottom = round(size * 0.88)
    card_radius = round(size * 0.15)
    clip_left = round(size * 0.34)
    clip_top = round(size * 0.06)
    clip_right = round(size * 0.66)
    clip_bottom = round(size * 0.19)
    clip_radius = round(size * 0.07)

    line_specs = (
        (0.28, 0.34, 0.72, 0.40),
        (0.28, 0.49, 0.61, 0.55),
        (0.28, 0.64, 0.67, 0.70),
    )

    for y in range(size):
        for x in range(size):
            color = bg
            if _inside_round_rect(x, y, card_left, card_top, card_right, card_bottom, card_radius):
                t = (x + y) / max(1, (size - 1) * 2)
                color = (
                    round(blue[0] * (1 - t) + indigo[0] * t),
                    round(blue[1] * (1 - t) + indigo[1] * t),
                    round(blue[2] * (1 - t) + indigo[2] * t),
                    255,
                )
            if _inside_round_rect(x, y, clip_left, clip_top, clip_right, clip_bottom, clip_radius):
                color = _blend(slate, color)
            for left, top, right, bottom in line_specs:
                if _inside_round_rect(
                    x,
                    y,
                    round(size * left),
                    round(size * top),
                    round(size * right),
                    round(size * bottom),
                    round(size * 0.025),
                ):
                    color = _blend(white, color)
            pixels.append(color)

    return _encode_png_rgba(size, size, pixels)


@lru_cache(maxsize=3)
def get_png_icon(size: int) -> bytes:
    if size not in (180, 192, 512):
        raise ValueError(f"unsupported icon size: {size}")
    return _icon_png(size)
