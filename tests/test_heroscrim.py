# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""How tall hero text will be (lib/ui/heroscrim.py), measured in Python.

Kodi measures a textbox on the next frame, so the new-look hero stacks
its lines from this estimate of the string the label shows.
"""
from lib.ui.heroscrim import block_size, text_width


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
