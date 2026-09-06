"""Frameless window position. Logical pixels for pywebview.move."""

from __future__ import annotations


def center_in_rect(
    width: int, height: int, left: int, top: int, right: int, bottom: int
) -> tuple[int, int]:
    span_x = right - left
    span_y = bottom - top
    x = left if span_x < width else left + (span_x - width) // 2
    y = top if span_y < height else top + (span_y - height) // 2
    return x, y


def pick_screen(screens, cursor: tuple[int, int] | None = None):
    if not screens:
        return None
    if cursor is None:
        return screens[0]
    cx, cy = cursor
    for scr in screens:
        left, top = scr.physical_x, scr.physical_y
        if left <= cx < left + scr.physical_width and top <= cy < top + scr.physical_height:
            return scr
    return screens[0]


def xy_for_screen(scr, width: int, height: int) -> tuple[int, int]:
    frame = getattr(scr, "frame", None)
    if frame is not None and hasattr(frame, "X") and hasattr(frame, "Width"):
        left, top = int(frame.X), int(frame.Y)
        return center_in_rect(
            width, height, left, top, left + int(frame.Width), top + int(frame.Height)
        )
    return center_in_rect(width, height, scr.x, scr.y, scr.x + scr.width, scr.y + scr.height)
