"""Provider lists (Netflix, Disney+, Hulu, HBO...): previews without a
type, and ids no stream addon takes (rev22)."""
import contextlib

import pytest

from tests.kodistubs import install_kodi_stubs
from tests.test_streamswindow_fetch import _FakeAddonClient, _FakeStore, _wire_data_layer

_RELOAD = (
    'lib.ui.compat', 'lib.ui.dependencies', 'lib.ui.uicommon', 'lib.ui.dialogs', 'lib.ui.player',
    'lib.ui.streamswindow', 'lib.ui.previews', 'lib.ui.detailwindow',
)


@pytest.fixture
def load():
    with contextlib.ExitStack() as stack:
        def _load():
            return stack.enter_context(install_kodi_stubs(reload=_RELOAD))
        yield _load


# --- previews without a type ---------------------------------------------------


def test_a_preview_without_a_type_takes_the_catalogs():
    from lib.stremio.addons import default_meta_types

    metas = [{'id': 'tt1'}, {'id': 'tt2', 'type': 'series'}, 'junk']
    assert default_meta_types(metas, 'movie') == [{'id': 'tt1', 'type': 'movie'}, {'id': 'tt2', 'type': 'series'}, 'junk']
    assert default_meta_types([{'id': 'tt3'}], '') == [{'id': 'tt3'}]


# --- the id stream addons are asked for ---------------------------------------------


def test_the_imdb_id_comes_from_the_fields_stremio_uses(load):
    sw = load().streamswindow
    assert sw.imdb_id_for({'id': 'tmdb:603', 'imdb_id': 'tt0133093'}) == 'tt0133093'
    assert sw.imdb_id_for({'id': 'tmdb:603', 'behaviorHints': {'defaultVideoId': 'tt0133093'}}) == 'tt0133093'
    assert sw.imdb_id_for({'id': 'tt0133093'}) == 'tt0133093'
    assert sw.imdb_id_for({'id': 'tmdb:603'}) == ''
    assert sw.imdb_id_for(None) == ''


def test_a_provider_keyed_movie_is_asked_for_by_its_imdb_id(load):
    sw = load().streamswindow
    meta = {'id': 'tmdb:603', 'imdb_id': 'tt0133093'}
    assert sw.stream_alias('tmdb:603', meta) == 'tt0133093'
    assert sw.stream_alias('tt0133093', meta) == ''


def test_a_provider_keyed_episode_maps_to_season_and_episode(load):
    sw = load().streamswindow
    meta = {'id': 'tmdb:1399', 'imdb_id': 'tt0944947', 'videos': [
        {'id': 'tmdb:1399:1:3', 'season': 1, 'episode': 3},
        {'id': 'x-odd', 'season': 2, 'episode': 5},
    ]}
    assert sw.stream_alias('tmdb:1399:1:3', meta) == 'tt0944947:1:3'
    assert sw.stream_alias('x-odd', meta) == 'tt0944947:2:5'
    assert sw.stream_alias('tmdb:1399:4:7', meta) == 'tt0944947:4:7'  # not in the list: its own numbers
    assert sw.stream_alias('tmdb:1399', meta) == 'tt0944947'


def test_imdb_shows_and_anime_ids_are_asked_for_as_they_are(load):
    sw = load().streamswindow
    imdb_show = {'id': 'tt1', 'videos': [{'id': 's1e1', 'season': 1, 'episode': 1}]}
    assert sw.stream_alias('s1e1', imdb_show) == ''
    assert sw.stream_alias('kitsu:123:5', {'id': 'kitsu:123', 'imdb_id': 'tt9'}) == ''


