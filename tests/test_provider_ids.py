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


def _merged_with(ctx, monkeypatch, preview, full):
    sw = ctx.streamswindow
    import lib.ui.uicommon as uicommon
    import lib.ui.views as views

    monkeypatch.setattr(views, '_fetch_meta', lambda stype, sid, **kw: full)
    monkeypatch.setattr(uicommon, 'run_cancellable', lambda callback, _heading: callback())
    return sw._meta_with_imdb('movie', 'tmdb:603', preview)


def test_an_empty_imdb_id_on_the_preview_does_not_hide_the_full_metas(load, monkeypatch):
    """CodeRabbit on #68: ``imdb_id: null`` blocked a provider-keyed meta's IMDb id."""
    ctx = load()
    preview = {'id': 'tmdb:603', 'name': 'The Matrix', 'imdb_id': None}
    merged = _merged_with(ctx, monkeypatch, preview, {'id': 'tmdb:603', 'imdb_id': 'tt0133093'})
    assert merged['imdb_id'] == 'tt0133093'
    assert ctx.streamswindow.stream_alias('tmdb:603', merged) == 'tt0133093'
    assert preview['imdb_id'] is None


def test_empty_preview_hints_take_the_full_metas(load, monkeypatch):
    ctx = load()
    preview = {'id': 'tmdb:603', 'behaviorHints': {}}
    full = {'id': 'tmdb:603', 'behaviorHints': {'defaultVideoId': 'tt0133093', 'hasScheduledVideos': False}}
    merged = _merged_with(ctx, monkeypatch, preview, full)
    assert merged['behaviorHints'] == full['behaviorHints']
    assert merged['behaviorHints'] is not full['behaviorHints']
    assert ctx.streamswindow.imdb_id_for(merged) == 'tt0133093'


def test_the_default_video_id_joins_the_previews_own_hints(load, monkeypatch):
    ctx = load()
    preview = {'id': 'tmdb:603', 'behaviorHints': {'bingeGroup': 'matrix'}}
    full = {'id': 'tmdb:603', 'behaviorHints': {'defaultVideoId': 'tt0133093', 'bingeGroup': 'other'}}
    merged = _merged_with(ctx, monkeypatch, preview, full)
    assert merged['behaviorHints'] == {'bingeGroup': 'matrix', 'defaultVideoId': 'tt0133093'}
    assert preview['behaviorHints'] == {'bingeGroup': 'matrix'}


def test_the_previews_own_imdb_fields_are_kept(load, monkeypatch):
    ctx = load()
    preview = {'id': 'tmdb:603', 'imdbId': 'x', 'behaviorHints': {'defaultVideoId': 'kept'}}
    full = {'id': 'tmdb:603', 'imdbId': 'tt0133093', 'behaviorHints': {'defaultVideoId': 'tt0133093'}}
    merged = _merged_with(ctx, monkeypatch, preview, full)
    assert merged['imdbId'] == 'x'
    assert merged['behaviorHints'] == {'defaultVideoId': 'kept'}


def test_a_tv_listed_show_is_found_by_search_as_a_series(load, monkeypatch):
    """A provider list that calls its shows "tv": the search answers "series"."""
    load()
    import lib.ui.dependencies as dependencies
    import lib.ui.detailwindow as detailwindow
    import lib.ui.searchwindow as searchwindow

    monkeypatch.setattr(dependencies, 'get_store', lambda: object())
    monkeypatch.setattr(dependencies, 'get_client', lambda: object())
    monkeypatch.setattr(searchwindow, 'run_query', lambda *a, **kw: [
        {'id': 'tt0944947', 'type': 'series', 'name': 'Game of Thrones', 'releaseInfo': '2011\u20132019'},
    ])
    preview = {'id': 'tmdb:1399', 'type': 'tv', 'name': 'Game of Thrones', 'releaseInfo': '2011'}
    assert detailwindow._imdb_alternative('tv', 'tmdb:1399', preview) == 'tt0944947'


# --- a series from a provider list must reach its episodes ------------------


_CINEMETA = {'transportUrl': 'https://cinemeta.example/manifest.json', 'manifest': {
    'name': 'Cinemeta', 'resources': ['catalog', 'meta'], 'types': ['movie', 'series'], 'idPrefixes': ['tt'],
    'catalogs': []}}
_PROVIDER_LISTS = {'transportUrl': 'https://lists.example/manifest.json', 'manifest': {
    'name': 'Provider lists', 'resources': ['catalog', 'meta'], 'types': ['movie', 'series'],
    'idPrefixes': ['tt', 'tmdb:'], 'catalogs': []}}
_TT_STREAMS = {'transportUrl': 'https://streams.example/manifest.json', 'manifest': {
    'name': 'Streams', 'resources': ['stream'], 'types': ['movie', 'series'], 'idPrefixes': ['tt']}}
_GOT = {'id': 'tt0944947', 'type': 'series', 'name': 'Game of Thrones', 'videos': [
    {'id': 'tt0944947:1:1', 'season': 1, 'episode': 1}, {'id': 'tt0944947:1:2', 'season': 1, 'episode': 2}]}


class _MetaClient:
    """Answers `meta()` per (transport, type, id); every other call is a miss."""

    def __init__(self, metas):
        self.metas = metas
        self.asked = []

    def meta(self, transport, stype, sid):
        from lib.stremio.addons import AddonError

        self.asked.append((transport, stype, sid))
        found = self.metas.get((transport, stype, sid))
        if found is None:
            raise AddonError('not found', category='not found')
        return dict(found)


