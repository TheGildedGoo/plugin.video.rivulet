# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The right-quarter hero panel. No Kodi."""
from lib.ui.playbackmeta import hero_panel_text


def test_panel_prints_whatever_the_meta_actually_carries():
    text = hero_panel_text({
        'imdbRating': '8.4',
        'rottenTomatoes': '91%',
        'metascore': 80,
        'releaseInfo': '2019',
        'runtime': '132 min',
        'genres': ['Action', 'Sci-Fi', 'Adventure', 'Drama'],
    }, now_word='now')
    assert text == '\n'.join([
        'Rotten Tomatoes 91%',
        'Metascore 80',
        'IMDb 8.4',
        '2019',
        '132 min',
        'Action, Sci-Fi, Adventure',
    ])


def test_panel_reads_a_ratings_list_and_skips_what_is_missing():
    text = hero_panel_text({
        'ratings': [
            {'source': 'Internet Movie Database', 'value': '7.2'},
            {'source': 'Rotten Tomatoes', 'value': '64%'},
            {'source': 'Trakt', 'value': '70'},
        ],
        'releaseInfo': '2022–',
    }, now_word='now')
    assert text == 'Rotten Tomatoes 64%\nIMDb 7.2\n2022–now'
    assert 'Trakt' not in text
    assert 'Metascore' not in text


def test_panel_hides_an_empty_rating_instead_of_a_bare_label():
    assert hero_panel_text({'imdbRating': 'n/a', 'year': '1999'}) == '1999'
    assert hero_panel_text({}) == ''
    assert hero_panel_text(None) == ''


def test_passed_in_runtime_wins_over_the_raw_field():
    text = hero_panel_text({'runtime': 98}, runtime_text='98 min')
    assert text == '98 min'
