# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""First catalog page through the slim stale-while-revalidate cache.

The window's own in-memory pages still win for the session
(``HomeWindow._catalog_pages``, a hub row's ``posters``). This module
is the disk layer underneath the first fetch: the next launch, and a
hub opened after Home has warmed, skips the GET while the page is fresh.

No second page is fetched to fill a row. One catalog page is already
more titles than the first screen draws.
"""

import contextlib
import os
import threading

from lib.stremio.pagecache import cache_key

_CATALOG_PAGES_FILENAME = 'catalog_pages.json'
_caches = {}  # type: dict
_caches_lock = threading.Lock()
_revalidate_inflight = set()
_revalidate_lock = threading.Lock()

#: `deferred_saves()` nesting depth, and whether a store happened inside.
#: Not thread-local on purpose: Home and the hubs fetch a first screen on
#: several workers inside one `deferred_saves()` block.
_defer = {'depth': 0, 'dirty': False}
_defer_lock = threading.Lock()


@contextlib.contextmanager
def deferred_saves():
    """Inside, pages are stored as they arrive and the file is written
    once, on the way out. Home used to rewrite catalog_pages.json once
    per row it opened (#13)."""
    with _defer_lock:
        _defer['depth'] += 1
    try:
        yield
    finally:
        with _defer_lock:
            _defer['depth'] -= 1
            flush = _defer['depth'] == 0 and _defer['dirty']
            if flush:
                _defer['dirty'] = False
        if flush:
            cache = get_page_cache()
            if cache is not None:
                try:
                    cache.save()
                except Exception:
                    pass


def _save(cache):
    """Write now, or once at the end of the enclosing `deferred_saves()`."""
    with _defer_lock:
        if _defer['depth']:
            _defer['dirty'] = True
            return
    cache.save()


def get_page_cache():
    """The process cache for the current profile, or None when the store
    has no data directory (fakes, and any caller that cannot persist).
    """
    from lib.ui.dependencies import get_store

    store = get_store()
    data_dir = getattr(store, 'data_dir', None)
    if not data_dir:
        return None
    path = os.path.join(data_dir, _CATALOG_PAGES_FILENAME)
    with _caches_lock:
        cache = _caches.get(path)
        if cache is None:
            from lib.stremio.pagecache import PageCache

            cache = PageCache(path)
            _caches[path] = cache
        return cache


def _hide_adult():
    from lib.ui.views import _adult_filtering_enabled

    return _adult_filtering_enabled()


def _blocked(manifest, catalog):
    """True for an adult catalog while the setting hides them. Such a
    catalog is neither requested nor cached: an empty page stored now
    would keep it empty after the setting is turned off."""
    if not _hide_adult():
        return False
    from lib.stremio.contentrating import is_adult_catalog

    return bool(is_adult_catalog(catalog if catalog is not None else {}, manifest))


def _visible(metas, manifest, catalog):
    """`metas` as the CURRENT hide-adult setting allows them: none for an
    adult catalog, and adult items dropped from any other. Pages are
    stored unfiltered, so this runs on every read, cached or fresh, and
    turning the setting on hides a page cached while it was off."""
    if metas is None or not _hide_adult():
        return metas
    from lib.stremio.contentrating import filter_metas, is_adult_catalog

    if is_adult_catalog(catalog if catalog is not None else {}, manifest):
        return []
    return filter_metas(metas)


def _fetch_first_page(transport, manifest, catalog, extra):
    """One page, unfiltered, and its cache hints. Adult catalogs are not
    requested while the setting hides them.

    A client without ``catalog_with_hints`` (the test fakes) falls
    through to ``iter_catalog_pages``, which already applies the adult
    filter and returns no hints.
    """
    from lib.ui.dependencies import get_client
    from lib.ui.views import iter_catalog_pages

    if _blocked(manifest, catalog):
        return [], {}
    client = get_client()
    hints_fn = getattr(client, 'catalog_with_hints', None)
    ctype = catalog.get('type') if isinstance(catalog, dict) else None
    cid = catalog.get('id') if isinstance(catalog, dict) else None
    if callable(hints_fn):
        metas, hints = hints_fn(transport, ctype, cid, extra=extra)
        return [meta for meta in metas if isinstance(meta, dict)], hints
    try:
        page = next(iter_catalog_pages(
            transport, ctype, cid, extra=extra, catalog=catalog, manifest=manifest,
        ))
    except StopIteration:
        return [], {}
    return [meta for meta in (page or []) if isinstance(meta, dict)], {}


def _revalidate(transport, manifest, catalog, extra, key):
    try:
        metas, hints = _fetch_first_page(transport, manifest, catalog, extra)
    except Exception:
        return
    if _blocked(manifest, catalog):
        # Hiding was turned on while this ran: keep the page that is cached.
        return
    cache = get_page_cache()
    if cache is None:
        return
    cache.store(key, metas, hints)
    _save(cache)


def _schedule_revalidate(transport, manifest, catalog, extra, key):
    with _revalidate_lock:
        if key in _revalidate_inflight:
            return
        _revalidate_inflight.add(key)

    def _work():
        try:
            _revalidate(transport, manifest, catalog, extra, key)
        finally:
            with _revalidate_lock:
                _revalidate_inflight.discard(key)

    threading.Thread(target=_work, name='rivulet-page-revalidate', daemon=True).start()


def cached_first_page(transport, manifest, catalog, extra=None):
    """The first page, from the cache when it is fresh or still servable.

    A stale hit is returned immediately and revalidated on a daemon. So
    is an expired one up to a day old (#13): the first open of an evening
    paints the rows it had instead of fetching every one cold, and the
    revalidation has the next open current. A miss fetches, stores, and
    writes the file once (once per `deferred_saves()` block).

    The page is stored as the addon sent it; the hide-adult setting is
    applied to what is returned (`_visible`), so it always reflects the
    setting as it is now. An adult catalog the setting hides is answered
    empty before the cache is read or written, so turning the setting
    off shows it again at once.
    """
    if _blocked(manifest, catalog):
        return []
    cache = get_page_cache()
    key = None
    if cache is not None and isinstance(catalog, dict):
        key = cache_key(transport, catalog.get('type'), catalog.get('id'), extra)
        state, metas = cache.lookup(key, allow_expired=True)
        if metas:
            # Pages cached before types were defaulted on the way in.
            from lib.stremio.addons import default_meta_types

            metas = default_meta_types(metas, catalog.get('type'))
        if state == 'fresh' and metas is not None:
            return _visible(metas, manifest, catalog)
        if state in ('stale', 'expired') and metas:
            _schedule_revalidate(transport, manifest, catalog, extra, key)
            return _visible(metas, manifest, catalog)
    metas, hints = _fetch_first_page(transport, manifest, catalog, extra)
    if cache is not None and key is not None:
        cache.store(key, metas, hints)
        _save(cache)
    return _visible(metas, manifest, catalog)