def _wire_addons(monkeypatch, addons, metas):
    import lib.ui.dependencies as dependencies
    import lib.ui.streamswindow as streamswindow
    import lib.ui.views as views

    store = _FakeStore(addons=addons)
    client = _MetaClient(metas)
    for module in (dependencies, views):
        monkeypatch.setattr(module, 'get_store', lambda: store)
        monkeypatch.setattr(module, 'get_client', lambda: client)
    _wire_data_layer(streamswindow, store, client)
    return client


def _first_episode_request(resolved):
    import lib.ui.streamswindow as streamswindow

    meta, stype, _sid = resolved
    episode = meta['videos'][0]['id']
    return [entry[2] for entry in streamswindow._stream_targets(stype, episode, meta)]


def test_a_show_whose_list_answers_a_meta_without_episodes_still_opens_its_episodes(load, monkeypatch):
    """Dylan on CoreELEC: every show from a provider list said "No streams
    found". The list's addon answered the show's meta first, with no
    episodes, so it was opened like a movie and streams were asked for
    the show itself."""
    load()
    import lib.ui.detailwindow as detailwindow

    _wire_addons(monkeypatch, [_PROVIDER_LISTS, _CINEMETA, _TT_STREAMS], {
        (_PROVIDER_LISTS['transportUrl'], 'series', 'tt0944947'): {'id': 'tt0944947', 'type': 'series', 'name': 'GoT'},
        (_CINEMETA['transportUrl'], 'series', 'tt0944947'): _GOT,
    })
    preview = {'id': 'tt0944947', 'type': 'series', 'name': 'Game of Thrones'}
    resolved = detailwindow._resolve_meta('series', 'tt0944947', preview)
    assert resolved[0]['videos'] == _GOT['videos']
    assert resolved[1:] == ('series', 'tt0944947')
    assert _first_episode_request(resolved) == ['tt0944947:1:1']


def test_a_provider_keyed_show_without_episodes_opens_by_its_imdb_id(load, monkeypatch):
    load()
    import lib.ui.detailwindow as detailwindow

    _wire_addons(monkeypatch, [_PROVIDER_LISTS, _CINEMETA, _TT_STREAMS], {
        (_PROVIDER_LISTS['transportUrl'], 'series', 'tmdb:1399'): {
            'id': 'tmdb:1399', 'type': 'series', 'name': 'Game of Thrones', 'imdb_id': 'tt0944947', 'videos': []},
        (_CINEMETA['transportUrl'], 'series', 'tt0944947'): _GOT,
    })
    preview = {'id': 'tmdb:1399', 'type': 'series', 'name': 'Game of Thrones'}
    resolved = detailwindow._resolve_meta('series', 'tmdb:1399', preview)
    assert resolved[1:] == ('series', 'tt0944947')
    assert _first_episode_request(resolved) == ['tt0944947:1:1']


def test_provider_episode_ids_are_asked_for_as_imdb_episodes(load, monkeypatch):
    """A provider-keyed series WITH episodes keeps its own ids; only the
    stream request uses ``tt...:season:episode``."""
    load()
    import lib.ui.detailwindow as detailwindow

    show = {'id': 'tmdb:1399', 'type': 'series', 'name': 'Game of Thrones', 'imdb_id': 'tt0944947', 'videos': [
        {'id': 'tmdb:1399:1:1', 'season': 1, 'episode': 1}]}
    client = _wire_addons(monkeypatch, [_PROVIDER_LISTS, _CINEMETA, _TT_STREAMS], {
        (_PROVIDER_LISTS['transportUrl'], 'series', 'tmdb:1399'): show,
    })
    resolved = detailwindow._resolve_meta('series', 'tmdb:1399', {'id': 'tmdb:1399', 'type': 'series'})
    assert resolved[1:] == ('series', 'tmdb:1399')
    assert resolved[0]['videos'][0]['id'] == 'tmdb:1399:1:1'
    assert _first_episode_request(resolved) == ['tt0944947:1:1']
    assert not any(sid == 'tt0944947' for _t, _s, sid in client.asked)  # no extra lookup


def test_a_show_nobody_has_episodes_for_is_left_as_it_was(load, monkeypatch):
    load()
    import lib.ui.detailwindow as detailwindow

    bare = {'id': 'tt0944947', 'type': 'series', 'name': 'GoT'}
    _wire_addons(monkeypatch, [_PROVIDER_LISTS, _TT_STREAMS], {
        (_PROVIDER_LISTS['transportUrl'], 'series', 'tt0944947'): bare,
    })
    resolved = detailwindow._resolve_meta('series', 'tt0944947', {'id': 'tt0944947', 'type': 'series'})
    assert resolved == (bare, 'series', 'tt0944947')


def test_a_movie_without_episodes_is_not_looked_up_again(load, monkeypatch):
    load()
    import lib.ui.detailwindow as detailwindow

    movie = {'id': 'tt0133093', 'type': 'movie', 'name': 'The Matrix'}
    client = _wire_addons(monkeypatch, [_CINEMETA, _TT_STREAMS], {
        (_CINEMETA['transportUrl'], 'movie', 'tt0133093'): movie,
    })
    assert detailwindow._resolve_meta('movie', 'tt0133093', {'id': 'tt0133093', 'type': 'movie'}) == (
        movie, 'movie', 'tt0133093')
    assert client.asked == [(_CINEMETA['transportUrl'], 'movie', 'tt0133093')]
