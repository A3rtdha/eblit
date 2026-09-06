"""App / tray glyph from the shipped PNG."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from .paths import icon_png


def make_icon(size: int = 64) -> Image.Image:
    img = Image.open(icon_png()).convert("RGBA")
    if img.size != (size, size):
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def icon_png_bytes(size: int = 64) -> bytes:
    buf = BytesIO()
    make_icon(size).save(buf, format="PNG")
    return buf.getvalue()
