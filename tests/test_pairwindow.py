# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The Settings pairing dialog, against the Kodi fakes."""
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

_SECRET = 'super-secret-omdb-key'
_REAL_CONNECT = socket.socket.connect
_REAL_CREATE = socket.create_connection


def _allow_localhost(monkeypatch):
    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else ''
        if host != '127.0.0.1':
            raise AssertionError('real network access attempted in a unit test')
        return _REAL_CONNECT(self, address)

    def create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else ''
        if host != '127.0.0.1':
            raise AssertionError('real network access attempted in a unit test')
        return _REAL_CREATE(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket, 'create_connection', create_connection)


def _load(kodi_stubs, **config):
    return kodi_stubs(reload=(
        'lib.ui.compat',
        'lib.ui.uicommon',
        'lib.ui.dialogs',
        'lib.ui.pairwindow',
    ), **config)


def _post(url):
    req = urllib.request.Request(url, data=('key=%s' % _SECRET).encode('utf-8'), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8')


def _logged(ctx):
    return ' '.join(msg for msg, _level in ctx.env.log_calls)


def _notes(ctx):
    return ' '.join(msg for _heading, msg, _icon, _time in ctx.env.notifications)


@pytest.mark.parametrize('setting_id,url,line_id', [
    ('ratings_omdb_key', 'https://www.omdbapi.com/apikey.aspx', 30541),
    ('ratings_mdblist_key', 'https://mdblist.com/preferences/', 30542),
])
def test_a_phone_post_saves_the_setting_without_logging_the_key(
        kodi_stubs, monkeypatch, setting_id, url, line_id):
    _allow_localhost(monkeypatch)
    # Use the shipped English strings, so the real hint and link are
    # exercised rather than the fake's STR<id> placeholders.
    import re
    po = (Path(__file__).resolve().parents[1] / 'resources/language/'
          'resource.language.en_gb/strings.po').read_text(encoding='utf-8')
    localized = {int(sid): text for sid, text in
                 re.findall(r'msgctxt "#(\d+)"\nmsgid "([^"\n]*)"', po)}
    ctx = _load(kodi_stubs, localized=localized)
    ctx.compat.ADDON.setSetting(setting_id, 'old-key')
    windows = []
    real_open = ctx.uicommon.open_window

    def open_window(*args, **kwargs):
        window = real_open(*args, **kwargs)
        windows.append(window)
        return window

    monkeypatch.setattr(ctx.uicommon, 'open_window', open_window)
    posted = {'done': False}

    def sleep(_seconds):
        if not posted['done']:
            posted['done'] = True
            page_url = windows[0].getControl(ctx.pairwindow.PAIR_URL).label
            hint = windows[0].getControl(ctx.pairwindow.PAIR_HINT).text
            assert hint == localized[30459] + '\n\n' + localized[line_id]
            assert url in hint
            with urllib.request.urlopen(page_url, timeout=2) as resp:
                form = resp.read().decode('utf-8')
            assert '<a href="%s" target="_blank" rel="noopener noreferrer">' % url in form
            assert localized[line_id] in form
            assert form.index('<a href=') < form.index('<input name="key"')
            assert 'old-key' not in form
            status, page = _post(page_url)
            assert status == 200
            assert _SECRET not in page
            assert windows[0].getControl(ctx.pairwindow.PAIR_CODE).label in page_url
        return False

    ctx.pairwindow.pair_setting(
        setting_id, 'Key', sleep=sleep, ipv4='127.0.0.1', bind_host='127.0.0.1',
    )

    assert ctx.compat.ADDON.getSetting(setting_id) == _SECRET
    other = 'ratings_mdblist_key' if setting_id == 'ratings_omdb_key' else 'ratings_omdb_key'
    assert ctx.compat.ADDON.getSetting(other) == ''
    assert _SECRET not in _logged(ctx)
    assert _SECRET not in _notes(ctx)
    assert windows[0].closed is True
    assert localized[30460] in _notes(ctx)


@pytest.mark.parametrize('setting_id', ['ratings_omdb_key', 'ratings_mdblist_key'])
def test_backing_out_does_not_save(kodi_stubs, monkeypatch, setting_id):
    ctx = _load(kodi_stubs)
    ctx.compat.ADDON.setSetting(setting_id, 'old-key')
    windows = []
    real_open = ctx.uicommon.open_window
    monkeypatch.setattr(ctx.uicommon, 'open_window', lambda *a, **k: windows.append(real_open(*a, **k)) or windows[-1])

    def sleep(_seconds):
        windows[0].cancel()
        return False

    ctx.pairwindow.pair_setting(
        setting_id, 'Key', sleep=sleep, ipv4='127.0.0.1', bind_host='127.0.0.1',
    )
    assert ctx.compat.ADDON.getSetting(setting_id) == 'old-key'
    assert 'STR30460' not in _notes(ctx)
    assert 'STR30462' not in _notes(ctx)


@pytest.mark.parametrize('setting_id', ['ratings_omdb_key', 'ratings_mdblist_key'])
def test_an_expired_code_notifies_without_a_key(kodi_stubs, setting_id):
    ctx = _load(kodi_stubs)
    ctx.compat.ADDON.setSetting(setting_id, 'old-key')
    ctx.pairwindow.pair_setting(
        setting_id, 'Key', sleep=lambda _s: False, ipv4='127.0.0.1',
        bind_host='127.0.0.1', timeout=0,
    )
    assert ctx.compat.ADDON.getSetting(setting_id) == 'old-key'
    assert 'STR30462' in _notes(ctx)


def test_a_save_error_logs_the_class_not_the_key(kodi_stubs, monkeypatch):
    _allow_localhost(monkeypatch)
    ctx = _load(kodi_stubs)
    windows = []
    real_open = ctx.uicommon.open_window
    monkeypatch.setattr(ctx.uicommon, 'open_window', lambda *a, **k: windows.append(real_open(*a, **k)) or windows[-1])

    def boom(_setting_id, value):
        raise RuntimeError(value)

    monkeypatch.setattr(ctx.compat.ADDON, 'setSetting', boom)

    def sleep(_seconds):
        _post(windows[0].getControl(ctx.pairwindow.PAIR_URL).label)
        return False

    ctx.pairwindow.pair_setting(
        'ratings_omdb_key', 'OMDb', sleep=sleep, ipv4='127.0.0.1', bind_host='127.0.0.1',
    )
    assert _SECRET not in _logged(ctx)
    assert _SECRET not in _notes(ctx)
    assert 'RuntimeError' in _logged(ctx)
    assert 'STR30469' in _notes(ctx)


def test_the_picker_hands_the_chosen_setting_to_pair(kodi_stubs, monkeypatch):
    ctx = _load(kodi_stubs)
    monkeypatch.setattr(ctx.dialogs, 'choose', lambda _heading, _rows: 1)
    seen = []
    monkeypatch.setattr(ctx.pairwindow, 'pair_setting', lambda setting_id, label: seen.append((setting_id, label)))
    ctx.pairwindow.open_pair_picker()
    assert seen == [('ratings_mdblist_key', 'STR30454')]


def test_no_network_notifies_and_does_not_save(kodi_stubs):
    ctx = _load(kodi_stubs)
    ctx.pairwindow.pair_setting('ratings_omdb_key', 'OMDb', ipv4='')
    assert ctx.compat.ADDON.getSetting('ratings_omdb_key') == ''
    assert 'STR30461' in _notes(ctx)


def test_pair_setting_cannot_write_an_arbitrary_setting(kodi_stubs, monkeypatch):
    ctx = _load(kodi_stubs)
    ctx.compat.ADDON.setSetting('server_url', 'existing-server')
    monkeypatch.setattr(ctx.pairwindow, 'pair_value', lambda *a, **k: pytest.fail('opened pairing'))
    ctx.pairwindow.pair_setting('server_url', 'Server')
    assert ctx.compat.ADDON.getSetting('server_url') == 'existing-server'


# ---------------------------------------------------------------------------
# Phone input for an addon link, a search, and Stremio's code sign-in.
# ---------------------------------------------------------------------------


def _load_with(kodi_stubs, **config):
    return kodi_stubs(reload=(
        'lib.ui.compat',
        'lib.ui.uicommon',
        'lib.ui.dialogs',
        'lib.ui.pairwindow',
    ), **config)


def test_an_addon_link_can_still_be_typed(kodi_stubs, monkeypatch):
    ctx = _load_with(kodi_stubs, dialog_inputs=['https://a.example/manifest.json'])
    monkeypatch.setattr(ctx.dialogs, 'choose', lambda _heading, _rows: 1)
    assert ctx.pairwindow.ask_addon_url('Install addon') == 'https://a.example/manifest.json'
    assert ctx.env.dialog_input_prompts == ['Install addon']


def test_backing_out_of_the_link_chooser_asks_nothing(kodi_stubs, monkeypatch):
    ctx = _load_with(kodi_stubs)
    monkeypatch.setattr(ctx.dialogs, 'choose', lambda _heading, _rows: -1)
    monkeypatch.setattr(ctx.pairwindow, 'pair_value', lambda *a, **k: 'https://never')
    assert ctx.pairwindow.ask_addon_url('Install addon') == ''
    assert ctx.env.dialog_input_prompts == []


def test_an_addon_link_from_the_phone_links_its_configure_page(kodi_stubs, monkeypatch):
    ctx = _load_with(kodi_stubs)
    chosen = []
    monkeypatch.setattr(ctx.dialogs, 'choose', lambda heading, rows: chosen.append((heading, rows)) or 0)
    asked = []

    def fake_pair_value(label, prompt=None, **kwargs):
        asked.append((label, prompt, kwargs))
        return 'https://cfg.example/manifest.json?token=x'

    monkeypatch.setattr(ctx.pairwindow, 'pair_value', fake_pair_value)

    url = ctx.pairwindow.ask_addon_url(
        'Long prompt', configure_url='https://cfg.example/configure', title='Torrentio',
    )

    assert url == 'https://cfg.example/manifest.json?token=x'
    assert chosen == [('Torrentio', ['STR30474', 'STR30475'])]
    label, prompt, kwargs = asked[0]
    assert (label, prompt) == ('Torrentio', 'STR30476')
    assert kwargs['cleaner'] is ctx.pairwindow.clean_url
    assert kwargs['max_length'] == ctx.pairwindow.MAX_URL_LENGTH
    assert kwargs['messages'] == {
        'empty': 'STR30478', 'long': 'STR30479',
        'link': 'https://cfg.example/configure', 'link_label': 'STR30477',
    }
    assert ctx.env.dialog_input_prompts == []


def test_a_phone_search_is_text_with_its_own_messages(kodi_stubs, monkeypatch):
    ctx = _load_with(kodi_stubs)
    asked = []
    monkeypatch.setattr(
        ctx.pairwindow, 'pair_value',
        lambda label, prompt=None, **kwargs: asked.append((label, prompt, kwargs)) or 'dune',
    )
    assert ctx.pairwindow.phone_search() == 'dune'
    label, prompt, kwargs = asked[0]
    assert (label, prompt) == ('STR30001', 'STR30485')
    assert kwargs['cleaner'] is ctx.pairwindow.clean_text
    assert kwargs['messages'] == {'empty': 'STR30486', 'long': 'STR30487'}


def test_a_link_post_reaches_the_caller_through_the_live_page(kodi_stubs, monkeypatch):
    """The real server, bound to 127.0.0.1: a long configured link fits."""
    _allow_localhost(monkeypatch)
    ctx = _load_with(kodi_stubs)
    windows = []
    real_open = ctx.uicommon.open_window
    monkeypatch.setattr(ctx.uicommon, 'open_window', lambda *a, **k: windows.append(real_open(*a, **k)) or windows[-1])
    link = 'https://cfg.example/' + 'c' * 1800 + '/manifest.json'
    posted = {'done': False}

    def sleep(_seconds):
        if not posted['done']:
            posted['done'] = True
            url = windows[0].getControl(ctx.pairwindow.PAIR_URL).label
            body = urllib.parse.urlencode({'key': link}).encode('utf-8')
            req = urllib.request.Request(url, data=body, method='POST')
            with urllib.request.urlopen(req, timeout=2) as resp:
                assert resp.status == 200
        return False

    value = ctx.pairwindow.pair_value(
        'Torrentio', 'prompt', cleaner=ctx.pairwindow.clean_url,
        max_length=ctx.pairwindow.MAX_URL_LENGTH, sleep=sleep,
        ipv4='127.0.0.1', bind_host='127.0.0.1',
    )
    assert value == link
    assert link not in _logged(ctx)


class _FakeApi:
    def __init__(self, user=None, exc=None):
        self.user = user
        self.exc = exc
        self.keys = []

    def get_user(self, auth_key):
        self.keys.append(auth_key)
        if self.exc is not None:
            raise self.exc
        return self.user


def _link_stubs(monkeypatch, ctx, answers, created=('WUS8', 'https://link.stremio.com/WUS8')):
    import lib.stremio.linklogin as linklogin

    reads = []

    def create_code():
        if isinstance(created, Exception):
            raise created
        return created

    def read_auth_key(code):
        reads.append(code)
        answer = answers.pop(0) if answers else None
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(linklogin, 'create_code', create_code)
    monkeypatch.setattr(linklogin, 'read_auth_key', read_auth_key)
    monkeypatch.setattr(ctx.pairwindow, '_LINK_POLL_SECONDS', 0)
    windows = []
    real_open = ctx.uicommon.open_window
    monkeypatch.setattr(ctx.uicommon, 'open_window', lambda *a, **k: windows.append(real_open(*a, **k)) or windows[-1])
    return reads, windows


def test_link_sign_in_waits_for_approval_then_returns_the_account(kodi_stubs, monkeypatch):
    from lib.stremio.linklogin import LinkError

    ctx = _load_with(kodi_stubs)
    reads, windows = _link_stubs(monkeypatch, ctx, [None, LinkError('blip'), 'auth-key-1'])
    api = _FakeApi(user={'email': 'a@b.com'})

    result = ctx.pairwindow.link_sign_in(api=api, sleep=lambda _s: False)

    assert result == {'authKey': 'auth-key-1', 'user': {'email': 'a@b.com'}}
    assert reads == ['WUS8', 'WUS8', 'WUS8']
    assert api.keys == ['auth-key-1']
    window = windows[0]
    assert window.getControl(ctx.pairwindow.PAIR_HEADING).label == 'STR30480'
    assert window.getControl(ctx.pairwindow.PAIR_CODE).label == 'WUS8'
    assert window.getControl(ctx.pairwindow.PAIR_URL).label == 'https://link.stremio.com/WUS8'
    assert window.closed is True
    assert 'auth-key-1' not in _logged(ctx)
    assert ctx.env.notifications == []


def test_link_sign_in_back_returns_nothing(kodi_stubs, monkeypatch):
    ctx = _load_with(kodi_stubs)
    _reads, windows = _link_stubs(monkeypatch, ctx, [])

    def sleep(_seconds):
        windows[0].cancel()
        return False

    assert ctx.pairwindow.link_sign_in(api=_FakeApi(), sleep=sleep) is None
    assert windows[0].closed is True
    assert ctx.env.notifications == []


def test_link_sign_in_times_out_with_a_toast(kodi_stubs, monkeypatch):
    ctx = _load_with(kodi_stubs)
    _link_stubs(monkeypatch, ctx, [])
    assert ctx.pairwindow.link_sign_in(api=_FakeApi(), sleep=lambda _s: False, timeout=0) is None
    assert 'STR30462' in _notes(ctx)


def test_link_sign_in_without_the_service_says_sign_in_failed(kodi_stubs, monkeypatch):
    from lib.stremio.linklogin import LinkError

    ctx = _load_with(kodi_stubs)
    _reads, windows = _link_stubs(monkeypatch, ctx, [], created=LinkError('ConnectionError'))
    assert ctx.pairwindow.link_sign_in(api=_FakeApi(), sleep=lambda _s: False) is None
    assert windows == []
    assert 'STR30023' in _notes(ctx)


def test_link_sign_in_keeps_the_key_when_the_account_lookup_fails(kodi_stubs, monkeypatch):
    from lib.stremio.api import ApiError

    ctx = _load_with(kodi_stubs)
    _link_stubs(monkeypatch, ctx, ['auth-key-2'])
    result = ctx.pairwindow.link_sign_in(api=_FakeApi(exc=ApiError('nope')), sleep=lambda _s: False)
    assert result == {'authKey': 'auth-key-2', 'user': {}}
    assert 'auth-key-2' not in _logged(ctx)
