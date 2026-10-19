"""Provider lists (Netflix, Disney+, Hulu, HBO...): previews without a
type, and ids no stream or meta addon takes."""
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


def test_filling_in_a_type_leaves_the_callers_dicts_alone():
    from lib.stremio.addons import default_meta_types

    original = {'id': 'tmdb:603'}
    metas = [original]
    filled = default_meta_types(metas, 'movie')
    assert filled == [{'id': 'tmdb:603', 'type': 'movie'}]
    assert original == {'id': 'tmdb:603'}
    assert metas == [{'id': 'tmdb:603'}]


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
    previews.remember({'id': 'tmdb:603', 'name': 'The Matrix', 'type': 'movie', 'poster': 'p.jpg', 'genres': ['x']})
    assert previews.lookup('tmdb:603') == {'id': 'tmdb:603', 'name': 'The Matrix', 'type': 'movie', 'poster': 'p.jpg'}
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
    opened = []
    monkeypatch.setattr(streamswindow, 'open_streams', lambda stype, sid, **kw: opened.append((stype, sid)) or False)
    detailwindow.open_detail('', 'tmdb:603')
    # No type on the preview: a movie is tried, then a series; the IMDb id opens it.
    assert asked == [('movie', 'tmdb:603'), ('series', 'tmdb:603'), ('movie', 'tt0133093')]
    assert opened == [('movie', 'tt0133093')]
    assert 'STR30030' not in [n[1] for n in ctx.env.notifications]


def test_a_movie_nobody_has_a_meta_for_opens_its_streams_from_the_preview(load, monkeypatch):
    """What stock Rivulet does with a catalog movie."""
    load()
    import lib.ui.detailwindow as detailwindow
    import lib.ui.streamswindow as streamswindow
    import lib.ui.views as views
    from lib.ui import previews

    previews.forget_all()
    previews.remember({'id': 'tt0133093', 'type': 'movie', 'name': 'The Matrix', 'poster': 'p.jpg'})
    monkeypatch.setattr(views, '_fetch_meta', lambda stype, sid, **kw: None)
    opened = []
    monkeypatch.setattr(streamswindow, 'open_streams', lambda stype, sid, **kw: opened.append((stype, sid, kw['meta']['name'])) or False)
    detailwindow.open_detail('movie', 'tt0133093')
    assert opened == [('movie', 'tt0133093', 'The Matrix')]


def test_a_title_listed_as_the_wrong_type_still_opens(load, monkeypatch):
    load()
    import lib.ui.detailwindow as detailwindow
    import lib.ui.views as views

    show = {'id': 'tt0944947', 'type': 'series', 'name': 'GoT', 'videos': []}
    monkeypatch.setattr(views, '_fetch_meta', lambda stype, sid, **kw: show if stype == 'series' else None)
    assert detailwindow._fetch_meta_any_type('Movies', 'tt0944947') == (show, 'series')


def test_the_swapped_type_is_tried_after_a_quick_miss(load, monkeypatch):
    load()
    import lib.ui.detailwindow as detailwindow
    import lib.ui.views as views

    show = {'id': 'tt0944947', 'type': 'series', 'name': 'GoT', 'videos': []}
    asked = []
    monkeypatch.setattr(views, '_fetch_meta', lambda stype, sid, **kw: asked.append(stype) or (show if stype == 'series' else None))
    assert detailwindow._fetch_meta_any_type('movie', 'tt0944947') == (show, 'series')
    assert asked == ['movie', 'series']


def test_the_swapped_type_is_skipped_after_a_slow_miss(load, monkeypatch):
    """A movie lookup that timed out across addons is not repeated as a series."""
    load()
    import types

    import lib.ui.detailwindow as detailwindow
    import lib.ui.views as views

    clock = {'now': 0.0}
    monkeypatch.setattr(detailwindow, 'time', types.SimpleNamespace(monotonic=lambda: clock['now']))
    asked = []

    def _slow_miss(stype, sid, **kw):
        asked.append(stype)
        clock['now'] += detailwindow._SWAPPED_TYPE_MAX_SECONDS + 1
        return None

    monkeypatch.setattr(views, '_fetch_meta', _slow_miss)
    assert detailwindow._fetch_meta_any_type('movie', 'tt0944947') == (None, 'movie')
    assert asked == ['movie']


