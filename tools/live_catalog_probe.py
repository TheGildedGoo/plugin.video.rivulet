# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""One live pass against Cinemeta and the community addon catalog.

Not part of pytest: the suite blocks sockets. Prints a short report and
exits non-zero when a check the rev11 behavior depends on fails.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.stremio.addoncatalogs import (
    BUILTIN_ADDON_CATALOG_SOURCES,
    fetch_addon_catalog,
)
from lib.stremio.addons import AddonClient
from lib.stremio.decades import decade_tiles, is_year_catalog, merge_decade_pages

_CINEMETA = 'https://v3-cinemeta.strem.io/manifest.json'


def _year_catalog(manifest):
    for catalog in manifest.get('catalogs') or []:
        if catalog.get('type') != 'movie':
            continue
        if is_year_catalog(catalog):
            return catalog
    return None


def main():
    client = AddonClient()
    manifest = client.manifest(_CINEMETA)
    catalog = _year_catalog(manifest)
    if catalog is None:
        print('FAIL cinemeta has no movie year catalog')
        return 1
    options = []
    for extra in catalog.get('extra') or []:
        if extra.get('name') == 'genre':
            options = list(extra.get('options') or [])
    tiles = decade_tiles(options)
    labels = [tile['label'] for tile in tiles]
    print('cinemeta year catalog %s tiles %s' % (catalog.get('id'), ' '.join(labels)))
    if labels[:1] != ['2020s'] or '1960s' not in labels or '1950s' in labels:
        print('FAIL decade tiles are not 2020s down to 1960s')
        return 1

    nineties = next(tile for tile in tiles if tile['label'] == '1990s')

    def fetch(year, skip):
        extra = [('genre', str(year))]
        if skip:
            extra.append(('skip', str(skip)))
        metas, hints = client.catalog_with_hints(
            _CINEMETA, 'movie', catalog.get('id'), extra=extra,
        )
        print('  %s skip=%s metas=%d hasMore=%s cacheMaxAge=%s' % (
            year, skip, len(metas), hints.get('hasMore'), hints.get('cacheMaxAge'),
        ))
        return metas, hints.get('hasMore'), hints

    merged = merge_decade_pages(nineties['years'], fetch, max_pages=4)
    names = [meta.get('name') for meta in merged[:5]]
    print('1990s top5: %s (%d titles)' % (', '.join(names), len(merged)))
    if not merged:
        print('FAIL 1990s merge was empty')
        return 1
    top = (merged[0].get('popularities') or {}).get('moviedb')
    if not isinstance(top, (int, float)):
        print('FAIL top title has no popularities.moviedb')
        return 1

    transport, type_, id_, name = BUILTIN_ADDON_CATALOG_SOURCES[0]
    addons = fetch_addon_catalog(client, transport, type_, id_)
    print('addon catalog %s entries=%d first=%s' % (
        name, len(addons), (addons[0].get('manifest') or {}).get('name') if addons else '',
    ))
    if len(addons) < 10:
        print('FAIL addon catalog returned fewer than 10 addons')
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
