# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Short-lived LAN page for typing something on a phone instead of the TV.

The TV shows a code and a QR. The phone opens the page this process is
serving and POSTs the value. A gh-pages page cannot do that job: it is
HTTPS, and a browser will not let an HTTPS page post to the TV's HTTP
address, and a static file cannot hold the value until the TV polls.

One session takes one value: an API key (`clean_key`, the default), an
addon install link (`clean_url`), or a search (`clean_text`). The page
can carry one outbound link, such as an addon's configure page.

The code is the only secret. It lasts three minutes, locks after a
handful of wrong tries, and is single use. The value is the POST body.
Nothing in this module logs, and a response never repeats the value.

No xbmc import. The window in lib.ui.pairwindow drives it.
"""

import hmac
import os
import secrets
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from lib.qrcodegen import QrCode

TTL_SECONDS = 180
MAX_FAILURES = 8
MAX_KEY_LENGTH = 128
#: A configured addon's install link carries its whole configuration.
MAX_URL_LENGTH = 2048
MAX_TEXT_LENGTH = 120
#: The POST cap for a key or a search. A link page allows more; see
#: `body_limit`.
MAX_BODY = 2048

#: No 0/O or 1/I. Read aloud from the couch, typed if the camera misses.
_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
_CODE_LENGTH = 6

_MESSAGES = ('saved', 'bad', 'empty', 'used', 'expired', 'long')


def new_code():
    return ''.join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def clean_key(value):
    """Printable ASCII, no spaces, capped. Anything else is refused
    rather than stored, so a wrapped paste cannot become the setting."""
    text = ''.join(ch for ch in str(value or '') if 33 <= ord(ch) <= 126)
    if not text or len(text) > MAX_KEY_LENGTH:
        return ''
    return text


def clean_url(value):
    """An addon install link, or '' to refuse it.

    No whitespace, at most `MAX_URL_LENGTH`. Configure pages hand out
    ``stremio://`` links; those are the same address over HTTPS. The
    caller still runs the addon validator on the result.
    """
    text = str(value or '').strip()
    if not text or len(text) > MAX_URL_LENGTH:
        return ''
    if any(ch.isspace() or ord(ch) < 33 for ch in text):
        return ''
    lowered = text.lower()
    if lowered.startswith('stremio://'):
        text = 'https://' + text[len('stremio://'):]
        lowered = text.lower()
    if not (lowered.startswith('https://') or lowered.startswith('http://')):
        return ''
    return text


def clean_text(value):
    """A search typed on the phone, or ''. Whitespace collapsed, control
    characters dropped, at most `MAX_TEXT_LENGTH`."""
    # Whitespace (tabs, newlines) becomes one space before the other
    # control characters are dropped, so "dark\nknight" keeps its gap.
    spaced = ' '.join(str(value or '').split())
    text = ' '.join(''.join(ch for ch in spaced if ord(ch) >= 32 and ord(ch) != 127).split())
    if not text or len(text) > MAX_TEXT_LENGTH:
        return ''
    return text


def local_ipv4():
    """The address the phone can open. UDP connect selects the outbound
    interface and does not transmit. '' when there is nowhere to send
    the phone."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            sock.connect(('192.0.2.1', 9))
            ip = sock.getsockname()[0]
        except OSError:
            return ''
    finally:
        sock.close()
    if not ip or ip.startswith('127.'):
        return ''
    return ip


def _same(left, right):
    a = str(left or '').encode('utf-8')
    b = str(right or '').encode('utf-8')
    if len(a) != len(b):
        hmac.compare_digest(b, b)
        return False
    return hmac.compare_digest(a, b)


class PairSession:
    """One code, one value, then done.

    `cleaner` turns the posted text into the stored value, or '' to
    refuse it; `max_length` is what the page allows and what a refusal
    is measured against.
    """

    def __init__(self, now=None, ttl=TTL_SECONDS, code=None, cleaner=None, max_length=MAX_KEY_LENGTH):
        self.code = code or new_code()
        self.ttl = ttl
        self.cleaner = cleaner or clean_key
        self.max_length = max_length
        self._now = now or time.monotonic
        self._created = self._now()
        self._key = None
        self._fails = 0
        self._lock = threading.Lock()

    def expired(self):
        return self._now() >= self._created + self.ttl

    def submit(self, code, key):
        """'ok' stores the value. Every other result stores nothing."""
        cleaned = self.cleaner(key)
        with self._lock:
            if self._key is not None:
                return 'used'
            if self._fails >= MAX_FAILURES or self.expired():
                return 'expired'
            if not _same(code, self.code):
                self._fails += 1
                if self._fails >= MAX_FAILURES:
                    return 'expired'
                return 'bad'
            if not cleaned:
                if self.cleaner is clean_key:
                    raw = ''.join(ch for ch in str(key or '') if 33 <= ord(ch) <= 126)
                else:
                    raw = str(key or '').strip()
                return 'long' if len(raw) > self.max_length else 'empty'
            self._key = cleaned
            return 'ok'

    def take(self):
        """The key once, or None. Cleared as it is read."""
        with self._lock:
            key = self._key
            self._key = None
            return key

    def clear(self):
        with self._lock:
            self._key = None