def test_a_failing_imdb_lookup_is_logged_not_swallowed(load, monkeypatch):
    ctx = load()
    import xbmc

    import lib.ui.detailwindow as detailwindow
    import lib.ui.searchwindow as searchwindow

    def _boom(*args, **kwargs):
        raise RuntimeError('https://secret.example/token/manifest.json')

    import lib.ui.dependencies as dependencies

    monkeypatch.setattr(dependencies, 'get_store', lambda: object())
    monkeypatch.setattr(dependencies, 'get_client', lambda: object())
    monkeypatch.setattr(searchwindow, 'run_query', _boom)
    assert detailwindow._imdb_alternative('movie', 'tmdb:603', {'id': 'tmdb:603', 'name': 'The Matrix'}) == ''
    warnings = [msg for msg, level in ctx.env.log_calls if level == xbmc.LOGWARNING]
    assert any('IMDb lookup by search for movie/tmdb:603 failed: RuntimeError' in m for m in warnings)
    assert not any('secret.example' in m for m in warnings)


# --- streams: learning the IMDb id before asking IMDb-only addons -----------


_IMDB_ONLY = {'transportUrl': 'tt-addon', 'manifest': {
    'name': 'Torrents', 'resources': ['stream'], 'types': ['movie'], 'idPrefixes': ['tt']}}


def test_a_fetched_imdb_id_lets_an_imdb_only_addon_be_asked(load, monkeypatch):
    ctx = load()
    sw = ctx.streamswindow
    import lib.ui.uicommon as uicommon
    import lib.ui.views as views

    _wire_data_layer(sw, _FakeStore(addons=[_IMDB_ONLY]), _FakeAddonClient({}))
    monkeypatch.setattr(views, '_fetch_meta', lambda stype, sid, **kw: {'id': 'tt0133093', 'type': 'movie'})
    monkeypatch.setattr(uicommon, 'run_cancellable', lambda callback, _heading: callback())
    preview = {'id': 'tmdb:603', 'name': 'The Matrix'}

    assert sw._stream_targets('movie', 'tmdb:603', preview) == []
    merged = sw._meta_with_imdb('movie', 'tmdb:603', preview)
    assert merged['imdb_id'] == 'tt0133093'
    assert preview == {'id': 'tmdb:603', 'name': 'The Matrix'}  # the caller's preview is not changed
    assert [entry[2] for entry in sw._stream_targets('movie', 'tmdb:603', merged)] == ['tt0133093']


def test_a_cancelled_imdb_lookup_keeps_the_preview(load, monkeypatch):
    ctx = load()
    sw = ctx.streamswindow
    import lib.ui.uicommon as uicommon

    preview = {'id': 'tmdb:603', 'name': 'The Matrix'}
    monkeypatch.setattr(uicommon, 'run_cancellable', lambda *_args: uicommon.CANCELLED)
    assert sw._meta_with_imdb('movie', 'tmdb:603', preview) is preview


def test_a_failing_imdb_meta_lookup_keeps_the_preview_and_is_logged(load, monkeypatch):
    ctx = load()
    sw = ctx.streamswindow
    import xbmc

    import lib.ui.uicommon as uicommon

    def _boom(*_args):
        raise RuntimeError('https://secret.example/token/manifest.json')

    preview = {'id': 'tmdb:603', 'name': 'The Matrix'}
    monkeypatch.setattr(uicommon, 'run_cancellable', _boom)
    assert sw._meta_with_imdb('movie', 'tmdb:603', preview) is preview
    warnings = [msg for msg, level in ctx.env.log_calls if level == xbmc.LOGWARNING]
    assert any('IMDb meta lookup for movie/tmdb:603 failed: RuntimeError' in m for m in warnings)
    assert not any('secret.example' in m for m in warnings)


def test_an_imdb_keyed_title_needs_no_lookup(load, monkeypatch):
    ctx = load()
    sw = ctx.streamswindow
    import lib.ui.uicommon as uicommon

    monkeypatch.setattr(uicommon, 'run_cancellable', lambda *_args: pytest.fail('looked up'))
    meta = {'id': 'tt0133093'}
    assert sw._meta_with_imdb('movie', 'tt0133093', meta) is meta
