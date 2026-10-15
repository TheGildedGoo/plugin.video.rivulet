# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Warm Kodi's texture cache with poster URLs only.

Four 1x1 image controls, visible, fed ``setImage`` four at a time.
``visible=false`` often skips the load. Fanart and logos are not warmed:
a background decodes toward fanartres, and ninety of those plus the
video cache is how a 1 GB box gets tight. Posters are not downloaded
into ``addon_data`` and ``Textures13.db`` is not written from Python.
Kodi fills its own cache when the control is given the URL.

The thread waits on ``Monitor.waitForAbort`` between batches so a Kodi
shutdown is not stuck behind the rest of the queue. One warmer runs at
a time; a hub that opens while Home is still warming appends to that
queue instead of starting a second one.
"""

import threading

_BATCH = 4
_WAIT_SECONDS = 0.05
_TITLES = 30
_ROWS = 3

_lock = threading.Lock()
_seen = set()
_queue = []
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


def warm_posters(urls, monitor=None):
    """Feed ``urls`` to four visible 1x1 controls. Returns when the
    queue is done or Kodi is aborting. Posters only; the caller has
    already dropped everything else.
    """
    import xbmc
    import xbmcgui

    urls = [url for url in (urls or []) if isinstance(url, str) and url]
    if not urls:
        return
    monitor = monitor or xbmc.Monitor()
    window = xbmcgui.Window()
    images = []
    for _slot in range(_BATCH):
        image = xbmcgui.ControlImage(0, 0, 1, 1, '')
        window.addControl(image)
        images.append(image)
    window.show()
    try:
        for start in range(0, len(urls), _BATCH):
            if monitor.waitForAbort(_WAIT_SECONDS):
                return
            for image, url in zip(images, urls[start:start + _BATCH]):
                image.setImage(url)
    finally:
        try:
            window.close()
        except Exception:
            pass


def request_warm(urls):
    """Queue poster URLs. A URL already queued this process is skipped.
    The worker is a daemon and dies with ``waitForAbort``.
    """
    global _running
    fresh = []
    with _lock:
        for url in urls or []:
            if not isinstance(url, str) or not url or url in _seen:
                continue
            _seen.add(url)
            fresh.append(url)
        if not fresh:
            return
        _queue.extend(fresh)
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
            if not batch:
                _running = False
                return
        try:
            warm_posters(batch)
        except Exception as exc:
            import xbmc

            from lib.ui.compat import log

            log('posterwarm: %r' % (exc,), xbmc.LOGWARNING)


def reset_warmer():
    """Test hook. Drops the queued URL set."""
    global _running
    with _lock:
        _seen.clear()
        del _queue[:]
        _running = False
