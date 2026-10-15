# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""One user path per test, crossing the modules that path actually uses.

The unit files pin a single function. These walk the same objects a
remote press would: Home's shelves, a hub decade into the coverflow,
Library past twelve titles, Continue Resume into Up next (season
boundary, series end, Back, Stop), the playback sync clock, and a
disk-backed addon pull that merges before it pushes.
"""
import contextlib
import datetime

import pytest

from tests.kodistubs import install_kodi_stubs
from tests.test_service_runner_player import (
    _CONTEXT,
    _FakeProgressAPI,
    _FakeProgressStore,
    _progress_player_env,
)

_HOME = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.router', 'lib.ui.homewindow',
    'lib.ui.catalogpicker', 'lib.ui.searchwindow', 'lib.ui.mystuff',
    'lib.ui.addonswindow', 'lib.ui.gridwindow', 'lib.ui.detailwindow',
    'lib.ui.hubwindow', 'lib.ui.dialogs', 'lib.ui.dependencies',
    'lib.ui.libraryaction', 'lib.ui.player', 'lib.ui.streamswindow', 'lib.ui.views',
)
_HUB = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.homewindow', 'lib.ui.hubwindow',
    'lib.ui.catalogpicker', 'lib.ui.detailwindow', 'lib.ui.mystuff', 'lib.ui.infowindow',
)
_GRID = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.gridwindow', 'lib.ui.mystuff',
)
_VIEWS = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.router', 'lib.ui.views',
    'lib.ui.addonsync', 'lib.ui.dependencies',
)


@pytest.fixture
def load_home():
    with contextlib.ExitStack() as stack:
        def _load(**kwargs):
            return stack.enter_context(install_kodi_stubs(reload=_HOME, **kwargs))
        yield _load


@pytest.fixture
def load_hub():
    with contextlib.ExitStack() as stack:
        def _load(**kwargs):
            return stack.enter_context(install_kodi_stubs(reload=_HUB, **kwargs))
        yield _load


@pytest.fixture
def load_grid():
    with contextlib.ExitStack() as stack:
        def _load(**kwargs):
            return stack.enter_context(install_kodi_stubs(reload=_GRID, **kwargs))
        yield _load


@pytest.fixture
def load_views():
    with contextlib.ExitStack() as stack:
        def _load(**kwargs):
            return stack.enter_context(install_kodi_stubs(reload=_VIEWS, **kwargs))
        yield _load


class _HomeStore:
    def __init__(self, addons, progress, auth=None):
        self._addons = addons
        self._progress = progress
        self._auth = auth

    def get_auth(self):
        return self._auth

    def get_addons(self):
        return list(self._addons)

    def get_enabled_addons(self):
        return list(self._addons)

    def get_progress_entries(self):
        return list(self._progress)


def test_home_open_paints_continue_library_and_the_movie_shelf(load_home, monkeypatch):
    """Opening Home fills Continue from progress, Library from the
    account, and the first movie catalog. The pull is not started:
    this store has no data directory, which is also what keeps the
    playback service out of the pull."""
    ctx = load_home()
    addons = [{'transportUrl': 'https://cine.example/manifest.json', 'manifest': {
        'name': 'Cine',
        'catalogs': [{'type': 'movie', 'id': 'top', 'name': 'Top'}],
    }}]
    progress = [{
        'type': 'series', 'id': 'tt1', 'video_id': 'tt1:1:3', 'name': 'Show',
        'poster': 'http://poster', 'position_ms': 724000, 'duration_ms': 3600000,
        'updated_at': '2020-01-02T00:00:00Z',
    }]
    library = [
        {'_id': 'tt%d' % i, 'name': 'Saved %d' % i, 'type': 'movie', 'poster': 'p', 'removed': False}
        for i in range(13)
    ]
    seen = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append(catalog.get('id'))
        return [{'id': 'm1', 'name': 'Dune', 'type': 'movie', 'poster': 'http://dune'}]

    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _HomeStore(addons, progress, {'authKey': 'k'}))
    monkeypatch.setattr(ctx.mystuff, '_fetch_library_entries', lambda _store: library)
    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    shelves = dict((action, list_id) for action, list_id, _label in ctx.homewindow._SHELVES)
    continue_ids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.CONTINUE_SHELF).items]
    library_ids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.LIBRARY_SHELF).items]
    movie_ids = [item.getProperty('sid') for item in win.getControl(shelves['movies']).items]
    assert continue_ids == ['tt1']
    assert library_ids == ['tt%d' % i for i in range(13)]
    assert movie_ids[0] == 'm1'
    assert seen == ['top']
    assert win.getControl(ctx.homewindow.HERO_TITLE).label


def test_movies_hub_decade_opens_the_sorted_coverflow(load_hub, monkeypatch):
    """The Year row is tiles. Selecting the 1990s fetches the years,
    sorts by moviedb popularity, and opens the existing coverflow.
    A picked title goes to the detail page."""
    ctx = load_hub()
    addons = [{'transportUrl': 'https://v3-cinemeta.strem.io/manifest.json', 'manifest': {
        'name': 'Cinemeta',
        'catalogs': [{
            'type': 'movie', 'id': 'year', 'name': 'Year',
            'extra': [{'name': 'genre', 'isRequired': True, 'options': ['1994', '1999', '1950']}],
        }],
    }}]
    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', lambda *a, **k: [])
    descs = ctx.hubwindow._descriptors(addons, frozenset({'movie'}))
    assert [item.getLabel() for item in descs[0]['posters']] == ['1990s']
    class _Client:
        def catalog_with_hints(self, transport, rtype, cid, extra=None):
            year = dict(extra or []).get('genre')
            if year == '1994':
                metas = [
                    {'id': 'obscure', 'name': 'Obscure', 'popularities': {'moviedb': 1.5}},
                    {'id': 'tt0111161', 'name': 'Shawshank', 'popularities': {'moviedb': 56.3}},
                ]
            else:
                metas = [{'id': 'tt0137523', 'name': 'Fight Club', 'popularities': {'moviedb': 40.0}}]
            return metas, {'hasMore': False}

    monkeypatch.setattr('lib.ui.dependencies.get_client', lambda: _Client())
    monkeypatch.setattr('lib.ui.catalogpages.get_page_cache', lambda: None)
    opened = {}

    def _showcase(metas, catalog_title=''):
        opened['metas'] = list(metas)
        opened['title'] = catalog_title
        return metas[0]

    monkeypatch.setattr(ctx.infowindow, 'open_showcase', _showcase)
    monkeypatch.setattr(
        ctx.detailwindow, 'open_detail',
        lambda stype, sid, **_k: opened.setdefault('detail', (stype, sid)) or True,
    )
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = descs
    ctx.hubwindow._paint_list(win, select=0)
    win.getControl(ctx.hubwindow.HUB_LIST).selectItem(0)

    win.onClick(ctx.hubwindow.HUB_LIST)

    assert [meta['name'] for meta in opened['metas'][:2]] == ['Shawshank', 'Fight Club']
    assert opened['title'] == 'Year'
    assert opened['detail'] == ('movie', 'tt0111161')


def test_library_screen_keeps_the_thirteenth_title(load_grid):
    """The Continue screen's library band is the whole account list.
    Twelve used to be where the row stopped."""
    ctx = load_grid()
    items = [
        {'band': ctx.mystuff.BAND_LIBRARY, 'id': 'tt%d' % i, 'name': 'Title %d' % i, 'type': 'movie'}
        for i in range(13)
    ]
    win = ctx.gridwindow.GridWindow('GridWindow.xml', '/addon/path', 'Default', '1080i')
    win.bands = [(ctx.mystuff.BAND_LIBRARY, items)]
    win.heading = 'CONTINUE'

    win.onInit()

    list_id = ctx.gridwindow.BAND_ROWS[ctx.mystuff.BAND_LIBRARY][0]
    labels = [item.getLabel() for item in win.getControl(list_id).items]
    assert labels[0] == 'Title 0'
    assert labels[12] == 'Title 12'
    assert len(labels) == 13


def test_continue_resume_stop_does_not_start_up_next_and_a_natural_end_does(load_home, monkeypatch):
    """Resume plays the saved stream at the saved offset. A user Stop
    returns without the next episode. Playing through joins Up next."""
    ctx = load_home()
    saved = {'url': 'https://cdn.example/ep.mp4', 'behaviorHints': {}}
    calls = []

    def choose(title, options):
        calls.append(('choose', title, list(options)))
        return 0

    def play_direct(stream, stype, sid, **kwargs):
        calls.append(('play', sid, kwargs.get('resume_offset_ms'), stream))
        return True

    waits = {'n': 0}

    def wait_end(*_a, **_k):
        waits['n'] += 1
        # First journey: the user stopped. Second: the file ended.
        return (True, waits['n'] > 1)

    binge = []
    monkeypatch.setattr(ctx.dialogs, 'choose', choose)
    monkeypatch.setattr(ctx.player, 'play_direct', play_direct)
    monkeypatch.setattr(ctx.streamswindow, '_wait_for_playback_end', wait_end)
    monkeypatch.setattr(ctx.streamswindow, '_try_binge_watch', lambda *a, **k: binge.append(a) or None)
    monkeypatch.setattr(ctx.uicommon, 'end_player_phase', lambda: calls.append('end'))
    monkeypatch.setattr(ctx.streamswindow, 'open_streams', lambda *a, **k: calls.append('streams'))
    monkeypatch.setattr(ctx.detailwindow, 'open_detail', lambda *a, **k: calls.append('detail'))
    monkeypatch.setattr(ctx.views, '_fetch_meta', lambda stype, sid, **k: {
        'id': sid, 'name': 'Show', 'type': stype,
        'videos': [
            {'id': 'tt1:1:8', 'season': 1, 'episode': 8},
            {'id': 'tt1:2:1', 'season': 2, 'episode': 1},
        ],
    })

    class _Store:
        def get_last_stream(self, *_a, **_k):
            return saved

    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _Store())
    import xbmcgui
    item = xbmcgui.ListItem('Show')
    item.setProperty('sid', 'tt1')
    item.setProperty('stype', 'series')
    item.setProperty('band', 'resume')
    item.setProperty('video_id', 'tt1:1:8')
    item.setProperty('position_ms', '724000')
    item.setProperty('duration_ms', '3600000')
    item.setProperty('hero_title', 'Show')
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)
    assert calls[0][0] == 'choose'
    assert calls[0][2][0].startswith('Resume ')
    assert calls[1][1] == 'tt1:1:8'
    assert calls[1][2] == 724000
    assert binge == []

    win.onClick(ctx.homewindow.CONTINUE_SHELF)
    assert binge and binge[0][0] == 'series'
    assert binge[0][4] == 'tt1:1:8'
    assert binge[0][1]['videos'][1]['id'] == 'tt1:2:1'


def test_up_next_crosses_a_season_stops_at_the_series_end_and_back_cancels(load_home, monkeypatch):
    """The chain uses the real next-episode walk. Season 1's last
    episode plays season 2's first. The last episode of the series
    does not invent another. Back on the card plays nothing."""
    ctx = load_home()
    sw = ctx.streamswindow
    meta = {'id': 'tt1', 'name': 'Show', 'videos': [
        {'id': 's1e8', 'season': 1, 'episode': 8, 'title': 'Finale'},
        {'id': 's2e1', 'season': 2, 'episode': 1, 'title': 'Premiere'},
    ]}
    streams = {
        's2e1': [{'name': '[RD+] Premiere 1080p', 'url': 'https://cdn.example/s2.mp4'}],
    }
    played = []

    from lib.stremio import streaminfo

    def fetch(_stype, sid):
        return [(streaminfo.parse_stream(item, addon_name='Addon'), item) for item in streams.get(sid, [])]

    def play(stream, _stype, sid, **kwargs):
        played.append((sid, kwargs.get('resume_offset_ms'), stream.get('url')))
        return True

    prompts = {'n': 0}

    def countdown(label, seconds, accept_on_timeout=True, alive=None, still_watching=False):
        prompts['n'] += 1
        prompts['label'] = label
        return True

    monkeypatch.setattr(sw, '_fetch_stream_pairs', fetch)
    monkeypatch.setattr(ctx.player, 'play_direct', play)
    monkeypatch.setattr(sw, '_binge_countdown', countdown)
    monkeypatch.setattr(sw, '_wait_for_playback_end', lambda *a, **k: (True, False))
    monkeypatch.setattr(sw, '_autoplay_limits', lambda: (30, 5, 3))

    assert sw._try_binge_watch('series', meta, '', {}, 's1e8', {}) is None
    assert played == [('s2e1', 0, 'https://cdn.example/s2.mp4')]
    assert 'Premiere' in prompts['label'] or 'S2E1' in prompts['label']

    played.clear()
    assert sw._try_binge_watch('series', {'id': 'tt1', 'videos': [
        {'id': 's2e1', 'season': 2, 'episode': 1},
    ]}, '', {}, 's2e1', {}) is None
    assert played == []

    def cancel(*_a, **_k):
        return None

    monkeypatch.setattr(sw, '_binge_countdown', cancel)
    played.clear()
    assert sw._try_binge_watch('series', meta, '', {}, 's1e8', {}) is None
    assert played == []


def test_stop_return_ignores_a_second_home_while_the_ui_is_alive(load_home):
    """Playback stopping makes Kodi re-run the plugin root. A fresh
    heartbeat means a screen is already up, so that run must not open
    another Home. A stale stamp must not lock the user out."""
    import time

    ctx = load_home()
    import xbmcgui
    home = xbmcgui.Window(10000)
    home.setProperty(ctx.uicommon.HEARTBEAT_PROPERTY, 'tok|%.3f' % time.time())
    assert ctx.uicommon.is_duplicate_launch() is True
    home.setProperty(ctx.uicommon.HEARTBEAT_PROPERTY, 'tok|%.3f' % (time.time() - 30))
    assert ctx.uicommon.is_duplicate_launch() is False


class _Clock(datetime.datetime):
    moment = datetime.datetime(2026, 1, 1, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        current = cls.moment
        if tz is not None and current.tzinfo is None:
            return current.replace(tzinfo=tz)
        return current


def test_sync_pushes_at_start_again_at_sixty_seconds_and_on_stop(monkeypatch):
    """The opening sample goes up immediately. A tick inside the minute
    does not. The tick at 60 seconds does. Stop always sends the last
    position, even inside that minute."""
    import lib.service_runner as service_runner

    monkeypatch.setattr(service_runner.datetime, 'datetime', _Clock)
    store = _FakeProgressStore(now_playing=dict(_CONTEXT), auth={'authKey': 'k'})
    api = _FakeProgressAPI()
    with _progress_player_env(store, api, sync_enabled=True) as (env, player, _logs):
        env.player_is_playing = True
        env.player_get_time = 1.0
        env.player_get_total_time = 1000.0
        player.onAVStarted()
        assert len(api.datastore_put_calls) == 1

        _Clock.moment = _Clock.moment + datetime.timedelta(seconds=30)
        env.player_get_time = 30.0
        player.sample_if_playing()
        assert len(api.datastore_put_calls) == 1

        _Clock.moment = _Clock.moment + datetime.timedelta(seconds=30)
        env.player_get_time = 60.0
        player.sample_if_playing()
        assert len(api.datastore_put_calls) == 2

        env.player_is_playing = False
        player.onPlayBackStopped()
        assert len(api.datastore_put_calls) == 3
    positions = [call[2][0]['state']['timeOffset'] for call in api.datastore_put_calls]
    assert positions[0] > 0
    assert positions[-1] == 60000


def test_addon_pull_merges_a_web_addon_then_the_push_sends_both(load_views, tmp_path, monkeypatch):
    """Disk store, real union, real sync action. The account has an
    addon this install does not. Sync pulls it in before the set, so
    the push cannot delete it. A later pull that fails does not push."""
    from lib.store import Store
    from lib.stremio.api import ApiError

    ctx = load_views()
    store = Store(str(tmp_path))
    local = {'transportUrl': 'https://local.example/manifest.json', 'manifest': {'id': 'org.local'}}
    web = {'transportUrl': 'https://web.example/manifest.json', 'manifest': {'id': 'org.web'}}
    store.set_auth({'authKey': 'abc'})
    store.update_addons(lambda _current: [local])
    pushes = []

    class _API:
        def __init__(self):
            self.fail = False

        def addon_collection_state(self, _key, update=True):
            assert update is True
            if self.fail:
                raise ApiError('timeout')
            return [local, web], 'stamp-1'

        def addon_collection_get(self, key, update=True):
            addons, _stamp = self.addon_collection_state(key, update=update)
            return addons

        def addon_collection_set(self, _key, addons):
            pushes.append(list(addons))

    api = _API()
    monkeypatch.setattr(ctx.views, 'get_store', lambda: store)
    monkeypatch.setattr(ctx.views, 'StremioAPI', lambda: api)
    monkeypatch.setattr(ctx.views, 'get_client', lambda: object())
    monkeypatch.setattr(ctx.views, '_refresh_addon_manifests', lambda *_a, **_k: None)

    ctx.views.sync_addons_now()

    urls = [item.get('transportUrl') for item in store.get_addons()]
    assert 'https://web.example/manifest.json' in urls
    assert 'https://local.example/manifest.json' in urls
    assert pushes and any(item.get('manifest', {}).get('id') == 'org.web' for item in pushes[-1])

    api.fail = True
    before = len(pushes)
    ctx.views.sync_addons_now()
    assert len(pushes) == before
    assert store.get_auth() == {'authKey': 'abc'}
