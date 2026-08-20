"""Coordinate geometry for driving a landscape UI on a physically portrait
panel without X11/Wayland to do rotation for us.

The app renders onto a landscape `canvas` surface, then blits it onto the
real (portrait) display surface via `pygame.transform.rotate(canvas,
rotate_deg)` -- `rotate_deg` follows pygame's convention (positive =
counterclockwise). Touch/click events arrive in physical panel
coordinates and must be mapped back into canvas coordinates for button
hit-testing; `physical_to_canvas` is the exact inverse of that rotation.
"""

from __future__ import annotations

Point = tuple[int, int]
Size = tuple[int, int]


def canvas_size_for_physical(physical_size: Size, rotate_deg: int) -> Size:
    width, height = physical_size
    if rotate_deg in (90, 270):
        return (height, width)
    return (width, height)


def physical_to_canvas(point: Point, canvas_size: Size, rotate_deg: int) -> Point:
    px, py = point
    cw, ch = canvas_size
    if rotate_deg == 0:
        return (px, py)
    if rotate_deg == 90:
        return (cw - 1 - py, px)
    if rotate_deg == 180:
        return (cw - 1 - px, ch - 1 - py)
    if rotate_deg == 270:
        return (py, ch - 1 - px)
    raise ValueError(f"unsupported rotate_deg: {rotate_deg} (must be 0/90/180/270)")
