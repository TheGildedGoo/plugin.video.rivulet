# SPDX-License-Identifier: MIT

"""Pull the Stremio addon collection into the local store before a push.

``addonCollectionSet`` replaces the whole account collection, so pushing
a stale local list deletes any addon that was added from another Stremio
client since the last pull. Every push therefore pulls first and unions
remote-only addons into ``addons.json`` (through ``Store.update_addons``,
the only compare-and-swap path). A failed pull raises ``ApiError`` and the
caller must not push. Web-side deletions are not propagated down.

Adapted from TheGildedGoo/plugin.video.rivulet (MIT).
"""

from lib.stremio.addons import AddonError, safe_url_for_log, validate_transport_url
from lib.ui.compat import log


def union_remote(local_addons, remote_addons, removed_url=None):
    """``local_addons`` plus every remote-only descriptor with a safe URL.

    Remote descriptors are untrusted account data: a ``transportUrl``
    failing ``validate_transport_url`` is discarded (only its safe
    identity is logged). Local entries are never altered or dropped.

    ``removed_url`` is the addon the user just uninstalled locally: the
    account still lists it (that is what the push is about to fix), so
    without this exclusion the pull would resurrect it and an uninstall
    could never stick while logged in.
    """
    import xbmc

    seen = {a.get('transportUrl') for a in local_addons}
    merged = list(local_addons)
    for descriptor in remote_addons:
        transport_url = descriptor.get('transportUrl')
        if not transport_url:
            continue
        try:
            normalized_url = validate_transport_url(transport_url)
        except AddonError:
            manifest_id = (descriptor.get('manifest') or {}).get('id') or '?'
            log('addonsync: discarding unsafe synced addon %s (%s)' % (
                manifest_id, safe_url_for_log(transport_url)), xbmc.LOGWARNING)
            continue
        if normalized_url not in seen and normalized_url != removed_url:
            merged.append(dict(descriptor, transportUrl=normalized_url))
            seen.add(normalized_url)
    return merged


def pull_account_addons(store, api, auth_key, removed_url=None):
    """Fetch the account collection and union it into ``store``.

    Raises ``ApiError`` (and ``ConcurrentUpdateError`` from the store)
    untouched so the caller can skip the push.
    """
    remote = api.addon_collection_get(auth_key)
    store.update_addons(lambda local: union_remote(local, remote, removed_url))
