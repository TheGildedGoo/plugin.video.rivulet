# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Fill the focused hero's ratings without blocking the remote.

The catalog text is drawn immediately. When an OMDb or MDBList key is
set and the 24-hour cache has this IMDb id, that text is rebuilt with
the cached scores. A miss starts one daemon thread. The thread does
not touch Kodi; when it finishes it posts Action(noop), and the
window's existing onAction paints the hero again, which now hits the
cache.

The key is read on the GUI thread and passed into the worker. It is
never written to the log. A failure is remembered for a minute, keyed
by a hash of the key, so fixing a typo retries at once and a dead
network does not refetch on every arrow press.
"""

import hashlib
import os
import threading
import time

from lib.stremio.ratings import (
    RatingsCache,
    RatingsError,
    imdb_id_of,
    merge_scores,
)

_FAIL_SECONDS = 60
_lock = threading.Lock()
_inflight = set()
_failed_until = {}  # type: dict
_cache = None
_cache_path = ''


def _token(key):
    text = (key or '').strip()
    if not text:
        return ''
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def _fail_id(imdb_id, omdb_key, mdblist_key):
    return '%s\n%s\n%s' % (imdb_id, _token(omdb_key), _token(mdblist_key))


def _keys():
    from lib.ui.compat import ADDON

    omdb = (ADDON.getSetting('ratings_omdb_key') or '').strip()
    mdblist = (ADDON.getSetting('ratings_mdblist_key') or '').strip()
    return omdb, mdblist


def _get_cache():
    global _cache, _cache_path
    from lib.ui.compat import addon_profile_dir

    path = os.path.join(addon_profile_dir(), 'ratings.json')
    if _cache is None or path != _cache_path:
        _cache = RatingsCache(path)
        _cache_path = path
    return _cache


def overlay_text(meta, fallback):
    """`fallback` (the catalog panel) plus cached scores when a key is set.

    A miss schedules a fetch and returns `fallback` unchanged, so the
    first paint still shows the catalog's IMDb rating. Never raises.
    """
    try:
        imdb_id = imdb_id_of(meta)
        if not imdb_id:
            return fallback
        omdb_key, mdblist_key = _keys()
        if not omdb_key and not mdblist_key:
            return fallback
        cache = _get_cache()
        scores = cache.lookup(imdb_id)
        if scores is None:
            _schedule(imdb_id, omdb_key, mdblist_key, cache)
            return fallback
        if not scores:
            return fallback
        from lib.ui.homewindow import _hero_meta_text
        from lib.ui.uicommon import escape_label

        return escape_label(_hero_meta_text(merge_scores(meta, scores)))
    except Exception:
        return fallback


def apply_to_property(listitem, meta, prop):
    """Write the overlaid panel onto `prop` when it actually changed."""
    if listitem is None or not isinstance(meta, dict):
        return
    fallback = listitem.getProperty(prop) or ''
    text = overlay_text(meta, fallback)
    if text != fallback:
        listitem.setProperty(prop, text)


def _schedule(imdb_id, omdb_key, mdblist_key, cache):
    fail_id = _fail_id(imdb_id, omdb_key, mdblist_key)
    now = time.time()
    with _lock:
        if imdb_id in _inflight:
            return
        if _failed_until.get(fail_id, 0) > now:
            return
        _inflight.add(imdb_id)
    thread = threading.Thread(
        target=_worker,
        args=(imdb_id, omdb_key, mdblist_key, cache, fail_id),
        daemon=True,
    )
    thread.start()


def _worker(imdb_id, omdb_key, mdblist_key, cache, fail_id):
    from lib.stremio.ratings import fetch_scores

    failed = False
    try:
        scores = fetch_scores(imdb_id, omdb_key, mdblist_key)
        cache.store(imdb_id, scores)
    except RatingsError as exc:
        failed = not exc.empty
        if exc.empty:
            try:
                cache.store(imdb_id, {})
            except Exception:
                failed = True
        _log_failure(imdb_id, exc)
    except Exception as exc:
        failed = True
        _log_failure(imdb_id, exc)
    if failed:
        with _lock:
            _failed_until[fail_id] = time.time() + _FAIL_SECONDS
    with _lock:
        _inflight.discard(imdb_id)
    try:
        import xbmc
        xbmc.executebuiltin('Action(noop)')
    except Exception:
        pass


def _log_failure(imdb_id, exc):
    """The class name only. `str(exc)` on a requests error is the URL."""
    try:
        import xbmc

        from lib.ui.compat import log

        log('ratings: fetch failed for %s: %s' % (imdb_id, type(exc).__name__), xbmc.LOGDEBUG)
    except Exception:
        pass
