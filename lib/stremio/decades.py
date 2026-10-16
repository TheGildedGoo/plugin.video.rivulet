# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Decade tiles for a catalog whose required genre options are years.

Detection is the shape of the manifest, not the host and not the catalog
id. A required ``genre`` whose every option is a four-digit year is the
Movies hub's "New" row (Cinemeta ``movie/year``). Anything else, including
a genre list that mixes years with words, is not.

The tiles stop at the 1960s. Older years in the manifest are ignored, and
a 1910s tile is never invented. The current decade is still labelled
``2020s`` when it only contains the years the manifest actually lists.

The year feed is newest-first, so the film people mean is often past the
first page. ``merge_decade_pages`` walks up to four pages per year and
sorts by ``popularities.moviedb``, then ``popularity``, then ``imdbRating``.
"""

import queue
import re
import threading

from lib.stremio.addons import catalog_extra_options, catalog_required_extra_names

#: Oldest decade tile. Years before this stay off the row.
DECADE_FLOOR = 1960

#: Pages per year. Four is what put Shawshank on the 1994 list; one page
#: is the obscure head of that feed and is not a successful decade.
DECADE_MAX_PAGES = 4

#: Coverflow bound after the popularity sort. The fetch itself is already
#: bounded by the page cap; this only stops a dense decade from handing
#: the skin every meta those pages returned.
DECADE_RESULT_CAP = 240

#: This fan-out's own pool. Not shared with catalog or stream workers:
#: each site bounds itself for the same low-power boxes.
_MAX_DECADE_WORKERS = 8

_YEAR = re.compile(r'^\d{4}$')


def is_year_catalog(catalog):
    """True when the only required extra (ignoring ``skip``) is ``genre``
    and every declared genre option is a four-digit year.

    Fail closed: one non-year option means this is an ordinary genre row,
    and the caller keeps today's "first option" behaviour.
    """
    if not isinstance(catalog, dict):
        return False
    required = catalog_required_extra_names(catalog) - {'skip'}
    if required != {'genre'}:
        return False
    options = catalog_extra_options(catalog, 'genre')
    if not options:
        return False
    return all(_YEAR.match(option) for option in options)


def decade_tiles(options, floor=DECADE_FLOOR):
    """``[{label, start, years}, ...]``, newest decade first.

    ``years`` are the four-digit strings the manifest listed for that
    decade, newest first, and only those ``>= floor``. An empty list
    means the manifest has no year in range; the caller draws nothing
    rather than inventing a tile.
    """
    by_decade = {}
    for option in options or []:
        if not _YEAR.match(option):
            return []
        year = int(option)
        if year < floor:
            continue
        start = (year // 10) * 10
        by_decade.setdefault(start, []).append(year)
    tiles = []
    for start in sorted(by_decade, reverse=True):
        years = sorted(by_decade[start], reverse=True)
        tiles.append({
            'label': '%ds' % start,
            'start': start,
            'years': ['%d' % year for year in years],
        })
    return tiles


def _number(value):
    """A finite float, or None. Booleans are not ratings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _sort_key(meta):
    """Missing numbers sort last. Present numbers sort high to low."""
    pops = meta.get('popularities') if isinstance(meta, dict) else None
    moviedb = _number(pops.get('moviedb')) if isinstance(pops, dict) else None
    popularity = _number(meta.get('popularity')) if isinstance(meta, dict) else None
    rating = _number(meta.get('imdbRating')) if isinstance(meta, dict) else None

    def part(number):
        if number is None:
            return (1, 0.0)
        return (0, -number)

    return part(moviedb) + part(popularity) + part(rating)


def _as_page(result):
    """``fetch`` may return ``(metas, has_more)`` or ``(metas, has_more, hints)``."""
    if isinstance(result, tuple):
        metas = result[0] if result else []
        has_more = result[1] if len(result) > 1 else None
    else:
        metas = result
        has_more = None
    if not isinstance(metas, list):
        metas = []
    if has_more is not None and not isinstance(has_more, bool):
        has_more = None
    return metas, has_more


def _collect_year(year, fetch, max_pages):
    """Up to ``max_pages`` for one year. A short page or ``hasMore`` false
    stops early. A failure keeps the pages already in hand and does not
    propagate: the other years of the decade still merge.
    """
    collected = []
    skip = 0
    first_len = None
    for _page in range(max_pages):
        try:
            metas, has_more = _as_page(fetch(year, skip))
        except Exception:
            break
        if not metas:
            break
        collected.extend(meta for meta in metas if isinstance(meta, dict))
        page_len = len(metas)
        if first_len is None:
            first_len = page_len
        if has_more is False or page_len < first_len:
            break
        skip += page_len
    return collected


def merge_decade_pages(years, fetch, max_pages=DECADE_MAX_PAGES, workers=_MAX_DECADE_WORKERS):
    """Merge ``fetch(year, skip)`` across ``years`` and sort by popularity.

    ``fetch`` raises for a hung year; that year contributes only the pages
    it already returned. Ids are deduped, first occurrence kept, then the
    whole list is sorted. A 1-page cap is a different call, not a success
    for a feed whose popular title starts on a later page.
    """
    years = [year for year in (years or []) if year]
    if not years:
        return []
    buckets = [None] * len(years)
    work = queue.Queue()
    for index, year in enumerate(years):
        work.put((index, year))

    def _worker():
        while True:
            try:
                index, year = work.get_nowait()
            except queue.Empty:
                return
            buckets[index] = _collect_year(year, fetch, max_pages)

    count = min(len(years), max(1, workers))
    threads = []
    for _index in range(count):
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

    seen = set()
    merged = []
    for bucket in buckets:
        for meta in bucket or []:
            meta_id = meta.get('id')
            if meta_id is not None:
                if meta_id in seen:
                    continue
                seen.add(meta_id)
            merged.append(meta)
    merged.sort(key=_sort_key)
    if len(merged) > DECADE_RESULT_CAP:
        return merged[:DECADE_RESULT_CAP]
    return merged
