# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Settings action: pair a key from a phone on the same Wi-Fi.

`PAIRABLE` is the list. A new key is one row (setting id, label id)
plus a caller of `pair_setting`. The ratings button asks which row,
then shows the code. The fetch runs in `lib.pairing`; this module only
paints the dialog and writes the setting.

The key is passed to `setSetting` and then dropped. A failure is logged
as the exception class, never `str(exc)`, because a message built from
the value would be the key.
"""

import os
import tempfile
import time

from lib.pairing import TTL_SECONDS, PairServer, PairSession, local_ipv4, write_qr_bmp
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


def _strings(label):
    from lib.ui.compat import L

    return {
        'title': label,
        'prompt': L(30459),
        'save': L(30463),
        'saved': L(30464),
        'bad': L(30465),
        'empty': L(30466),
        'used': L(30467),
        'expired': L(30462),
        'long': L(30468),
    }


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


def pair_setting(setting_id, label, sleep=None, ipv4=None, bind_host='0.0.0.0', timeout=None):
    """Block until the phone posts, the user backs out, or the code expires.

    `ipv4` and `bind_host` are for tests. Production binds every
    interface and advertises `local_ipv4()`."""
    import xbmc

    from lib.ui.compat import ADDON, L, log, notify
    from lib.ui.uicommon import (
        open_window,
        register_transient_dialog,
        unregister_transient_dialog,
    )

    ip = local_ipv4() if ipv4 is None else ipv4
    if not ip:
        notify(L(30461))
        return
    session = PairSession(ttl=TTL_SECONDS if timeout is None else timeout)
    server = PairServer(session, _strings(label), host=bind_host)
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
        _paint(window, label, session.code, url, L(30459), qr_path, L(30223))
        key = _wait(session, window.iscanceled, sleep or _sleep, session.ttl)
        if not key:
            if not window.iscanceled():
                notify(L(30462))
            return
        try:
            ADDON.setSetting(setting_id, key)
        except Exception as exc:
            log('pair: save failed: %s' % type(exc).__name__, xbmc.LOGERROR)
            notify(L(30469))
            return
        notify(L(30460))
    except Exception as exc:
        log('pair: failed: %s' % type(exc).__name__, xbmc.LOGERROR)
        notify(L(30461))
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