def test_each_addon_gets_the_id_it_takes(load):
    ctx = load()
    sw = ctx.streamswindow
    imdb_only = {'transportUrl': 'tt-addon', 'manifest': {
        'name': 'Torrents', 'resources': ['stream'], 'types': ['movie'], 'idPrefixes': ['tt']}}
    tmdb_only = {'transportUrl': 'tmdb-addon', 'manifest': {
        'name': 'TMDB only', 'resources': ['stream'], 'types': ['movie'], 'idPrefixes': ['tmdb:']}}
    both = {'transportUrl': 'both', 'manifest': {
        'name': 'Both', 'resources': ['stream'], 'types': ['movie'], 'idPrefixes': ['tt', 'tmdb:']}}
    client = _FakeAddonClient({'tt-addon': [], 'tmdb-addon': [], 'both': []})
    _wire_data_layer(sw, _FakeStore(addons=[imdb_only, tmdb_only, both]), client)
    targets = sw._stream_targets('movie', 'tmdb:603', {'id': 'tmdb:603', 'imdb_id': 'tt0133093'})
    assert [(d['transportUrl'], rid) for d, _m, rid in targets] == [
        ('tt-addon', 'tt0133093'), ('tmdb-addon', 'tmdb:603'), ('both', 'tt0133093'),
    ]
    results = sw._start_stream_fetch_workers('movie', 'tmdb:603', targets)
    for _ in targets:
        results.get(timeout=5)
    assert sorted(call[2] for call in client.calls) == ['tmdb:603', 'tt0133093', 'tt0133093']


def test_without_an_imdb_id_nothing_changes(load):
    sw = load().streamswindow
    imdb_only = {'transportUrl': 'tt-addon', 'manifest': {
        'name': 'Torrents', 'resources': ['stream'], 'types': ['movie'], 'idPrefixes': ['tt']}}
    _wire_data_layer(sw, _FakeStore(addons=[imdb_only]), _FakeAddonClient({'tt-addon': []}))
    assert sw._stream_targets('movie', 'tmdb:603', {'id': 'tmdb:603'}) == []


# --- opening a title whose id no meta addon resolves ---------------------------------


def test_search_match_needs_the_same_name_type_and_year():
    from lib.ui.previews import best_match

    preview = {'name': 'The Matrix', 'type': 'movie', 'releaseInfo': '1999'}
    found = [
        {'id': 'tt30849200', 'type': 'movie', 'name': 'The Matrix Collection'},
        {'id': 'tt0234215', 'type': 'movie', 'name': 'The Matrix Reloaded', 'releaseInfo': '2003'},
        {'id': 'tt9999999', 'type': 'series', 'name': 'The Matrix'},
        {'id': 'tt0133093', 'type': 'movie', 'name': 'The Matrix', 'releaseInfo': '1999'},
    ]
    assert best_match(preview, found, 'movie') == 'tt0133093'
    assert best_match(dict(preview, releaseInfo='2021'), found, 'movie') == ''
    assert best_match({'name': ''}, found, 'movie') == ''


def test_previews_are_remembered_by_id(load):
    from lib.ui import previews

    previews.forget_all()
    previews.remember({'id': 'tmdb:603', 'name': 'The Matrix', 'type': 'movie', 'poster': 'p.jpg'})
    assert previews.lookup('tmdb:603') == {'id': 'tmdb:603', 'name': 'The Matrix', 'type': 'movie'}
    assert previews.lookup('nope') is None


def test_open_detail_falls_back_to_the_imdb_id(load, monkeypatch):
    ctx = load()
    import lib.ui.detailwindow as detailwindow
    import lib.ui.streamswindow as streamswindow
    import lib.ui.views as views
    from lib.ui import previews

    previews.forget_all()
    previews.remember({'id': 'tmdb:603', 'name': 'The Matrix', 'imdb_id': 'tt0133093'})
    asked = []
    movie = {'id': 'tt0133093', 'type': 'movie', 'name': 'The Matrix'}
    monkeypatch.setattr(views, '_fetch_meta', lambda stype, sid, **kw: asked.append((stype, sid)) or (movie if sid.startswith('tt') else None))
    monkeypatch.setattr(detailwindow, '_pull_account_item', lambda sid: None)
    opened = []
    monkeypatch.setattr(streamswindow, 'open_streams', lambda stype, sid, **kw: opened.append((stype, sid)) or False)
    detailwindow.open_detail('', 'tmdb:603')
    # No type on the preview: a movie is tried; the IMDb id opens it.
    assert asked == [('movie', 'tmdb:603'), ('movie', 'tt0133093')]
    assert opened == [('movie', 'tt0133093')]
    assert 'STR30430' not in [n[1] for n in ctx.env.notifications]