def _esc(text):
    return (str(text or '')
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _path_code(path):
    name = (path or '/').split('?', 1)[0].strip('/')
    if not name or '/' in name or len(name) > _CODE_LENGTH:
        return ''
    if any(ch not in _ALPHABET for ch in name):
        return ''
    return name


def _page(title, body):
    return (
        '<!DOCTYPE html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        '<title>%s</title>'
        '<style>body{font:20px sans-serif;background:#111;color:#eee;margin:24px}'
        'input,button{font-size:22px;padding:12px}input{width:100%%}'
        'button{margin-top:16px}</style>'
        '<h1>%s</h1>%s</html>'
    ) % (_esc(title), _esc(title), body)


def _outbound(strings):
    """The page's one outbound link (an addon's configure page), or ''.
    Only http(s), escaped, opened without a referrer."""
    link = str(strings.get('link') or '')
    if not link.lower().startswith(('https://', 'http://')):
        return ''
    return '<p><a href="%s" target="_blank" rel="noopener noreferrer">%s</a></p>' % (
        _esc(link), _esc(strings.get('link_label') or link),
    )


def _form(strings, code, max_length=MAX_KEY_LENGTH):
    hidden = ''
    typed = ''
    if code:
        hidden = '<input type="hidden" name="code" value="%s">' % _esc(code)
    else:
        typed = '<input name="code" maxlength="8" autocomplete="off" autocapitalize="characters">'
    body = (
        '<p>%s</p>%s<form method="post" action="/%s" autocomplete="off">%s%s'
        '<input name="key" maxlength="%d" autocomplete="off" autocapitalize="off" '
        'spellcheck="false" autofocus>'
        '<button type="submit">%s</button></form>'
    ) % (
        _esc(strings.get('prompt')),
        _outbound(strings),
        _esc(code),
        hidden,
        typed,
        max_length,
        _esc(strings.get('save')),
    )
    return _page(strings.get('title'), body)


def _result(strings, kind):
    text = strings.get(kind) or strings.get('bad') or ''
    return _page(strings.get('title'), '<p>%s</p>' % _esc(text))


def body_limit(session):
    """The largest POST `session` accepts. Percent-encoding can triple a
    value, and the form adds the code and field names."""
    length = getattr(session, 'max_length', MAX_KEY_LENGTH) or MAX_KEY_LENGTH
    return max(MAX_BODY, length * 3 + 256)


def respond(method, path, body, session, strings):
    """(status, html) for one request. `body` is the raw POST.

    The html is built from the fixed messages in `strings`. The key is
    not one of them.
    """
    strings = strings or {}
    if method == 'GET':
        if (path or '').split('?', 1)[0] == '/favicon.ico':
            return 404, ''
        return 200, _form(strings, _path_code(path), getattr(session, 'max_length', MAX_KEY_LENGTH))
    if method != 'POST':
        return 405, _result(strings, 'bad')
    try:
        fields = parse_qs(body.decode('utf-8', 'replace'), keep_blank_values=True)
    except Exception:
        return 400, _result(strings, 'empty')
    code = (fields.get('code') or [''])[0] or _path_code(path)
    key = (fields.get('key') or [''])[0]
    kind = session.submit(code, key)
    if kind == 'ok':
        return 200, _result(strings, 'saved')
    status = {'bad': 403, 'empty': 400, 'long': 400, 'used': 409, 'expired': 410}.get(kind, 400)
    return status, _result(strings, kind if kind in _MESSAGES else 'bad')


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        """Silence. The default line is the request path, and a future
        change that put the key on that path would land in Kodi's log."""
        return

    def version_string(self):
        return 'pairing'

    def do_GET(self):
        self._serve('GET', b'')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except (TypeError, ValueError):
            length = -1
        if length < 0 or length > body_limit(self.server.session):
            self.close_connection = True
            self._write(400, _result(self.server.strings, 'long'))
            return
        raw = self.rfile.read(length) if length else b''
        self._serve('POST', raw)

    def _serve(self, method, raw):
        try:
            status, html = respond(method, self.path, raw, self.server.session, self.server.strings)
        except Exception:
            status, html = 500, _result(self.server.strings, 'bad')
        self._write(status, html)

    def _write(self, status, html):
        payload = (html or '').encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, session, strings):
        self.session = session
        self.strings = strings
        super().__init__(address, _Handler)

    def handle_error(self, request, client_address):
        """Drop the traceback. It can quote the request line."""
        return


class PairServer:
    """Serves one session until `close`. `host` is the bind address."""

    def __init__(self, session, strings, host='0.0.0.0', port=0):
        self.session = session
        self.strings = strings
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None

    def start(self):
        self._httpd = _Server((self.host, self.port), self.session, self.strings)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        self._thread.start()

    def page_url(self, ip):
        return 'http://%s:%d/%s' % (ip, self.port, self.session.code)

    def close(self):
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=2)
        self.session.clear()


def write_qr_bmp(text, path, scale=8, border=4):
    """A BMP Kodi can `setImage`. Quiet zone included. Returns `path`."""
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    modules = qr.get_size()
    dim = (modules + border * 2) * scale
    row_stride = (dim * 3 + 3) & ~3
    pixels = bytearray(b'\xff' * (row_stride * dim))
    for y in range(modules):
        for x in range(modules):
            if not qr.get_module(x, y):
                continue
            for sy in range(scale):
                file_y = dim - 1 - ((y + border) * scale + sy)
                for sx in range(scale):
                    px = (x + border) * scale + sx
                    start = file_y * row_stride + px * 3
                    pixels[start:start + 3] = b'\x00\x00\x00'
    header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
    info = struct.pack('<IiiHHIIiiII', 40, dim, dim, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write(header)
        handle.write(info)
        handle.write(pixels)
    return path
