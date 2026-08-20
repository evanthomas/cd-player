import pytest

from cd_player.ui.rotation import canvas_size_for_physical, physical_to_canvas

# Real panel: physically portrait 720x1280; UI renders landscape 1280x720.
PHYSICAL = (720, 1280)
CANVAS = (1280, 720)


@pytest.mark.parametrize("rotate_deg", [0, 90, 180, 270])
def test_canvas_size_round_trip_covers_whole_physical_panel(rotate_deg):
    canvas_size = canvas_size_for_physical(PHYSICAL, rotate_deg)
    # Every corner of the physical panel must map inside the canvas.
    pw, ph = PHYSICAL
    corners = [(0, 0), (pw - 1, 0), (0, ph - 1), (pw - 1, ph - 1)]
    cw, ch = canvas_size
    for corner in corners:
        cx, cy = physical_to_canvas(corner, canvas_size, rotate_deg)
        assert 0 <= cx < cw
        assert 0 <= cy < ch


def test_landscape_canvas_for_portrait_physical():
    assert canvas_size_for_physical(PHYSICAL, 90) == (1280, 720)
    assert canvas_size_for_physical(PHYSICAL, 270) == (1280, 720)


def test_no_rotation_is_identity():
    assert physical_to_canvas((100, 200), (720, 1280), 0) == (100, 200)


def test_rotate_90_maps_physical_corners_to_expected_canvas_corners():
    # rotate_deg=90 corresponds to pygame.transform.rotate(canvas, 90)
    # (counterclockwise) being blitted onto the physical surface.
    canvas_size = canvas_size_for_physical(PHYSICAL, 90)
    assert physical_to_canvas((0, 0), canvas_size, 90) == (1279, 0)
    assert physical_to_canvas((719, 0), canvas_size, 90) == (1279, 719)
    assert physical_to_canvas((0, 1279), canvas_size, 90) == (0, 0)


def test_rotate_270_maps_physical_corners_to_expected_canvas_corners():
    canvas_size = canvas_size_for_physical(PHYSICAL, 270)
    assert physical_to_canvas((0, 0), canvas_size, 270) == (0, 719)
    assert physical_to_canvas((719, 0), canvas_size, 270) == (0, 0)
    assert physical_to_canvas((0, 1279), canvas_size, 270) == (1279, 719)


def test_unsupported_rotation_raises():
    with pytest.raises(ValueError):
        physical_to_canvas((0, 0), (100, 100), 45)
