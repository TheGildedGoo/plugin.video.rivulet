# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Fill the focused hero's ratings without blocking the remote.

The catalog text is drawn immediately. When an OMDb or MDBList key is
set and the 24-hour cache has this IMDb id, that text is rebuilt with
the cached scores.

A miss does not fetch at once. Holding Right across a row used to start
one request per title it passed, and OMDb's free key allows 1,000 a
day. The miss becomes the plan: the focused title, then the next few on
its row. One worker waits until the focus has rested ``_DWELL_SECONDS``
on that plan, then fetches it in order. A new focus replaces the plan
(latest wins), so titles skimmed past are never requested. The worker
does not touch Kodi; after each fetch it posts Action(noop), and the
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

_MAX_CACHE_ENTRIES = 2000
_FAIL_SECONDS = 60
#: Rejected/quota-limited keys pause across titles for five minutes. A
#: corrected key has a different token and is usable immediately.
_PROVIDER_COOLDOWN_SECONDS = 5 * 60
_provider_until = {}  # type: dict
#: How long the focus must rest before a miss is fetched.
_DWELL_SECONDS = 0.6
#: Titles after the focused one that ride along once it has been fetched.
PREFETCH = 2
_lock = threading.Lock()
_inflight = set()
_failed_until = {}  # type: dict
_cache = None
_cache_path = ''
_cache_keys = ('', '')
#: Latest-wins plan: (imdb id, omdb key, mdblist key, cache) in fetch order,
#: and the monotonic time it was set.
_plan = {'items': [], 'at': 0.0, 'running': False}
_wake = threading.Event()
_stop = threading.Event()


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


def _get_cache(omdb_key='', mdblist_key=''):
    global _cache, _cache_path, _cache_keys
    from lib.ui.compat import addon_profile_dir

    path = os.path.join(addon_profile_dir(), 'ratings.json')
    key_ids = (_token(omdb_key), _token(mdblist_key))
    if _cache is None or path != _cache_path or key_ids != _cache_keys:
        _cache = RatingsCache(path, keys=(omdb_key, mdblist_key))
        _cache_path = path
        _cache_keys = key_ids
    return _cache


def _type_of(meta):
    """The Stremio type a meta (or its panel facts) carries, or ''."""
    if not isinstance(meta, dict):
        return ''
    value = meta.get('type')
    return value.strip() if isinstance(value, str) else ''


def _misses(cache, metas):
    """`(imdb_id, type)` for the `metas` the cache does not hold, in order."""
    found = []
    seen = set()
    for meta in metas or ():
        try:
            imdb_id = imdb_id_of(meta)
        except Exception:
            imdb_id = None
        if imdb_id and imdb_id not in seen and cache.lookup(imdb_id) is None:
            seen.add(imdb_id)
            found.append((imdb_id, _type_of(meta)))
    return found


def overlay_text(meta, fallback, upcoming=None):
    """`fallback` (the catalog panel) plus cached scores when a key is set.

    A miss plans a fetch and returns `fallback` unchanged, so the first
    paint still shows the catalog's IMDb rating. `upcoming` is the next
    few metas on the row; their misses ride along after this one. Never
    raises.
    """
    try:
        imdb_id = imdb_id_of(meta)
        if not imdb_id:
            return fallback
        omdb_key, mdblist_key = _keys()
        if not omdb_key and not mdblist_key:
            return fallback
        stype = _type_of(meta)
        cache = _get_cache(omdb_key, mdblist_key)
        scores = cache.lookup(imdb_id)
        later = [other for other in _misses(cache, upcoming) if other[0] != imdb_id]
        if scores is None:
            _schedule(imdb_id, omdb_key, mdblist_key, cache, later[:PREFETCH], stype=stype)
            return fallback
        if later:
            _schedule(later[0][0], omdb_key, mdblist_key, cache, later[1:PREFETCH], stype=later[0][1])
        if not scores:
            return fallback
        from lib.ui.newhome import _hero_meta_text
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


