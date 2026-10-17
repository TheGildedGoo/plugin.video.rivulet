# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The hero bar is one full-width plate, as tall as the words.

Kodi measures a textbox on the next frame and will not paint a texture
at that size, so the bar is computed from the string the label shows.
A short plot sits lower, on a shorter bar. A full plot keeps the skin
bar, whose bottom is the poster row. The top 64 pixels are the fade.
"""
from lib.ui.heroscrim import (
    ANCHORS,
    BAR,
    FADE,
    block_size,
    place_hero_bar,
    text_width,
)


class _Box:
    def __init__(self):
        self.visible = True
        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def setVisible(self, visible):
        self.visible = visible

    def setPosition(self, x, y):
        self.x = x
        self.y = y

    def setWidth(self, width):
        self.width = width

    def setHeight(self, height):
        self.height = height


class _Window:
    def __init__(self):
        self.controls = {}

    def getControl(self, control_id):
        box = self.controls.get(control_id)
        if box is None:
            box = _Box()
            self.controls[control_id] = box
        return box


def test_a_short_title_does_not_use_the_column():
    width, height = block_size('Dune', 37, 64, 1056, 1)
    assert height == 64
    assert 60 <= width <= 220


def test_a_wrapped_plot_fills_the_column_and_grows_by_lines():
    short_w, short_h = block_size('A quiet film.', 30, 30, 1056, 6)
    assert short_h == 30
    assert short_w < 400
    plot = (
        'A group of explorers make a startling discovery that changes '
        'everything they thought they knew about the ocean and the '
        'things that live under it.'
    )
    width, height = block_size(plot, 30, 30, 1056, 6)
    assert width == 1056
    assert 60 <= height <= 180
    assert height > short_h


def test_ratings_hug_the_longest_line():
    width, height = block_size('IMDb 8.1\n2024\n2h 15m', 25, 32, 380, 8)
    assert height == 96
    assert width < 200
    # A line that does not fit the quarter uses the quarter.
    wide, tall = block_size(
        'Drama, Adventure, Science Fiction, Thriller', 25, 32, 380, 8,
    )
    assert wide == 380
    assert tall >= 64


def test_markup_is_not_counted_as_letters():
    plain = text_width('Dune', 37)
    marked = text_width('[B][COLOR FFFFFFFF]Dune[/COLOR][/B]', 37)
    assert marked == plain


def test_a_short_plot_sits_lower_on_a_shorter_bar():
    """One plot line and two rating lines. The stack ends above the row."""
    window = _Window()
    place_hero_bar(window, 'home', 'Dune', 'A quiet film.', 'IMDb 8.1\n2024', False)
    bar = window.controls[BAR]
    end = ANCHORS['home']['band'] - ANCHORS['home']['row_gap']
    assert bar.visible
    assert bar.x == 0 and bar.width == 1920
    assert bar.y == 466
    assert bar.height == 186
    assert bar.y + bar.height == end
    assert window.controls[30020].y == 530
    assert window.controls[30020].height == 64
    assert window.controls[30023].y == 530
    assert window.controls[30022].y == 602
    assert window.controls[30022].height == 50
    assert window.controls[30021].y == 530
    # Two ratings lines of font13 (#11): 2 x 38.
    assert window.controls[30021].height == 76
    # The fade is above the words, not a hard edge through them.
    assert window.controls[30020].y - bar.y == FADE


def test_a_full_plot_keeps_the_skin_bar():
    plot = ' '.join(['discovery'] * 90)
    _width, height = block_size(plot, 30, 30, 1056, 6)
    assert height == 180
    window = _Window()
    place_hero_bar(window, 'home', 'Dune', plot, 'IMDb 8.1', False)
    bar = window.controls[BAR]
    assert bar.y == 316
    assert bar.height == 336
    assert bar.y + bar.height == 652
    assert window.controls[30020].y == 380
    assert window.controls[30022].height == 200


def test_a_grid_caption_is_part_of_the_stack():
    window = _Window()
    place_hero_bar(
        window, 'grid', 'Dune', 'A quiet film.', '', False, '42% watched',
    )
    bar = window.controls[BAR]
    assert bar.y + bar.height == ANCHORS['grid']['band']
    assert window.controls[30025].height == 32
    assert window.controls[30025].y + window.controls[30025].height == 684


def test_an_empty_hero_hides_the_bar():
    window = _Window()
    place_hero_bar(window, 'home', '', '', '', False)
    assert window.controls[BAR].visible is False
    # Nothing to measure, so the title stays where the skin put it.
    assert 30020 not in window.controls


def test_estimates_cover_noto_sans():
    """The estimate is at least as wide as the face Kodi draws."""
    import os

    import pytest
    pytest.importorskip('PIL')
    from PIL import ImageFont

    regular = '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf'
    if not os.path.exists(regular):
        pytest.skip('Noto Sans is not installed')
    bold = '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf'
    samples = (
        (regular, 30, False, 'A group of explorers make a discovery.'),
        (regular, 37, False, 'The Lord of the Rings'),
        (bold, 37, True, 'The Lord of the Rings: The Return of the King'),
        (bold, 60, True, 'Dune'),
        (regular, 25, False, 'IMDb 8.1'),
        (regular, 25, False, 'Drama, Adventure'),
        (regular, 30, False, 'Rotten Tomatoes 94%'),
        (regular, 30, False, 'Science Fiction, Adventure'),
    )
    for path, size, is_bold, text in samples:
        font = ImageFont.truetype(path, size)
        assert text_width(text, size, is_bold) >= font.getlength(text)
