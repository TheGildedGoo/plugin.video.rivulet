# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Pull the Stremio addon collection into the local store.

Home and the Add-ons screen share one 15-minute monotonic clock, so
backing out of a hub does not pull again. Every push calls
``pull_account_addons(..., force=True)`` first: ``addonCollectionSet``
replaces the account, and a push of a stale local list deletes an addon
that was added on the web.

The pull does not run from the playback service. A failed pull leaves
the local list alone and does not push. 401/403 clears the stored auth.
A timeout does not. Web-side deletions are left alone.
"""

import threading
import time

from lib.stremio.api import ApiError, StremioAPI
from lib.stremio.collection import union_addon_descriptors

#: Home open / Add-ons open. A push ignores this and pulls immediately.
PULL_INTERVAL_SECONDS = 15 * 60

_lock = threading.Lock()
_last_success = None


def reset_pull_clock():
    """Test hook. Production never calls this."""
    global _last_success
    with _lock:
        _last_success = None


def _due(now):
    with _lock:
        if _last_success is None:
            return True
        return (now - _last_success) >= PULL_INTERVAL_SECONDS


def _mark(now):
    global _last_success
    with _lock:
        _last_success = now


def _read_remote(api, auth_key):
    """``(addons, lastModified)``. A fake that only implements
    ``addon_collection_get`` still works: the timestamp is then None
    and the merge decides whether anything changed.
    """
    state = getattr(api, 'addon_collection_state', None)
    if callable(state):
        result = state(auth_key)
        if isinstance(result, tuple) and len(result) == 2:
            addons, modified = result
            if not isinstance(addons, list):
                addons = []
            return addons, modified
    addons = api.addon_collection_get(auth_key)
    if isinstance(addons, tuple) and len(addons) == 2:
        return addons
    if not isinstance(addons, list):
        addons = []
    return addons, None


def _log_discarded(discarded):
    import xbmc

    from lib.ui.compat import log

    for manifest_id, safe in discarded:
        log(
            'addonsync: discarding unsafe synced addon %s (%s)' % (manifest_id, safe),
            xbmc.LOGWARNING,
        )


def pull_account_addons(store, api=None, force=True, now=None):
    """Union remote-only addons into ``store``.

    Returns True when the local list gained a descriptor. ``force=False``
    is the Home / Add-ons clock: a successful pull inside the last 15
    minutes is skipped. ``force=True`` always hits the account, which is
    what a push needs.

    Raises ``ApiError``. On 401/403 the stored auth is cleared first.
    An unchanged ``lastModified`` does not rewrite ``addons.json``.
    """
    moment = time.monotonic() if now is None else now
    with _lock:
        if not force and _last_success is not None and (moment - _last_success) < PULL_INTERVAL_SECONDS:
            return False
    auth = store.get_auth() if store is not None else None
    if not auth or not auth.get('authKey'):
        return False
    api = api or StremioAPI()
    remote, modified = _read_remote(api, auth.get('authKey'))
    getter = getattr(store, 'get_addon_collection_mtime', None)
    if modified is not None and callable(getter) and getter() == modified:
        _mark(moment)
        return False
    current = store.get_addons()
    merged, discarded = union_addon_descriptors(current, remote)
    if discarded:
        _log_discarded(discarded)
    added = merged != current
    if added:
        def _merge(local):
            return union_addon_descriptors(local, remote)[0]

        store.update_addons(_merge)
    setter = getattr(store, 'set_addon_collection_mtime', None)
    if modified is not None and callable(setter):
        setter(modified)
    _mark(moment)
    return added


def schedule_account_pull(store, window=None):
    """Daemon pull after Home has painted. No-op when signed out, when
    the 15-minute clock has not elapsed, or when the store has no
    profile directory to persist into. A pull that adds descriptors
    drops the window's catalog-page cache so the next paint reads the
    new list.
    """
    if store is None or not callable(getattr(store, 'get_auth', None)) or not store.get_auth():
        return
    if not getattr(store, 'data_dir', None):
        return
    if not _due(time.monotonic()):
        return

    def _work():
        import xbmc

        from lib.ui.compat import L, log, notify

        try:
            added = pull_account_addons(store, force=False)
        except ApiError as exc:
            log('addonsync: home pull failed: %r' % (exc,), xbmc.LOGWARNING)
            if exc.is_auth_error:
                store.set_auth(None)
                notify(L(30035))
            return
        except Exception as exc:
            log('addonsync: home pull failed: %r' % (exc,), xbmc.LOGWARNING)
            return
        if added and window is not None:
            window._catalog_pages = None
            window._row_key = None

    threading.Thread(target=_work, name='rivulet-addon-pull', daemon=True).start()


def pull_if_due(store):
    """The Add-ons screen: same helper and same clock as Home, on the
    caller so the list matches the account while it is on screen.
    A failure leaves the list that was already on disk.
    """
    if store is None or not callable(getattr(store, 'get_auth', None)) or not store.get_auth():
        return False
    try:
        return pull_account_addons(store, force=False)
    except ApiError as exc:
        import xbmc

        from lib.ui.compat import L, log, notify

        log('addonsync: addons pull failed: %r' % (exc,), xbmc.LOGWARNING)
        if exc.is_auth_error:
            store.set_auth(None)
            notify(L(30035))
        return False
    except Exception as exc:
        import xbmc

        from lib.ui.compat import log

        log('addonsync: addons pull failed: %r' % (exc,), xbmc.LOGWARNING)
        return False
