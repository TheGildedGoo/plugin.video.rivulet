# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The Settings pairing dialog, against the Kodi fakes."""
import socket
import urllib.error
import urllib.request

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


def _load(kodi_stubs):
    return kodi_stubs(reload=(
        'lib.ui.compat',
        'lib.ui.uicommon',
        'lib.ui.dialogs',
        'lib.ui.pairwindow',
    ))


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


def test_a_phone_post_saves_the_setting_without_logging_the_key(kodi_stubs, monkeypatch):
    _allow_localhost(monkeypatch)
    ctx = _load(kodi_stubs)
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
            url = windows[0].getControl(ctx.pairwindow.PAIR_URL).label
            status, page = _post(url)
            assert status == 200
            assert _SECRET not in page
            assert windows[0].getControl(ctx.pairwindow.PAIR_CODE).label in url
        return False

    ctx.pairwindow.pair_setting(
        'ratings_omdb_key', 'OMDb', sleep=sleep, ipv4='127.0.0.1', bind_host='127.0.0.1',
    )

    assert ctx.compat.ADDON.getSetting('ratings_omdb_key') == _SECRET
    assert _SECRET not in _logged(ctx)
    assert _SECRET not in _notes(ctx)
    assert windows[0].closed is True
    assert 'STR30460' in _notes(ctx)


def test_backing_out_does_not_save(kodi_stubs, monkeypatch):
    ctx = _load(kodi_stubs)
    windows = []
    real_open = ctx.uicommon.open_window
    monkeypatch.setattr(ctx.uicommon, 'open_window', lambda *a, **k: windows.append(real_open(*a, **k)) or windows[-1])

    def sleep(_seconds):
        windows[0].cancel()
        return False

    ctx.pairwindow.pair_setting(
        'ratings_omdb_key', 'OMDb', sleep=sleep, ipv4='127.0.0.1', bind_host='127.0.0.1',
    )
    assert ctx.compat.ADDON.getSetting('ratings_omdb_key') == ''
    assert 'STR30460' not in _notes(ctx)
    assert 'STR30462' not in _notes(ctx)


def test_an_expired_code_notifies_without_a_key(kodi_stubs):
    ctx = _load(kodi_stubs)
    ctx.pairwindow.pair_setting(
        'ratings_omdb_key', 'OMDb', sleep=lambda _s: False, ipv4='127.0.0.1',
        bind_host='127.0.0.1', timeout=0,
    )
    assert ctx.compat.ADDON.getSetting('ratings_omdb_key') == ''
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
