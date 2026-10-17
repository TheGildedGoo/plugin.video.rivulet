# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""#18: TMDB art is asked for at the size the skin draws.

Catalogs built on TMDB hand out ``/t/p/original/`` paths: multi-megabyte
files Kodi downloads whole before it can scale a 200px card. `sized_image`
rewrites only TMDB paths and only downward.
"""
from lib.ui.urlutil import sized_image

_BASE = 'https://image.tmdb.org/t/p/%s/abc.jpg'


def test_original_poster_and_backdrop_come_down_to_the_drawn_size():
    assert sized_image(_BASE % 'original', 'poster') == _BASE % 'w342'
    assert sized_image(_BASE % 'original', 'backdrop') == _BASE % 'w1280'
    assert sized_image(_BASE % 'original', 'fill') == _BASE % 'w780'


def test_a_wider_w_size_is_reduced_and_a_smaller_one_is_kept():
    assert sized_image(_BASE % 'w780', 'poster') == _BASE % 'w342'
    assert sized_image(_BASE % 'w185', 'poster') == _BASE % 'w185'
    assert sized_image(_BASE % 'w780', 'backdrop') == _BASE % 'w780'
    assert sized_image(_BASE % 'w1920', 'backdrop') == _BASE % 'w1280'


def test_other_hosts_and_height_sizes_are_left_alone():
    metahub = 'https://images.metahub.space/poster/small/tt0944947/img'
    assert sized_image(metahub, 'poster') == metahub
    assert sized_image(_BASE % 'h632', 'poster') == _BASE % 'h632'
    assert sized_image('http://image.tmdb.org/t/p/original/x.png', 'poster') == (
        'http://image.tmdb.org/t/p/w342/x.png'
    )


def test_unknown_kind_and_non_strings_are_safe():
    assert sized_image(_BASE % 'original', 'logo') == _BASE % 'original'
    assert sized_image(None, 'poster') == ''
    assert sized_image('', 'backdrop') == ''
