# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Launch the Home session, with migration, update notice and heartbeat.

These run once per launch, outside onInit, which Kodi repeats when Home
reopens after playback. Keeping them here preserves their call timing.
"""
from lib.ui.dependencies import get_store
from lib.ui.uicommon import UiHeartbeat, open_window


def _migrate_mystuff_setting():
    """Carry a `home_show_continue` value over to `home_show_mystuff` once.

    The merged row replaced two rows and took a new setting id with it, so
    anyone who had deliberately turned the old "Continue watching" row OFF
    would silently get the new row switched back on. This copies that
    decision across the rename exactly once.

    Only a `false` needs carrying: the new setting already defaults to
    True, so an unset or true old value is already correct. The old key is
    cleared afterwards, which is also what makes this idempotent - a
    second launch finds nothing to migrate and cannot re-apply the value
    over a choice the user has since changed.

    Best-effort: a settings read/write failing here must never stop Home
    from opening, so any exception is logged and swallowed.
    """
    import xbmc

    from lib.ui.compat import ADDON, log, setting_bool

    try:
        raw = (ADDON.getSetting('home_show_continue') or '').strip()
        if not raw:
            return
        if not setting_bool('home_show_continue', True):
            ADDON.setSetting('home_show_mystuff', 'false')
            log('homewindow: carried home_show_continue=false to home_show_mystuff', xbmc.LOGINFO)
        ADDON.setSetting('home_show_continue', '')
    except Exception as exc:
        log('homewindow: home_show_mystuff migration failed: %r' % (exc,), xbmc.LOGWARNING)


def _notify_if_updated(store):
    """Toast the user once when the running addon version differs from the
    version `store` last recorded - the "tell them on next launch" approach
    (as opposed to a boot-time service notification, which is easy to miss
    behind Kodi's splash/home screen). A brand-new install has nothing
    recorded yet, so that first call only seeds the current version and
    stays silent; only version numbers that actually change are ever
    announced.

    Best-effort: `store` I/O failing here must never stop the home screen
    from opening, so any exception is logged and swallowed, same as other
    non-critical HomeWindow paths."""
    import xbmc

    from lib.ui.compat import log
    try:
        from lib.ui.compat import ADDON, L, notify

        current = ADDON.getAddonInfo('version')
        last_seen = store.get_last_seen_version()
        if last_seen == current:
            return
        store.set_last_seen_version(current)
        if last_seen is not None:
            notify(L(30184) % current)
    except Exception as exc:
        log('homewindow: update-notification check failed: %r' % (exc,), xbmc.LOGWARNING)




def open_home():
    """Build and run the HomeWindow modal; blocks until the user exits.

    default.py wraps this call in its own try/except and falls back to
    the minimal recovery directory (Settings row) on ANY exception, so
    an exception raised here must keep propagating unchanged - this
    only logs it for diagnostics and
    guarantees the window is closed (it may not have had a chance to
    self-close, e.g. if onInit() or doModal() itself raised) before
    re-raising.

    The whole session runs under `uicommon.UiHeartbeat`, the liveness marker
    `default.py` consults before opening another Home (see `uicommon`'s
    "UI phases" notes).

    Home always uses NewHomeWindow.xml."""
    import xbmc

    from lib.ui.compat import log

    log('homewindow: opening HomeWindow', xbmc.LOGINFO)
    # Runs here, not in HomeWindow.onInit(): onInit() re-fires every time
    # Home is resumed after a nested modal (Discover/Search/...) closes,
    # which would re-show the toast on every back-navigation. open_home()
    # runs exactly once per addon launch. get_store() itself is guarded
    # here too (not just inside _notify_if_updated): a cosmetic toast must
    # never stop Home from opening, even if Store construction itself
    # fails (e.g. an unwritable profile directory).
    _migrate_mystuff_setting()
    with UiHeartbeat():
        # Everything below runs under the heartbeat, so a second interpreter
        # (Kodi re-running the plugin root after playback - see
        # uicommon's phase notes) can tell a live UI is already up and
        # `default.py` does not open another HomeWindow over it. The
        # heartbeat is cleared and its thread joined on every exit path.
        try:
            _notify_if_updated(get_store())
        except Exception as exc:
            log('homewindow: update-notification store unavailable: %r' % (exc,), xbmc.LOGWARNING)
        from lib.ui.newhome import NewHomeWindow

        win = open_window(NewHomeWindow, 'NewHomeWindow.xml')
        try:
            win.doModal()
        except Exception as exc:  # default.py's caller falls back to the recovery directory
            log('homewindow: HomeWindow failed: %r' % (exc,), xbmc.LOGERROR)
            raise
        finally:
            # A normal return means HomeWindow already closed itself; close()
            # again here is a safe no-op. Only a raised exception makes this
            # the window's one chance to close.
            try:
                win.close()
            except Exception:
                pass
    log('homewindow: HomeWindow closed', xbmc.LOGINFO)
