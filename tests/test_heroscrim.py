# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The hero scrims hug the words instead of a fixed rectangle.

Kodi measures a textbox on the next frame and will not paint a texture
at that size, so the scrim is computed from the string the label shows.
A short title stays narrow. A wrapped plot uses the column, because
that is the width the text wraps to. Ratings stay as wide as their
longest line.
"""
from lib.ui.heroscrim import (
    FEATHER,
    LEFT_SCRIM,
    RIGHT_SCRIM,
    block_size,
    place_hero_scrims,
    text_width,
)


class _Scrim:
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
        self.controls = {LEFT_SCRIM: _Scrim(), RIGHT_SCRIM: _Scrim()}

    def getControl(self, control_id):
        return self.controls[control_id]


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
    # A line that does not fit the quarter uses the quarter, not a
    # scrim wider than the text box.
    wide, tall = block_size(
        'Drama, Adventure, Science Fiction, Thriller', 25, 32, 380, 8,
    )
    assert wide == 380
    assert tall >= 64


def test_markup_is_not_counted_as_letters():
    plain = text_width('Dune', 37)
    marked = text_width('[B][COLOR FFFFFFFF]Dune[/COLOR][/B]', 37)
    assert marked == plain


def test_place_pulls_both_scrims_in_to_a_short_title():
    window = _Window()
    place_hero_scrims(window, 'home', 'Dune', 'A quiet film.', 'IMDb 8.1\n2024', False)
    left = window.controls[LEFT_SCRIM]
    right = window.controls[RIGHT_SCRIM]
    assert left.visible and right.visible
    # Full left stack is 1056 + 80 of feather. A short title is narrower.
    assert left.width < 1056
    assert left.height < 64 + 8 + 200 + 2 * FEATHER
    # The ratings box in the skin is 380 by 272. Two short lines are not.
    assert right.width < 380 + 2 * FEATHER
    assert right.height < 272
    assert right.x + right.width == 1860 + FEATHER
    assert left.x == 64 - FEATHER


def test_an_empty_hero_hides_the_scrims():
    window = _Window()
    place_hero_scrims(window, 'home', '', '', '', False)
    assert window.controls[LEFT_SCRIM].visible is False
    assert window.controls[RIGHT_SCRIM].visible is False


def test_estimates_cover_noto_sans():
    """The scrim is at least as wide as the face Kodi draws."""
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
    )
    for path, size, is_bold, text in samples:
        font = ImageFont.truetype(path, size)
        assert text_width(text, size, is_bold) >= font.getlength(text)
