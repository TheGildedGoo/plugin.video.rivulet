# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""First catalog page through the slim stale-while-revalidate cache.

The window's own in-memory pages still win for the session
(``HomeWindow._catalog_pages``, a hub row's ``posters``). This module
is the disk layer underneath the first fetch: the next launch, and a
hub opened after Home has warmed, skips the GET while the page is fresh.

Home can fill a filtered anime view from later pages; those raw pages
share a bounded session LRU below. Stock first-page callers are unchanged.
"""

import contextlib
import os
import threading
from collections import OrderedDict

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
                except OSError as exc:
                    _log_save_error(exc)


def _save(cache):
    """Write now, or once at the end of the enclosing `deferred_saves()`."""
    with _defer_lock:
        if _defer['depth']:
            _defer['dirty'] = True
            return
    cache.save()


def _log_save_error(exc):
    from lib.stremio.addons import addon_error_detail
    from lib.ui.compat import log

    log('catalogpages: cache save failed: %s' % addon_error_detail(exc))


def _store_page(cache, key, metas):
    """A loaded row survives a read-only/full cache directory."""
    try:
        cache.store(key, metas)
        _save(cache)
    except OSError as exc:
        _log_save_error(exc)


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
    """The first production catalog page; adult catalogs are not requested
    while the setting hides them. Keep the existing iterator's filtering
    and paging behavior, without a test-only client extension."""
    from lib.ui.views import iter_catalog_pages

    if _blocked(manifest, catalog):
        return []
    ctype = catalog.get('type') if isinstance(catalog, dict) else None
    cid = catalog.get('id') if isinstance(catalog, dict) else None
    try:
        page = next(iter_catalog_pages(
            transport, ctype, cid, extra=extra, catalog=catalog, manifest=manifest,
        ))
    except StopIteration:
        return []
    return [meta for meta in (page or []) if isinstance(meta, dict)]


def _revalidate(transport, manifest, catalog, extra, key):
    try:
        metas = _fetch_first_page(transport, manifest, catalog, extra)
    except Exception:
        return
    if _blocked(manifest, catalog):
        # Hiding was turned on while this ran: keep the page that is cached.
        return
    cache = get_page_cache()
    if cache is None:
        return
    _store_page(cache, key, metas)


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
    metas = _fetch_first_page(transport, manifest, catalog, extra)
    if cache is not None and key is not None:
        _store_page(cache, key, metas)
    return _visible(metas, manifest, catalog)


# Later pages live only for this interpreter. A bounded LRU shares a plain
# anime catalog's raw pages between its two filtered Home views.
_later_pages = OrderedDict()  # type: OrderedDict
_later_lock = threading.Lock()
_MAX_LATER_PAGES = 200


def clear_later_pages():
    with _later_lock:
        _later_pages.clear()


def cached_later_page(transport, ctype, cid, extra=None):
    from lib.ui.views import _fetch_catalog

    pairs = list(extra or ())
    key = (transport, ctype, cid, tuple((k, v) for k, v in pairs if k != 'skip'),
           next((v for k, v in pairs if k == 'skip'), 0))
    with _later_lock:
        if key in _later_pages:
            _later_pages.move_to_end(key)
            return list(_later_pages[key])
    page = _fetch_catalog(transport, ctype, cid, extra=extra)
    with _later_lock:
        _later_pages[key] = list(page)
        _later_pages.move_to_end(key)
        while len(_later_pages) > _MAX_LATER_PAGES:
            _later_pages.popitem(last=False)
    return page
