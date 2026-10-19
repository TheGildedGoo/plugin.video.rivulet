"""lib/ui/trailer.py: which YouTube id a meta's trailer is, and where it plays from."""
import pytest

from tests.kodistubs import install_kodi_stubs


@pytest.fixture
def trailer():
    with install_kodi_stubs(reload=('lib.ui.compat', 'lib.ui.trailer')) as ctx:
        import lib.ui.trailer as module
        ctx.trailer = module
        yield ctx


def test_trailer_streams_win_over_the_older_field(trailer):
    meta = {
        'trailerStreams': [{'title': 'Official', 'ytId': 'abcdefghijk'}],
        'trailers': [{'source': 'zzzzzzzzzzz', 'type': 'Trailer'}],
    }
    assert trailer.trailer.trailer_id(meta) == 'abcdefghijk'


def test_a_trailer_is_preferred_over_a_clip(trailer):
    meta = {'trailers': [
        {'source': 'clip0000000', 'type': 'Clip'},
        {'source': 'trailer0000', 'type': 'Trailer'},
    ]}
    assert trailer.trailer.trailer_id(meta) == 'trailer0000'


@pytest.mark.parametrize('meta', [None, {}, {'trailers': [{'source': 'not an id!'}]}, {'trailerStreams': ['x']}])
def test_no_usable_trailer(trailer, meta):
    assert trailer.trailer.trailer_id(meta) == ''


def test_a_server_stream_that_answers_goes_first_then_the_youtube_addon(trailer, monkeypatch):
    monkeypatch.setattr(trailer.trailer, '_youtube_addon_url', lambda yt: 'plugin://plugin.video.youtube/play/?video_id=%s' % yt)
    monkeypatch.setattr(trailer.trailer, '_server_url', lambda yt: 'http://127.0.0.1:11470/yt/%s' % yt)
    assert list(trailer.trailer.trailer_urls('abcdefghijk')) == [
        'http://127.0.0.1:11470/yt/abcdefghijk',
        'plugin://plugin.video.youtube/play/?video_id=abcdefghijk',
    ]
    # A probe already made is not made again.
    assert list(trailer.trailer.trailer_urls('abcdefghijk', '')) == [
        'plugin://plugin.video.youtube/play/?video_id=abcdefghijk',
    ]
    monkeypatch.setattr(trailer.trailer, '_youtube_addon_url', lambda yt: '')
    assert trailer.trailer.trailer_url('abcdefghijk') == 'http://127.0.0.1:11470/yt/abcdefghijk'


def test_a_server_url_that_does_not_play_is_not_used(trailer, monkeypatch):
    import lib.ui.player as player

    class _Server:
        def is_available(self):
            return True

        def resolve_stream(self, stream):
            return 'http://127.0.0.1:11470/yt/%s' % stream['ytId']

    monkeypatch.setattr(player, '_server_client', lambda: _Server())
    monkeypatch.setattr(trailer.trailer, '_plays', lambda url: False)
    assert trailer.trailer._server_url('abcdefghijk') == ''
    monkeypatch.setattr(trailer.trailer, '_plays', lambda url: True)
    assert trailer.trailer._server_url('abcdefghijk').endswith('/yt/abcdefghijk')


def test_no_trailer_tells_the_viewer_and_plays_nothing(trailer, monkeypatch):
    monkeypatch.setattr(trailer.trailer, '_full_meta', lambda meta, stype, sid: meta)
    assert trailer.trailer.play_trailer({'name': 'X'}) is False
    assert trailer.env.notifications[-1][1] == 'STR30497'


