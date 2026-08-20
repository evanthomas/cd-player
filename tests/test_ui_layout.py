from cd_player.ui.layout import BUTTON_NAMES, button_at, compute_layout

CANVAS_SIZE = (1280, 720)


def test_all_five_buttons_present_left_to_right():
    layout = compute_layout(CANVAS_SIZE)

    assert set(layout.buttons.keys()) == set(BUTTON_NAMES)
    xs = [layout.buttons[name][0] for name in BUTTON_NAMES]
    assert xs == sorted(xs)


def test_buttons_do_not_overlap():
    layout = compute_layout(CANVAS_SIZE)

    rects = [layout.buttons[name] for name in BUTTON_NAMES]
    for i, (x1, _y1, w1, _h1) in enumerate(rects):
        for x2, _y2, w2, _h2 in rects[i + 1 :]:
            assert x1 + w1 <= x2 or x2 + w2 <= x1


def test_buttons_and_artwork_fit_within_canvas():
    width, height = CANVAS_SIZE
    layout = compute_layout(CANVAS_SIZE)

    for x, y, w, h in [layout.artwork_rect, layout.text_rect, *layout.buttons.values()]:
        assert x >= 0 and y >= 0
        assert x + w <= width
        assert y + h <= height


def test_button_at_hits_correct_button():
    layout = compute_layout(CANVAS_SIZE)
    x, y, w, h = layout.buttons["eject"]
    center = (x + w // 2, y + h // 2)

    assert button_at(layout, center) == "eject"


def test_button_at_misses_between_buttons():
    layout = compute_layout(CANVAS_SIZE)

    assert button_at(layout, (0, 0)) is None
