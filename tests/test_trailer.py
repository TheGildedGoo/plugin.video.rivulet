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


def test_the_youtube_addon_is_preferred_then_the_server(trailer, monkeypatch):
    monkeypatch.setattr(trailer.trailer, '_youtube_addon_url', lambda yt: 'plugin://plugin.video.youtube/play/?video_id=%s' % yt)
    monkeypatch.setattr(trailer.trailer, '_server_url', lambda yt: 'http://127.0.0.1:11470/yt/%s' % yt)
    assert trailer.trailer.trailer_url('abcdefghijk').startswith('plugin://plugin.video.youtube/')

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
    monkeypatch.setattr(trailer.trailer, 'trailer_url', lambda yt: '')
    import lib.ui.dialogs as dialogs
    asked = []
    monkeypatch.setattr(dialogs, 'confirm', lambda heading, body, yes, no: asked.append(body) or True)
    assert trailer.trailer.play_trailer({'trailers': [{'source': 'abcdefghijk'}]}) is False
    assert asked == ['STR30504']
    assert 'InstallAddon(plugin.video.youtube)' in trailer.env.executed_builtins


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
