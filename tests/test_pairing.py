# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The phone pairing page. No Kodi. The live check binds 127.0.0.1 only."""
import contextlib
import io
import socket
import struct
import urllib.error
import urllib.request

from lib.pairing import (
    MAX_FAILURES,
    MAX_KEY_LENGTH,
    TTL_SECONDS,
    PairServer,
    PairSession,
    clean_key,
    local_ipv4,
    new_code,
    respond,
    write_qr_bmp,
)
from lib.qrcodegen import QrCode

_SECRET = 'SUPERSECRETKEY'
_STRINGS = {
    'title': 'OMDb',
    'prompt': 'Paste the key',
    'save': 'Save',
    'saved': 'Saved. You can close this page.',
    'bad': 'That code does not match.',
    'empty': 'Enter a key.',
    'used': 'Already saved.',
    'expired': 'That code expired.',
    'long': 'That key is too long.',
}

# Captured before the suite's socket guard replaces them.
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


def _request(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8')


def test_code_is_short_and_unambiguous():
    # The phone-page string says the code works for 3 minutes.
    assert TTL_SECONDS == 180
    code = new_code()
    assert len(code) == 6
    assert set(code) <= set('ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
    assert '0' not in code and 'O' not in code and '1' not in code and 'I' not in code


def test_submit_stores_one_key_and_then_refuses():
    session = PairSession(code='ABCDEF', now=lambda: 0, ttl=TTL_SECONDS)
    assert session.submit('ABCDEF', '  %s  ' % _SECRET) == 'ok'
    assert session.submit('ABCDEF', 'OTHERSECRET') == 'used'
    assert session.take() == _SECRET
    assert session.take() is None


def test_a_wrong_code_does_not_store_the_key_and_then_locks():
    session = PairSession(code='ABCDEF', now=lambda: 0)
    for _ in range(MAX_FAILURES - 1):
        assert session.submit('ZZZZZZ', _SECRET) == 'bad'
    assert session.submit('ZZZZZZ', _SECRET) == 'expired'
    assert session.submit('ABCDEF', _SECRET) == 'expired'
    assert session.take() is None


def test_an_expired_code_stores_nothing():
    clock = {'t': 0}
    session = PairSession(code='ABCDEF', now=lambda: clock['t'], ttl=180)
    clock['t'] = 181
    assert session.submit('ABCDEF', _SECRET) == 'expired'
    assert session.take() is None


def test_blank_and_overlong_keys_are_refused():
    session = PairSession(code='ABCDEF', now=lambda: 0)
    assert clean_key('   ') == ''
    assert session.submit('ABCDEF', ' \n ') == 'empty'
    assert session.submit('ABCDEF', 'A' * (MAX_KEY_LENGTH + 1)) == 'long'
    assert session.take() is None
    assert session.submit('ABCDEF', 'A' * MAX_KEY_LENGTH) == 'ok'


def test_the_page_escapes_its_title_and_never_prints_the_key():
    session = PairSession(code='ABCDEF', now=lambda: 0)
    strings = dict(_STRINGS, title='<b>OMDb</b>')
    _status, html = respond('GET', '/ABCDEF', b'', session, strings)
    assert '<b>' not in html
    assert '&lt;b&gt;' in html
    body = ('code=WRONG&key=%s' % _SECRET).encode('utf-8')
    status, html = respond('POST', '/ABCDEF', body, session, strings)
    assert status == 403
    assert _SECRET not in html
    body = ('code=ABCDEF&key=%s' % _SECRET).encode('utf-8')
    status, html = respond('POST', '/ABCDEF', body, session, strings)
    assert status == 200
    assert _SECRET not in html
    assert 'Saved' in html
    assert session.take() == _SECRET


def test_local_ipv4_is_empty_without_a_route(monkeypatch):
    def boom(self, address):
        raise OSError('no route')

    monkeypatch.setattr(socket.socket, 'connect', boom)
    assert local_ipv4() == ''


def test_the_server_accepts_one_post_and_does_not_log_the_key(monkeypatch):
    _allow_localhost(monkeypatch)
    session = PairSession(code='ABCDEF', now=lambda: 0)
    server = PairServer(session, _STRINGS, host='127.0.0.1')
    stderr = io.StringIO()
    try:
        server.start()
        url = server.page_url('127.0.0.1')
        with contextlib.redirect_stderr(stderr):
            status, page = _request(url)
            assert status == 200
            assert 'ABCDEF' in page
            posted, saved = _request(url, data=('key=%s' % _SECRET).encode('utf-8'))
            huge = ('key=%s&pad=%s' % (_SECRET, 'x' * 3000)).encode('utf-8')
            rejected, reject_page = _request(url, data=huge, headers={'Content-Length': str(len(huge))})
        assert posted == 200
        assert _SECRET not in saved
        assert _SECRET not in page
        assert rejected == 400
        assert _SECRET not in reject_page
        assert session.take() == _SECRET
    finally:
        server.close()
    assert _SECRET not in stderr.getvalue()


def test_qr_bmp_paints_the_finder_and_leaves_the_quiet_zone(tmp_path):
    text = 'http://127.0.0.1:9/ABCDEF'
    path = tmp_path / 'code.bmp'
    write_qr_bmp(text, str(path))
    data = path.read_bytes()
    assert data[:2] == b'BM'
    offset = struct.unpack_from('<I', data, 10)[0]
    width, height = struct.unpack_from('<ii', data, 18)
    stride = (width * 3 + 3) & ~3

    def pixel(x, y):
        start = offset + (height - 1 - y) * stride + x * 3
        return data[start:start + 3]

    assert pixel(2, 2) == b'\xff\xff\xff'
    assert pixel(4 * 8 + 4, 4 * 8 + 4) == b'\x00\x00\x00'
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    assert qr.get_module(0, 0) is True
