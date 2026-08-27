from cd_player.ui.layout import (
    BUTTON_NAMES,
    MAX_SETTINGS_SPEAKER_ROWS,
    button_at,
    compute_layout,
    compute_settings_layout,
    settings_hit_at,
    volume_from_slider_x,
)

CANVAS_SIZE = (1280, 720)


def test_all_buttons_present_left_to_right():
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


def test_settings_layout_has_one_row_per_speaker():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=3)

    assert len(layout.speaker_rows) == 3


def test_settings_layout_caps_rows_at_max_non_scrolling():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=MAX_SETTINGS_SPEAKER_ROWS + 5)

    assert len(layout.speaker_rows) == MAX_SETTINGS_SPEAKER_ROWS


def test_settings_rows_do_not_overlap():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=MAX_SETTINGS_SPEAKER_ROWS)

    row_bands = [
        (min(cy, ly), max(cy + ch, ly + lh))
        for (cx, cy, cw, ch), (lx, ly, lw, lh) in layout.speaker_rows
    ]
    for i, (top1, bottom1) in enumerate(row_bands):
        for top2, bottom2 in row_bands[i + 1 :]:
            assert bottom1 <= top2 or bottom2 <= top1


def test_settings_layout_fits_within_canvas():
    width, height = CANVAS_SIZE
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=MAX_SETTINGS_SPEAKER_ROWS)

    rects = [layout.back_rect, layout.volume_slider_rect]
    for checkbox_rect, label_rect in layout.speaker_rows:
        rects.extend([checkbox_rect, label_rect])
    for x, y, w, h in rects:
        assert x >= 0 and y >= 0
        assert x + w <= width
        assert y + h <= height


def test_settings_hit_at_back():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=2)
    x, y, w, h = layout.back_rect

    assert settings_hit_at(layout, (x + w // 2, y + h // 2)) == ("back", None)


def test_settings_hit_at_speaker_checkbox_and_label():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=2)
    checkbox_rect, label_rect = layout.speaker_rows[1]

    cx, cy, cw, ch = checkbox_rect
    assert settings_hit_at(layout, (cx + cw // 2, cy + ch // 2)) == ("speaker_toggle", 1)

    lx, ly, lw, lh = label_rect
    assert settings_hit_at(layout, (lx + lw // 2, ly + lh // 2)) == ("speaker_toggle", 1)


def test_settings_hit_at_volume_slider():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=2)
    x, y, w, h = layout.volume_slider_rect

    assert settings_hit_at(layout, (x + w // 2, y + h // 2)) == ("volume_slider", None)


def test_settings_hit_at_misses_empty_space():
    layout = compute_settings_layout(CANVAS_SIZE, speaker_count=2)

    assert settings_hit_at(layout, (0, 0)) is None


def test_volume_from_slider_x_at_ends_and_midpoint():
    rect = (100, 0, 200, 50)  # x=100..300

    assert volume_from_slider_x(rect, 100) == 0
    assert volume_from_slider_x(rect, 300) == 100
    assert volume_from_slider_x(rect, 200) == 50


def test_volume_from_slider_x_clamps_outside_bounds():
    rect = (100, 0, 200, 50)

    assert volume_from_slider_x(rect, 0) == 0
    assert volume_from_slider_x(rect, 10_000) == 100
