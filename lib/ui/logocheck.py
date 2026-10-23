# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Is this clearlogo real? Asked over HTTP, off the GUI thread.

The hero swaps the text title for a clearlogo only when the logo is known
to load: the skin hides the title whenever a logo is set, so a logo URL
that 404s (metahub has none for many titles) left the title area blank
(#10). rev15 trusted only Kodi's texture cache, which holds a logo once
some control has drawn it. Two warm slots could not keep up with a row
of posters, so most titles showed text even when their logo existed.

This asks the logo's host directly: one small GET per URL, on a single
worker, the answer kept for the session. A logo that answers with an
image is good; the worker then posts ``Action(noop)`` so the screen that
asked repaints its hero with it. Nothing here blocks the remote.
"""

import threading

from lib.stremio.addons import USER_AGENT

#: url -> True (an image), False (missing or not an image). Absent: not asked.
_STATE = {}  # type: dict
#: url -> (Kodi texture-cache result, monotonic check time).
_LOGO_STATE = {}  # type: dict
_MAX_CACHE_ENTRIES = 2000
_PENDING = []  # type: list
_LOCK = threading.Lock()
_WAKE = threading.Event()
_WORKER = []  # type: list
_STOP = threading.Event()
#: Per request. A slow host just means the text title stays a while.
TIMEOUT_SECONDS = 4.0
#: At most this many URLs wait; older asks are dropped first (the remote
#: has moved on from them).
_MAX_PENDING = 24


def _cap(cache):
    """FIFO: a long session must not retain every URL it has visited."""
    while len(cache) > _MAX_CACHE_ENTRIES:
        del cache[next(iter(cache))]


def texture_cached(url):
    """Kodi's already-downloaded logo; revalidation asks here before HTTP."""
    import json

    import xbmc

    request = {
        'jsonrpc': '2.0', 'id': 1, 'method': 'Textures.GetTextures',
        'params': {
            'properties': ['url'],
            'filter': {'field': 'url', 'operator': 'is', 'value': url},
        },
    }
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)) or '{}')
    except Exception:
        return False
    result = answer.get('result') if isinstance(answer, dict) else None
    textures = result.get('textures') if isinstance(result, dict) else None
    return bool(textures)


def texture_state(url):
    with _LOCK:
        return _LOGO_STATE.get(url)


def remember_texture(url, good, checked_at):
    with _LOCK:
        _LOGO_STATE[url] = (bool(good), checked_at)
        _cap(_LOGO_STATE)


def state(url):
    """True, False, or None when `url` has not been answered yet."""
    with _LOCK:
        return _STATE.get(url)


def remember(url, good):
    """Record an answer learnt elsewhere (Kodi's texture cache)."""
    if url:
        with _LOCK:
            _STATE[url] = bool(good)
            _cap(_STATE)


def forget_all():
    """Drop every answer (Settings > Refresh cached data)."""
    with _LOCK:
        _STATE.clear()
        _LOGO_STATE.clear()
        del _PENDING[:]


def ask(urls):
    """Queue `urls` that have no answer yet. Returns at once."""
    queued = False
    with _LOCK:
        for url in urls or ():
            if not url or url in _STATE or url in _PENDING:
                continue
            _PENDING.append(url)
            queued = True
        while len(_PENDING) > _MAX_PENDING:
            _PENDING.pop(0)
        if queued:
            _STOP.clear()
        if queued and not _WORKER:
            worker = threading.Thread(target=_run, name='rivulet-logocheck', daemon=True)
            _WORKER.append(worker)
            worker.start()
    if queued:
        _WAKE.set()


def stop():
    """Home closed: discard queued asks and wake the idle worker now."""
    with _LOCK:
        del _PENDING[:]
        _STOP.set()
        _WAKE.set()


def _next():
    with _LOCK:
        # Newest first: the title the remote is on now.
        if _PENDING:
            return _PENDING.pop()
        # Clear while the empty check still holds the queue lock. An ask
        # after this check sets the event after acquiring the same lock.
        _WAKE.clear()
        return None


def _run():
    from lib.ui.background import monitor as shared_monitor

    monitor = shared_monitor()
    retired = False
    try:
        while True:
            with _LOCK:
                if _STOP.is_set() or monitor.abortRequested():
                    del _WORKER[:]
                    retired = True
                    return
            url = _next()
            if url is None:
                if not _WAKE.wait(1.0):
                    with _LOCK:
                        if _PENDING:
                            continue
                        # Retire atomically with the last empty check, so
                        # the next ask can start a worker immediately.
                        del _WORKER[:]
                        retired = True
                    return
                continue
            good = texture_cached(url) or fetch_is_image(url)
            with _LOCK:
                # Decide and retire under the lock `ask()` takes. Returning
                # first and deregistering in `finally` left a window where
                # an ask saw this worker registered, queued its URL, and
                # started no replacement.
                if _STOP.is_set() or monitor.abortRequested():
                    del _WORKER[:]
                    retired = True
                    return
            remember(url, good)
            if good:
                _repaint()
    finally:
        if not retired:
            with _LOCK:
                del _WORKER[:]


def fetch_is_image(url):
    """True when `url` answers 200/206 with an image. Never raises."""
    try:
        import requests
    except Exception:
        return False
    try:
        response = requests.get(
            url, stream=True, timeout=TIMEOUT_SECONDS, headers={'Range': 'bytes=0-2047', 'User-Agent': USER_AGENT},
        )
    except Exception:
        return False
    try:
        if response.status_code not in (200, 206):
            return False
        kind = str(response.headers.get('Content-Type') or '').lower()
        return kind.startswith('image/')
    except Exception:
        return False
    finally:
        try:
            response.close()
        except Exception:
            pass


def _repaint():
    try:
        import xbmc

        xbmc.executebuiltin('Action(noop)')
    except Exception:
        pass