def test_nowhere_to_play_it_offers_the_youtube_addon(trailer, monkeypatch):
    monkeypatch.setattr(trailer.trailer, '_full_meta', lambda meta, stype, sid: meta)
    monkeypatch.setattr(trailer.trailer, '_server_url', lambda yt: '')
    monkeypatch.setattr(trailer.trailer, '_youtube_addon_url', lambda yt: '')
    import lib.ui.dialogs as dialogs
    asked = []
    monkeypatch.setattr(dialogs, 'confirm', lambda heading, body, yes, no: asked.append(body) or True)
    assert trailer.trailer.play_trailer({'trailers': [{'source': 'abcdefghijk'}]}) is False
    assert asked == ['STR30504']
    assert 'InstallAddon(plugin.video.youtube)' in trailer.env.executed_builtins


def _routes(trailer, monkeypatch, outcomes):
    monkeypatch.setattr(trailer.trailer, '_full_meta', lambda meta, stype, sid: meta)
    monkeypatch.setattr(trailer.trailer, '_server_url', lambda yt: 'http://127.0.0.1:11470/yt/%s' % yt)
    monkeypatch.setattr(trailer.trailer, '_youtube_addon_url', lambda yt: 'plugin://plugin.video.youtube/play/?video_id=%s' % yt)
    tried = []
    watched = []
    queue = list(outcomes)
    monkeypatch.setattr(trailer.trailer, '_start', lambda url, item, heading: tried.append(url) or queue.pop(0))
    monkeypatch.setattr(trailer.trailer, '_watch', lambda: watched.append(True))
    return tried, watched


_META = {'name': 'Dune', 'trailers': [{'source': 'abcdefghijk'}]}


def test_a_stalled_route_is_dropped_for_the_next(trailer, monkeypatch):
    tried, watched = _routes(trailer, monkeypatch, ['stalled', 'rolling'])
    assert trailer.trailer.play_trailer(_META) is True
    assert [url.split(':')[0] for url in tried] == ['http', 'plugin']
    assert watched == [True]


def test_no_route_starting_says_so_and_keeps_the_screens(trailer, monkeypatch):
    tried, watched = _routes(trailer, monkeypatch, ['stalled', 'stalled'])
    assert trailer.trailer.play_trailer(_META) is False
    assert len(tried) == 2
    assert watched == []
    assert trailer.env.notifications[-1][1] == 'STR30510'


def test_back_on_the_spinner_stops_trying(trailer, monkeypatch):
    tried, watched = _routes(trailer, monkeypatch, ['cancelled', 'rolling'])
    assert trailer.trailer.play_trailer(_META) is False
    assert len(tried) == 1
    assert watched == []


class _Player:
    def __init__(self, clock):
        self._clock = list(clock)
        self.stopped = False
        self.playing = True

    def isPlayingVideo(self):
        return bool(self._clock)

    def isPlaying(self):
        return self.playing and not self.stopped

    def getTime(self):
        return self._clock.pop(0) if len(self._clock) > 1 else self._clock[0]

    def stop(self):
        self.stopped = True


class _Monitor:
    def waitForAbort(self, seconds):
        return False

    def abortRequested(self):
        return False


def test_rolling_means_the_clock_moved(trailer):
    player = _Player([0.0, 0.0, 0.1, 0.6])
    assert trailer.trailer._wait_rolling(player, _Monitor(), timeout=5, tick=0) == 'rolling'


def test_a_clock_stuck_at_zero_is_a_stall(trailer):
    player = _Player([0.0])
    assert trailer.trailer._wait_rolling(player, _Monitor(), timeout=0.05, tick=0) == 'stalled'


def test_the_start_wait_runs_on_the_monotonic_clock(trailer, monkeypatch):
    """A wall clock that jumps back (NTP, a time zone change) must not
    hold the wait open: the deadline is measured on time.monotonic()."""
    import time

    ticks = iter(range(100))
    monkeypatch.setattr(time, 'monotonic', lambda: float(next(ticks)))
    monkeypatch.setattr(time, 'time', lambda: 0.0)  # frozen wall clock
    player = _Player([0.0])
    assert trailer.trailer._wait_rolling(player, _Monitor(), timeout=5, tick=0) == 'stalled'


