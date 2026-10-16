# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Union a Stremio account's addon collection into the local list.

``addonCollectionSet`` replaces the account. Pushing the local list
alone deletes an addon that was installed in a browser and has not
been pulled yet. The merge here only adds: every local descriptor
stays, including one the response omitted, and a remote descriptor is
appended only when its transport URL validates and is not already
present. Local ``flags`` (``disabled`` included) are left as they are
when the URL matches. Web-side deletions are not mirrored.
"""

from lib.stremio.addons import AddonError, safe_url_for_log, validate_transport_url


def union_addon_descriptors(local_addons, remote_addons):
    """Return ``(merged, discarded)``.

    ``merged`` is ``local_addons`` plus remote descriptors that are safe
    and not already installed. ``discarded`` is ``(manifest_id, safe_url)``
    for remote URLs ``validate_transport_url`` rejected, so the caller
    can log them without ever writing the raw URL. Remote dicts are not
    mutated; a normalized URL is set on the copy that is appended.
    """
    local_addons = [addon for addon in (local_addons or []) if isinstance(addon, dict)]
    seen = set()
    for addon in local_addons:
        url = addon.get('transportUrl')
        if not url:
            continue
        seen.add(url)
        try:
            seen.add(validate_transport_url(url))
        except AddonError:
            pass
    merged = list(local_addons)
    discarded = []
    for descriptor in remote_addons or []:
        if not isinstance(descriptor, dict):
            continue
        transport_url = descriptor.get('transportUrl')
        if not transport_url:
            continue
        try:
            normalized = validate_transport_url(transport_url)
        except AddonError:
            manifest = descriptor.get('manifest') if isinstance(descriptor.get('manifest'), dict) else {}
            discarded.append((manifest.get('id') or '?', safe_url_for_log(transport_url)))
            continue
        if normalized in seen:
            continue
        merged.append(dict(descriptor, transportUrl=normalized))
        seen.add(normalized)
    return merged, discarded
