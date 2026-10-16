# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Year-catalog detection and the popularity merge. No Kodi."""
from lib.stremio.addons import AddonError
from lib.stremio.decades import (
    DECADE_FLOOR,
    decade_tiles,
    is_year_catalog,
    merge_decade_pages,
)

_YEAR = {
    'type': 'movie', 'id': 'year', 'name': 'New',
    'extra': [{'name': 'genre', 'isRequired': True, 'options': [
        '2026', '2020', '2014', '1994', '1960', '1959', '1920',
    ]}],
}


def test_year_catalog_is_every_required_genre_option_a_year():
    assert is_year_catalog(_YEAR) is True
    mixed = {
        'extra': [{'name': 'genre', 'isRequired': True, 'options': ['2020', 'Action']}],
    }
    assert is_year_catalog(mixed) is False
    assert is_year_catalog({'extra': [{'name': 'search', 'isRequired': True}]}) is False
    assert is_year_catalog(None) is False


def test_tiles_stop_at_the_1960s_and_do_not_invent_older_ones():
    tiles = decade_tiles([
        '2026', '2024', '2010', '1999', '1960', '1959', '1920',
    ])
    assert [tile['label'] for tile in tiles] == [
        '2020s', '2010s', '1990s', '1960s',
    ]
    assert tiles[0]['years'] == ['2026', '2024']
    assert tiles[-1]['start'] == DECADE_FLOOR
    assert decade_tiles(['1950', '1940', '1920']) == []
    assert decade_tiles(['2020', 'Action']) == []


def _page(skip):
    """1994, newest-first. The title people mean is on the third page."""
    if skip == 0:
        return [{'id': 'obscure-%d' % index, 'name': 'Obscure', 'popularities': {'moviedb': 1.5}}
                for index in range(50)], True
    if skip == 50:
        return [{'id': 'mid-%d' % index, 'popularities': {'moviedb': 1.2}} for index in range(50)], True
    if skip == 100:
        head = [{'id': 'shawshank', 'name': 'The Shawshank Redemption', 'popularities': {'moviedb': 56.3}}]
        rest = [{'id': 'p3-%d' % index, 'popularities': {'moviedb': 1.1}} for index in range(49)]
        return head + rest, True
    if skip == 150:
        head = [{'id': 'gump', 'name': 'Forrest Gump', 'popularities': {'moviedb': 40}}]
        rest = [{'id': 'p4-%d' % index, 'popularities': {'moviedb': 1.0}} for index in range(49)]
        return head + rest, False
    raise AssertionError('unexpected skip %s' % skip)


def test_four_pages_surface_the_popular_title_a_single_page_misses():
    def fetch(year, skip):
        assert year == '1994'
        metas, has_more = _page(skip)
        return metas, has_more

    merged = merge_decade_pages(['1994'], fetch, max_pages=4)
    assert merged[0]['id'] == 'shawshank'
    assert merged[1]['id'] == 'gump'

    one_page = merge_decade_pages(['1994'], fetch, max_pages=1)
    assert one_page[0]['id'] == 'obscure-0'
    assert all(meta['id'] != 'shawshank' for meta in one_page)


def test_a_hung_year_does_not_drop_the_others():
    def fetch(year, skip):
        if year == '1995':
            raise AddonError('hung')
        return [{'id': year, 'popularities': {'moviedb': 4}}], False

    merged = merge_decade_pages(['1994', '1995', '1996'], fetch)
    assert [meta['id'] for meta in merged] == ['1994', '1996']


def test_sort_uses_moviedb_then_popularity_then_rating_and_missing_last():
    def fetch(year, skip):
        return [
            {'id': 'blank'},
            {'id': 'rated', 'imdbRating': '8.1'},
            {'id': 'pop', 'popularity': 9},
            {'id': 'mdb', 'popularities': {'moviedb': 2}, 'popularity': 1},
        ], False

    merged = merge_decade_pages(['1994'], fetch, max_pages=1)
    assert [meta['id'] for meta in merged] == ['mdb', 'pop', 'rated', 'blank']


def test_duplicate_ids_across_years_collapse():
    def fetch(year, skip):
        return [{'id': 'same', 'popularities': {'moviedb': int(year) - 1990}}], False

    merged = merge_decade_pages(['1991', '1999'], fetch)
    assert [meta['id'] for meta in merged] == ['same']
    assert len(merged) == 1