def test_a_stalled_start_stops_the_player(trailer, monkeypatch):
    import xbmc

    player = _Player([0.0])
    monkeypatch.setattr(xbmc, 'Player', lambda: player, raising=False)
    played = []
    player.play = lambda url, item: played.append(url)
    monkeypatch.setattr(trailer.trailer, '_wait_rolling', lambda player, monitor: 'stalled')
    assert trailer.trailer._start('http://x/yt/abc', object(), 'Trailer') == 'stalled'
    assert played == ['http://x/yt/abc']
    assert player.stopped is True


def test_watching_closes_the_screens_and_goes_full_screen(trailer, monkeypatch):
    import lib.ui.streamswindow as streamswindow
    import lib.ui.uicommon as uicommon

    calls = []
    monkeypatch.setattr(uicommon, 'close_windows_for_playback', lambda: calls.append('close'))
    monkeypatch.setattr(uicommon, 'end_player_phase', lambda: calls.append('end'))
    monkeypatch.setattr(streamswindow, '_wait_for_playback_end', lambda start_timeout: calls.append('wait'))
    trailer.trailer._watch()
    assert calls == ['close', 'wait', 'end']
    assert 'ActivateWindow(fullscreenvideo)' in trailer.env.executed_builtins


@pytest.fixture
def menu():
    with install_kodi_stubs(reload=('lib.ui.compat', 'lib.ui.dialogs', 'lib.ui.libraryaction', 'lib.ui.trailer')) as ctx:
        import lib.ui.libraryaction as libraryaction
        ctx.libraryaction = libraryaction
        yield ctx


class _Store:
    def __init__(self, auth):
        self._auth = auth

    def get_auth(self):
        return self._auth


def _wire(ctx, monkeypatch, auth, pick, record=None):
    import lib.ui.dependencies as dependencies
    import lib.ui.dialogs as dialogs
    import lib.ui.trailer as trailer
    shown = []
    played = []
    monkeypatch.setattr(dependencies, 'get_store', lambda: _Store(auth))
    monkeypatch.setattr(dialogs, 'choose', lambda heading, rows: shown.append(rows) or pick)
    monkeypatch.setattr(trailer, 'play_trailer', lambda meta, stype='', sid='': played.append((stype, sid)))
    monkeypatch.setattr(ctx.libraryaction, '_lookup', lambda auth, sid: (record, True))
    return shown, played


def test_poster_menu_signed_out_still_offers_the_trailer(menu, monkeypatch):
    shown, played = _wire(menu, monkeypatch, None, 0)
    assert menu.libraryaction.poster_menu({'id': 'tt1', 'type': 'movie', 'name': 'Dune'}) is None
    assert shown == [['STR30499']]
    assert played == [('movie', 'tt1')]


def test_poster_menu_signed_in_puts_the_library_row_first(menu, monkeypatch):
    shown, played = _wire(menu, monkeypatch, {'authKey': 'k'}, 1)
    menu.libraryaction.poster_menu({'id': 'tt1', 'type': 'movie', 'name': 'Dune'})
    assert shown == [['STR30293', 'STR30499']]
    assert played == [('movie', 'tt1')]


def test_poster_menu_library_row_writes(menu, monkeypatch):
    _wire(menu, monkeypatch, {'authKey': 'k'}, 0)
    writes = []
    monkeypatch.setattr(menu.libraryaction, '_write', lambda auth, meta, in_library: writes.append(in_library) or 'added')
    assert menu.libraryaction.poster_menu({'id': 'tt1', 'type': 'movie', 'name': 'Dune'}) == 'added'
    assert writes == [False]


def test_poster_menu_backed_out_does_nothing(menu, monkeypatch):
    shown, played = _wire(menu, monkeypatch, {'authKey': 'k'}, -1)
    assert menu.libraryaction.poster_menu({'id': 'tt1', 'name': 'Dune'}) is None
    assert played == []
