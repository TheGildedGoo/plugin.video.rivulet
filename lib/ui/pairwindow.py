# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Type on the phone instead of the TV.

`pair_value` shows a code and a QR, serves the short-lived page in
`lib.pairing`, and returns what the phone posted. Its callers:

- `pair_setting`: a ratings key (`PAIRABLE`), written to the setting.
- `ask_addon_url`: an addon's install link, from Add-ons and from a
  configurable addon (the page links to its configure page).
- `phone_search`: a search, from the Search screen.

`link_sign_in` is the other phone flow: Stremio's own code sign-in
(`lib.stremio.linklogin`). The TV shows a code, the viewer approves it
on a phone where they are signed in, and no password is typed here.

A value is handed to its caller and then dropped. A failure is logged
as the exception class, never `str(exc)`, because a message built from
the value would be the value.
"""

import os
import tempfile
import time

from lib.pairing import (
    MAX_KEY_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_URL_LENGTH,
    TTL_SECONDS,
    PairServer,
    PairSession,
    clean_text,
    clean_url,
    local_ipv4,
    write_qr_bmp,
)
from lib.ui.dialogs import _TransientDialog

PAIR_HEADING = 30390
PAIR_CODE = 30391
PAIR_URL = 30392
PAIR_HINT = 30393
PAIR_QR = 30394
PAIR_CANCEL = 30395

#: (setting id, strings.po id). Order is the chooser order.
PAIRABLE = (
    ('ratings_omdb_key', 30453),
    ('ratings_mdblist_key', 30454),
)


class _PairWindow(_TransientDialog):
    def onClick(self, control_id):
        if control_id == PAIR_CANCEL:
            self.cancel()


def open_pair_picker():
    """Settings button. Back leaves every key alone."""
    from lib.ui.compat import L
    from lib.ui.dialogs import choose

    index = choose(L(30458), [L(string_id) for _setting_id, string_id in PAIRABLE])
    if index is None or index < 0 or index >= len(PAIRABLE):
        return
    setting_id, string_id = PAIRABLE[index]
    pair_setting(setting_id, L(string_id))


def _strings(label, prompt=None, messages=None):
    from lib.ui.compat import L

    strings = {
        'title': label,
        'prompt': prompt or L(30459),
        'save': L(30463),
        'saved': L(30464),
        'bad': L(30465),
        'empty': L(30466),
        'used': L(30467),
        'expired': L(30462),
        'long': L(30468),
    }
    strings.update(messages or {})
    return strings


def _sleep(seconds):
    import xbmc
    return xbmc.Monitor().waitForAbort(seconds)


def _wait(session, canceled, sleep, timeout):
    deadline = time.monotonic() + timeout
    while True:
        key = session.take()
        if key:
            return key
        if canceled():
            return None
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        if sleep(min(0.25, left)):
            return None


def _paint(window, heading, code, url, hint, image, cancel):
    window.getControl(PAIR_HEADING).setLabel(heading)
    window.getControl(PAIR_CODE).setLabel(code)
    window.getControl(PAIR_URL).setLabel(url)
    window.getControl(PAIR_HINT).setText(hint)
    window.getControl(PAIR_CANCEL).setLabel(cancel)
    if image:
        window.getControl(PAIR_QR).setImage(image)


def pair_value(label, prompt=None, cleaner=None, max_length=MAX_KEY_LENGTH, messages=None,
               sleep=None, ipv4=None, bind_host='0.0.0.0', timeout=None):
    """Show the code and the QR; block until the phone posts, the user
    backs out, or the code expires. The cleaned value, or None.

    `messages` overrides the page's texts (`prompt`, `empty`, `long`,
    `link`, `link_label`, ...). `ipv4` and `bind_host` are for tests.
    Production binds every interface and advertises `local_ipv4()`.
    """
    import xbmc

    from lib.ui.compat import L, log, notify
    from lib.ui.uicommon import (
        open_window,
        register_transient_dialog,
        unregister_transient_dialog,
    )

    ip = local_ipv4() if ipv4 is None else ipv4
    if not ip:
        notify(L(30461))
        return None
    strings = _strings(label, prompt, messages)
    session = PairSession(
        ttl=TTL_SECONDS if timeout is None else timeout,
        cleaner=cleaner, max_length=max_length,
    )
    server = PairServer(session, strings, host=bind_host)
    qr_path = ''
    window = None
    try:
        server.start()
        url = server.page_url(ip)
        qr_path = os.path.join(tempfile.gettempdir(), 'rivulet-pair-%s.bmp' % session.code)
        try:
            write_qr_bmp(url, qr_path)
        except Exception as exc:
            log('pair: qr failed: %s' % type(exc).__name__, xbmc.LOGDEBUG)
            qr_path = ''
        window = open_window(_PairWindow, 'PairDialog.xml')
        register_transient_dialog(window)
        window.show()
        _paint(window, label, session.code, url, strings['prompt'], qr_path, L(30223))
        value = _wait(session, window.iscanceled, sleep or _sleep, session.ttl)
        if not value:
            if not window.iscanceled():
                notify(L(30462))
            return None
        return value
    except Exception as exc:
        log('pair: failed: %s' % type(exc).__name__, xbmc.LOGERROR)
        notify(L(30461))
        return None
    finally:
        if window is not None:
            unregister_transient_dialog(window)
            window.close()
        server.close()
        if qr_path:
            try:
                os.remove(qr_path)
            except OSError:
                pass


def pair_setting(setting_id, label, sleep=None, ipv4=None, bind_host='0.0.0.0', timeout=None):
    """A ratings key from the phone, written to `setting_id`."""
    import xbmc

    from lib.ui.compat import ADDON, L, log, notify

    key = pair_value(label, sleep=sleep, ipv4=ipv4, bind_host=bind_host, timeout=timeout)
    if not key:
        return
    try:
        ADDON.setSetting(setting_id, key)
    except Exception as exc:
        log('pair: save failed: %s' % type(exc).__name__, xbmc.LOGERROR)
        notify(L(30469))
        return
    notify(L(30460))


def ask_addon_url(heading, configure_url=None, title=None):
    """An addon install link, from the phone or the keyboard. '' on Back.

    The phone page links to `configure_url` when the addon needs one, so
    the viewer configures it there and pastes the link it hands out. The
    keyboard is still offered: phone remote apps can type into it.
    """
    import xbmcgui

    from lib.ui.compat import L
    from lib.ui.dialogs import choose

    picked = choose(title or heading, [L(30474), L(30475)])
    if picked == 0:
        messages = {'empty': L(30478), 'long': L(30479)}
        if configure_url:
            messages['link'] = configure_url
            messages['link_label'] = L(30477)
        value = pair_value(
            title or L(30010), L(30476), cleaner=clean_url,
            max_length=MAX_URL_LENGTH, messages=messages,
        )
        return value or ''
    if picked == 1:
        return xbmcgui.Dialog().input(heading) or ''
    return ''


def phone_search():
    """A search typed on the phone, or ''."""
    from lib.ui.compat import L

    value = pair_value(
        L(30001), L(30485), cleaner=clean_text, max_length=MAX_TEXT_LENGTH,
        messages={'empty': L(30486), 'long': L(30487)},
    )
    return value or ''


#: How often the TV asks whether the code has been approved, and for how
#: long. The service's own code lifetime is not published; five minutes
#: is long enough to sign in on a phone.
_LINK_POLL_SECONDS = 2.0
_LINK_TIMEOUT_SECONDS = 300


def link_sign_in(api=None, sleep=None, timeout=_LINK_TIMEOUT_SECONDS):
    """Stremio's code sign-in. ``{'authKey', 'user'}``, or None.

    None when the viewer backs out, the code times out, or the service
    cannot be reached (a toast says which). The auth key is never
    logged.
    """
    import xbmc

    from lib.stremio.api import ApiError
    from lib.stremio.linklogin import LinkError, create_code, read_auth_key
    from lib.ui.compat import L, log, notify
    from lib.ui.dependencies import get_api
    from lib.ui.uicommon import (
        open_window,
        register_transient_dialog,
        unregister_transient_dialog,
    )

    try:
        code, link = create_code()
    except LinkError as exc:
        log('signin: link code failed: %s' % exc, xbmc.LOGWARNING)
        notify(L(30023))
        return None
    sleep = sleep or _sleep
    qr_path = os.path.join(tempfile.gettempdir(), 'rivulet-link-%s.bmp' % code)
    try:
        write_qr_bmp(link, qr_path)
    except Exception as exc:
        log('signin: qr failed: %s' % type(exc).__name__, xbmc.LOGDEBUG)
        qr_path = ''
    window = None
    try:
        window = open_window(_PairWindow, 'PairDialog.xml')
        register_transient_dialog(window)
        window.show()
        _paint(window, L(30480), code, link, L(30482), qr_path, L(30223))
        deadline = time.monotonic() + timeout
        next_read = 0.0
        auth_key = None
        while True:
            if window.iscanceled():
                return None
            now = time.monotonic()
            if now >= deadline:
                notify(L(30462))
                return None
            if now >= next_read:
                next_read = now + _LINK_POLL_SECONDS
                try:
                    auth_key = read_auth_key(code)
                except LinkError as exc:
                    log('signin: link read failed: %s' % exc, xbmc.LOGDEBUG)
                if auth_key:
                    break
            # Short naps so Back answers at once; the service is only
            # asked every `_LINK_POLL_SECONDS`.
            if sleep(min(0.25, max(0.0, deadline - now))):
                return None
        try:
            user = (api or get_api()).get_user(auth_key)
        except ApiError as exc:
            log('signin: user lookup failed: %s' % type(exc).__name__, xbmc.LOGWARNING)
            user = {}
        if not isinstance(user, dict):
            user = {}
        return {'authKey': auth_key, 'user': user}
    finally:
        if window is not None:
            unregister_transient_dialog(window)
            window.close()
        if qr_path:
            try:
                os.remove(qr_path)
            except OSError:
                pass
