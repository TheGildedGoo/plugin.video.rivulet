# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Warm Kodi's texture cache with poster URLs only.

Home carries eight 1x1 image controls (``WARM_SLOTS``)
under their backdrop plate. The worker hands those slots the posters of
the first rows, eight at a time, so Kodi downloads and caches them before
the remote reaches them. Fanart and logos are not warmed: a background
decodes toward fanartres, and ninety of those plus the video cache is how
a 1 GB box gets tight. Posters are not downloaded into ``addon_data`` and
``Textures13.db`` is not written from Python. Kodi fills its own cache
when a visible control is given the URL.

This used to open a separate ``xbmcgui.Window`` for the slots. Kodi
refuses to activate a window while a modal dialog is up ("Activate of
window ... refused because there are active modal dialogs"), and every
Rivulet screen is one, so the slots never rendered and nothing was
cached. Closing that window also sent Kodi's previous-window message to
whatever was underneath. The slots now live in the screen that asked.

Each batch is held for ``_HOLD_SECONDS``. Kodi cancels a queued texture
job when its control lets go of the URL, so a batch swapped out too fast
is a batch that never loaded. The thread waits on ``Monitor.waitForAbort``
so a Kodi shutdown is not stuck behind the queue. One warmer runs at a
time; further requests add to that queue and Home's slots carry the rest.
"""

import threading

#: Image controls in NewHomeWindow.xml. 1x1, visible,
#: drawn under the opaque backdrop plate.
WARM_SLOTS = tuple(range(30090, 30098))

_HOLD_SECONDS = 1.0
_TITLES = 30
_ROWS = 3

_lock = threading.Lock()
_seen = {}  # type: dict
_MAX_SEEN = 2000
_queue = []
_target = {'window': None}
_running = False


def collect_poster_urls(groups, limit_rows=_ROWS, limit_titles=_TITLES):
    """Poster URLs from the first ``limit_rows`` non-empty groups.

    Each group is a list of metas or of objects with a ``poster``
    string. ``background`` and ``logo`` are ignored even when present.
    """
    urls = []
    rows = 0
    for group in groups or []:
        found = []
        for meta in group or []:
            if len(found) >= limit_titles:
                break
            poster = None
            if isinstance(meta, dict):
                poster = meta.get('poster')
            elif hasattr(meta, 'getProperty'):
                poster = meta.getProperty('thumbnail') or meta.getProperty('poster')
            if isinstance(poster, str) and poster:
                found.append(poster)
        if not found:
            continue
        urls.extend(found)
        rows += 1
        if rows >= limit_rows:
            break
    return urls


def _slots(window):
    """The window's warm controls, or [] when it has none (another skin,
    or a window that has already closed)."""
    if window is None:
        return []
    found = []
    for control_id in WARM_SLOTS:
        try:
            found.append(window.getControl(control_id))
        except Exception:
            return []
    return found


def _clear(slots):
    for slot in slots:
        try:
            slot.setImage('')
        except Exception:
            pass


def warm_posters(window, urls, monitor=None):
    """Feed ``urls`` to ``window``'s slots, a batch per hold. Returns
    when the list is done, the window has no slots, or Kodi is aborting.
    Posters only; the caller has already dropped everything else.
    """
    import xbmc

    urls = [url for url in (urls or []) if isinstance(url, str) and url]
    if not urls:
        return
    slots = _slots(window)
    if not slots:
        return
    monitor = monitor or xbmc.Monitor()
    stop = getattr(window, '_home_stop', None)
    try:
        for start in range(0, len(urls), len(slots)):
            if (stop is not None and stop.is_set()) or monitor.abortRequested():
                return
            batch = urls[start:start + len(slots)]
            try:
                for slot, url in zip(slots, batch):
                    slot.setImage(url)
            except Exception:
                return
            if stop is None:
                if monitor.waitForAbort(_HOLD_SECONDS):
                    return
            else:
                # Home close is independent of Kodi shutdown. Short timed
                # waits release the slots while the window is still owned.
                import time

                until = time.monotonic() + _HOLD_SECONDS
                while time.monotonic() < until:
                    if stop.wait(min(0.1, until - time.monotonic())) or monitor.abortRequested():
                        return
    finally:
        _clear(slots)


def request_warm(window, urls):
    """Queue poster URLs for ``window``'s slots. A URL already queued
    this process is skipped. The worker is a daemon and stops with
    ``waitForAbort``.
    """
    global _running
    fresh = []
    with _lock:
        for url in urls or []:
            if not isinstance(url, str) or not url or url in _seen:
                continue
            _seen[url] = None
            while len(_seen) > _MAX_SEEN:
                del _seen[next(iter(_seen))]
            fresh.append(url)
        if not fresh:
            return
        _queue.extend(fresh)
        if window is not None:
            _target['window'] = window
        if _running:
            return
        _running = True
    threading.Thread(target=_drain, name='rivulet-poster-warm', daemon=True).start()


def _drain():
    global _running
    while True:
        with _lock:
            batch = list(_queue)
            del _queue[:]
            window = _target['window']
            stop = getattr(window, '_home_stop', None)
            if stop is not None and stop.is_set():
                del _queue[:]
                _target['window'] = None
                _running = False
                return
            if not batch:
                _running = False
                return
        try:
            warm_posters(window, batch)
        except Exception as exc:
            import xbmc

            from lib.ui.compat import log

            log('posterwarm: %s' % type(exc).__name__, xbmc.LOGWARNING)


def reset_warmer():
    """Test hook. Drops the queued URL set."""
    global _running
    with _lock:
        _seen.clear()
        del _queue[:]
        _target['window'] = None
        _running = False