def _schedule(imdb_id, omdb_key, mdblist_key, cache, prefetch=(), stype=''):
    """Replace the plan with `imdb_id` then `prefetch`. Latest wins.

    `stype` is `imdb_id`'s Stremio type, and each `prefetch` entry is an
    `(imdb_id, type)` pair (a bare id is taken as type unknown): MDBList
    looks movies and shows up on different paths. Nothing is fetched
    until the focus has rested `_DWELL_SECONDS` on this plan. One worker
    serves every window; it is started here when it is not already
    running.
    """
    items = []
    for entry in [(imdb_id, stype)] + list(prefetch or ()):
        wanted, wanted_type = entry if isinstance(entry, tuple) else (entry, '')
        if wanted and wanted not in [item[0] for item in items]:
            items.append((wanted, omdb_key, mdblist_key, cache, wanted_type or ''))
    if not items:
        return
    with _lock:
        _stop.clear()
        _plan['items'] = items
        _plan['at'] = time.monotonic()
        start = not _plan['running']
        if start:
            _plan['running'] = True
    _wake.set()
    if start:
        threading.Thread(target=_loop, name='rivulet-ratings', daemon=True).start()


def stop():
    """Discard Home's dwell/prefetch plan and wake its worker on close."""
    with _lock:
        _stop.set()
        _plan['items'] = []
        _wake.set()


def _next_due():
    """The plan's head once its dwell has passed: `(item, None)`, or
    `(None, seconds)` to wait, or `(None, None)` when the plan is empty
    (the worker then stops)."""
    import xbmc

    with _lock:
        if _stop.is_set() or xbmc.Monitor().abortRequested() or not _plan['items']:
            _plan['running'] = False
            return None, None
        left = _plan['at'] + _DWELL_SECONDS - time.monotonic()
        if left > 0:
            return None, left
        item = _plan['items'].pop(0)
        imdb_id, omdb_key, mdblist_key, _cache_obj, _stype = item
        fail_id = _fail_id(imdb_id, omdb_key, mdblist_key)
        if imdb_id in _inflight or _failed_until.get(fail_id, 0) > time.time():
            return (), None
        _inflight.add(imdb_id)
        return item + (fail_id,), None


def _loop():
    """The one worker. Waits out the dwell, then fetches in plan order."""
    while True:
        item, wait = _next_due()
        if item is None and wait is None:
            return
        if item is None:
            _wake.clear()
            _wake.wait(min(wait, 0.1))
            continue
        if not item:
            continue
        imdb_id, omdb_key, mdblist_key, cache, stype, fail_id = item
        try:
            cached = cache.lookup(imdb_id) is not None
        except Exception:
            cached = False
        if cached:
            with _lock:
                _inflight.discard(imdb_id)
            continue
        _worker(imdb_id, omdb_key, mdblist_key, cache, fail_id, stype)


def _cap(cache):
    """Oldest failures go first; remote scrolling is unbounded."""
    while len(cache) > _MAX_CACHE_ENTRIES:
        del cache[next(iter(cache))]


def _provider_key(provider, key):
    return '%s\n%s' % (provider, _token(key))


def _available_key(provider, key):
    with _lock:
        until = _provider_until.get(_provider_key(provider, key), 0)
    return '' if until > time.monotonic() else key


def _worker(imdb_id, omdb_key, mdblist_key, cache, fail_id, stype=''):
    from lib.stremio.ratings import fetch_scores

    def rejected(provider):
        key = omdb_key if provider == 'omdb' else mdblist_key
        with _lock:
            _provider_until[_provider_key(provider, key)] = time.monotonic() + _PROVIDER_COOLDOWN_SECONDS
            _cap(_provider_until)

    available_omdb = _available_key('omdb', omdb_key)
    available_mdblist = _available_key('mdblist', mdblist_key)
    if not available_omdb and not available_mdblist:
        with _lock:
            _inflight.discard(imdb_id)
        return
    paused = (bool(omdb_key) and not available_omdb) or (bool(mdblist_key) and not available_mdblist)
    failed = False
    try:
        scores = fetch_scores(imdb_id, available_omdb, available_mdblist, stype=stype,
                              on_rejected=rejected)
        if paused and not scores:
            raise RatingsError('provider cooldown')
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
            _cap(_failed_until)
    with _lock:
        _inflight.discard(imdb_id)
    if _stop.is_set():
        return
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
