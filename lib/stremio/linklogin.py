# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Sign in by approving a code on another device (Stremio's link login).

The TV asks link.stremio.com for a short code and shows it with a QR of
the code's page. The viewer opens that page on a phone, signs in to
Stremio there, and approves. Meanwhile the TV polls for the answer,
which is the account's auth key. No password is typed on the TV, and
none crosses the local network.

``create`` answers ``{"code", "link", "qrcode"}`` (also mirrored under
``result``). ``read`` answers an error envelope until the code has been
approved, then the auth key. Both shapes are read defensively: a key is
looked for at the top level and under ``result``.

No xbmc import. lib.ui.pairwindow drives it.
"""

LINK_API_URL = 'https://link.stremio.com/api'
DEFAULT_TIMEOUT = 10


class LinkError(Exception):
    """The link service could not be reached or sent nonsense."""


def _get(path, params, session=None, timeout=DEFAULT_TIMEOUT):
    import requests

    getter = session.get if session is not None else requests.get
    try:
        response = getter('%s/%s' % (LINK_API_URL, path), params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise LinkError(type(exc).__name__)
    except ValueError:
        raise LinkError('invalid response')
    if not isinstance(data, dict):
        raise LinkError('invalid response')
    return data


def _field(data, name):
    """`name` from the top level or from `result`, as a non-empty string."""
    for source in (data, data.get('result') if isinstance(data.get('result'), dict) else None):
        if isinstance(source, dict):
            value = source.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ''


def create_code(session=None, timeout=DEFAULT_TIMEOUT):
    """``(code, link)`` for a new sign-in code. Raises `LinkError`."""
    data = _get('create', {'type': 'Create'}, session=session, timeout=timeout)
    code = _field(data, 'code')
    link = _field(data, 'link')
    if not code:
        raise LinkError('no code')
    if not link.lower().startswith('https://'):
        link = 'https://link.stremio.com/%s' % code
    return code, link


def read_auth_key(code, session=None, timeout=DEFAULT_TIMEOUT):
    """The auth key once `code` has been approved, else None.

    The service answers "Invalid or expired token" while the code is
    still waiting, so an error envelope is "not yet", not a failure.
    Raises `LinkError` only when the service cannot be reached.
    """
    data = _get('read', {'type': 'Read', 'code': code}, session=session, timeout=timeout)
    return _field(data, 'authKey') or None
