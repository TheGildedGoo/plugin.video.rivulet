# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""open_my_stuff(): the merged "My Stuff" screen - one grid combining
what the Home menu used to split across two rows ("Continue watching",
`lib.ui.continuewatching`, and "Library", `lib.ui.librarywindow`) plus a
third band those two never surfaced at all: titles finished recently.

The two old rows were already the same shape - build a list of meta
dicts, hand it to a coverflow - and they overlap heavily in practice (a
title you are part-way through is usually also in your library). Showing
them as separate destinations made the viewer guess which one held the
thing they wanted. This module merges both sources on their common
`(type, id)` key and renders the result as one labelled poster row per
band (`lib.ui.gridwindow`) - see `merge_entries()` for the merge and
`group_by_band()` for the split into rows.

Band ordering (the flat list is grouped, not sorted by one key):

    BAND_RESUME   part-way through, most recently touched first
    BAND_NEXT_UP  a series whose last episode is finished - the NEXT
                  episode is what the viewer actually wants
    BAND_RECENT   finished recently, nothing left to resume
    BAND_LIBRARY  saved but never played on this device

`BAND_NEXT_UP` is why finishing an episode is not the same as finishing
a title: at 99% of S1E2 the old "Continue watching" row dropped the show
entirely (its >=95% cutoff), exactly when the viewer most wants S1E3.
Resolving which episode that is needs the series meta, so the band is
computed here as "this series is next-up" and the actual episode is
resolved lazily by `lib.ui.binge.next_video()` once the meta is in hand
(see `resolve_next_up()`).

Everything above `open_my_stuff()` is a pure function of its arguments -
no store, no addon, no Kodi imports - so tests/test_mystuff.py exercises
every band with plain dicts.
"""
import threading
from typing import Dict

from lib.ui.dependencies import get_store

#: Progress band edges, as a percent of duration. Mirrors
#: `lib.ui.player`'s RESUME_MIN_PERCENT/RESUME_MAX_PERCENT, and matches
#: what `lib.ui.continuewatching` used before this module replaced it
#: (importing `lib.ui.player` for two floats would pull in its
#: xbmcplayer-derived playback machinery, which this module never needs).
RESUME_MIN_PERCENT = 1.0
RESUME_MAX_PERCENT = 95.0

#: Band identifiers, in display order. Carried on each merged entry as
#: `band`, so the grid can badge a card ("62%", "NEXT UP", "WATCHED")
#: without re-deriving which band it landed in.
BAND_RESUME = 'resume'
BAND_NEXT_UP = 'next_up'
BAND_RECENT = 'recent'
BAND_LIBRARY = 'library'

#: Display order of the bands - `merge_entries()` emits its flat list in
#: exactly this sequence.
BAND_ORDER = (BAND_RESUME, BAND_NEXT_UP, BAND_RECENT, BAND_LIBRARY)

#: band -> the localized-string id naming it. The grid names the band of
#: whichever title is focused (`gridwindow._caption()`), which is what
#: tells the viewer WHY that title is on the screen; the per-card badge
#: is the same information compressed to a colour and a few characters.
BAND_HEADINGS = {
    BAND_RESUME: 30245,
    BAND_NEXT_UP: 30242,
    BAND_RECENT: 30246,
    BAND_LIBRARY: 30247,
}

#: Cap on the number of titles fetched for the played bands (resume /
#: next-up / recent). Each one costs a `views._fetch_meta` fan-out on a
#: cache miss, so this bounds a cold open's worst case - the same reason
#: `lib.ui.continuewatching` capped its row at 15.
MAX_PLAYED_ITEMS = 24

#: Cap on library titles appended after the played bands. The library
#: needs no per-title fetch (the datastore entry already carries name and
#: poster), so this is a grid-length bound rather than a fetch bound and
#: can be far more generous.
MAX_LIBRARY_ITEMS = 200


def percent_watched(entry):
    """Percent of `entry`'s duration already watched, or None when the
    entry carries no usable duration (`duration_ms` missing, zero, or
    non-numeric) - the same tolerance `Store.get_progress_entries()`
    applies to a partly-corrupt cache file."""
    duration_ms = entry.get('duration_ms') or 0
    if not isinstance(duration_ms, (int, float)) or isinstance(duration_ms, bool):
        return None
    if duration_ms <= 0:
        return None
    position_ms = entry.get('position_ms') or 0
    if not isinstance(position_ms, (int, float)) or isinstance(position_ms, bool):
        return None
    return (position_ms / duration_ms) * 100.0


def _band_for(percent, content_type, entry=None):
    """Which band a single progress entry belongs to, or None when it is
    not worth surfacing at all.

    Below `RESUME_MIN_PERCENT` is "barely started" - a few seconds in,
    usually a stream the viewer opened and immediately backed out of, so
    it is dropped rather than presented as something to resume. At or
    above `RESUME_MAX_PERCENT` the title is finished: a series goes to
    `BAND_NEXT_UP` (the next episode is the real target - see the module
    docstring), anything else to `BAND_RECENT`.
    """
    # An account row with a positive offset but no measurable percent
    # (the next-episode pointer: timeOffset 1, duration 0) is still
    # Continue. A local sub-1% row stays dropped -- opening a stream
    # and backing straight out is not something to resume.
    if entry and entry.get('from_library'):
        position_ms = entry.get('position_ms') or 0
        if isinstance(position_ms, (int, float)) and not isinstance(position_ms, bool) and position_ms > 0:
            if percent is None or percent < RESUME_MIN_PERCENT:
                return BAND_RESUME
    if percent is None or percent < RESUME_MIN_PERCENT:
        return None
    if percent < RESUME_MAX_PERCENT:
        return BAND_RESUME
    return BAND_NEXT_UP if content_type == 'series' else BAND_RECENT


def latest_by_title(entries):
    """Reduce raw `Store.get_progress_entries()` dicts to one entry per
    `(type, id)` - the most recently updated - so a binged series shows
    once, not once per episode.

    Deliberately reduces BEFORE banding rather than after: the band of a
    series is a property of its LATEST episode (finished S1E2 -> next-up),
    and banding first would let an older half-watched episode outrank it
    and pin the show in `BAND_RESUME` forever. Returns a list sorted by
    `updated_at` descending (most recent first); entries with no usable
    percent are dropped here, since they can never land in a band.
    """
    best = {}
    for entry in entries or []:
        # Local rows with no duration cannot land in a band. Account
        # rows can: a next-episode pointer has timeOffset > 0 and
        # duration 0, and Continue still wants the show.
        position_ms = entry.get('position_ms') or 0
        keep_pointer = (
            entry.get('from_library')
            and isinstance(position_ms, (int, float))
            and not isinstance(position_ms, bool)
            and position_ms > 0
        )
        if percent_watched(entry) is None and not keep_pointer:
            continue
        key = (entry.get('type'), entry.get('id'))
        if key[1] is None:
            continue
        updated_at = entry.get('updated_at') or ''
        current = best.get(key)
        if current is None or updated_at > (current.get('updated_at') or ''):
            best[key] = entry
    return sorted(best.values(), key=lambda e: e.get('updated_at') or '', reverse=True)


def library_metas(entries):
    """Reduce a Stremio `libraryItem` datastore response to meta dicts,
    dropping entries the user removed and any without an `_id`.

    Newest `_ctime` first (the added time). A row with no `_ctime`
    falls back to `_mtime`, then stays in the order it arrived. Home's
    Library row and the library band both read this list.
    """
    kept = [
        entry for entry in entries or []
        if isinstance(entry, dict) and not entry.get('removed') and entry.get('_id')
    ]
    kept.sort(key=lambda entry: entry.get('_ctime') or entry.get('_mtime') or '', reverse=True)
    return [
        {
            'id': entry['_id'],
            'name': entry.get('name'),
            'type': entry.get('type'),
            'poster': entry.get('poster'),
            'background': entry.get('background'),
        }
        for entry in kept
    ]


def merge_entries(progress_entries, library_entries):
    """Merge local playback progress with the Stremio library into one
    banded, flat list of dicts:

        {'type', 'id', 'band', 'percent', 'video_id', 'updated_at',
         'name', 'poster', 'background', 'position_ms', 'duration_ms'}

    Played titles come first, in `BAND_ORDER`, each band most-recently-
    touched first; library titles never played on this device follow, in
    datastore order. A title present in BOTH sources appears exactly once
    - in its played band, enriched with the library's name/poster so the
    grid can draw it without waiting on an addon fetch.

    Either source may be empty: logged out (no library) still yields the
    played bands, and a fresh install with an empty cache still yields
    the library. Pure function - the caller does all I/O.
    """
    # Account rows fold in here, not in the Home window. Home, Continue
    # and Library all call this function, so a phone-side watch shows up
    # on those shelves without a layout change. The newer of local
    # updated_at and account lastWatched wins per episode.
    from lib.librarysync import merge_progress_sources

    library = library_metas(library_entries)
    by_key = {(meta.get('type'), meta.get('id')): meta for meta in library}
    progress = merge_progress_sources(progress_entries, library_entries)

    banded = {band: [] for band in BAND_ORDER}
    played_keys = set()
    for entry in latest_by_title(progress)[:MAX_PLAYED_ITEMS]:
        content_type = entry.get('type')
        percent = percent_watched(entry)
        band = _band_for(percent, content_type, entry)
        if band is None:
            continue
        key = (content_type, entry.get('id'))
        played_keys.add(key)
        known = by_key.get(key) or {}
        banded[band].append({
            'type': content_type,
            'id': entry.get('id'),
            'band': band,
            'percent': percent,
            'video_id': entry.get('video_id'),
            'updated_at': entry.get('updated_at'),
            'name': known.get('name') or entry.get('name'),
            'poster': known.get('poster') or entry.get('poster'),
            'background': known.get('background') or entry.get('background'),
            'position_ms': entry.get('position_ms'),
            'duration_ms': entry.get('duration_ms'),
        })

    merged = []
    for band in BAND_ORDER:
        merged.extend(banded[band])
    remaining = MAX_LIBRARY_ITEMS
    for meta in library:
        if remaining <= 0:
            break
        if (meta.get('type'), meta.get('id')) in played_keys:
            continue
        merged.append(dict(meta, band=BAND_LIBRARY, percent=None, video_id=None, updated_at=None))
        remaining -= 1
    return merged


def group_by_band(items):
    """Split the merged list into `[(band, [item, ...]), ...]` in
    `BAND_ORDER`, dropping bands with nothing in them.

    The grid draws one labelled row per band (see `lib.ui.gridwindow`),
    so this is the shape that screen consumes. Bands with no members are
    dropped rather than passed through empty: the skin would hide the row
    anyway, and an empty entry here would make the first-band focus in
    `GridWindow.onInit()` land on a row that is not drawn.
    """
    grouped = []
    for band in BAND_ORDER:
        members = [item for item in items or [] if item.get('band') == band]
        if members:
            grouped.append((band, members))
    return grouped


def resolve_next_up(item, meta):
    """For a `BAND_NEXT_UP` item, the `meta['videos']` entry after the
    episode the viewer just finished (`item['video_id']`), via
    `lib.ui.binge.next_video()` - or None when the series has no next
    episode (a finished final season), the meta carries no videos, or
    `item` is not in that band.

    Kept separate from `merge_entries()` on purpose: the merge is a pure
    local-cache operation, while this needs the series meta, which the
    caller only has after its fetch fan-out.
    """
    if not item or item.get('band') != BAND_NEXT_UP:
        return None
    video_id = item.get('video_id')
    if not video_id:
        return None
    from lib.ui.binge import next_video
    return next_video(meta, video_id)


def has_content(store):
    """Cheap gate for whether the Home "My Stuff" row should be shown at
    all - True iff the local progress cache holds at least one bandable
    entry, or the user is logged in (in which case they may have a
    library worth opening, which cannot be checked without a network
    call). `get_progress_entries()`/`get_auth()` are both pure local
    reads, so this is safe on every Home render."""
    if any(_band_for(percent_watched(e), e.get('type')) for e in latest_by_title(store.get_progress_entries())):
        return True
    return bool(store.get_auth())


# Writes that have been pushed and must show before the next
# datastoreGet echoes them. Keyed by `_id`. A later fetch drops a
# write once the account row is at least as new and agrees on `removed`.
_library_writes: Dict[str, dict] = {}
_library_write_lock = threading.Lock()


def clear_library_writes():
    """Test hook. Production never calls this."""
    with _library_write_lock:
        _library_writes.clear()


def note_library_write(item):
    """Remember a libraryItem this process just put.

    Home and the Library screen both read `_fetch_library_entries`.
    Painting from this copy is what makes Add and Remove show up
    without waiting for the account to echo the change.
    """
    if not isinstance(item, dict):
        return
    item_id = item.get('_id')
    if not item_id:
        return
    with _library_write_lock:
        _library_writes[item_id] = item


def _apply_library_writes(entries):
    with _library_write_lock:
        pending = dict(_library_writes)
    if not pending:
        return list(entries or [])
    out = []
    seen = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        item_id = entry.get('_id')
        overlay = pending.pop(item_id, None) if item_id else None
        if overlay is None:
            out.append(entry)
            if item_id:
                seen.add(item_id)
            continue
        remote_m = entry.get('_mtime') or ''
        local_m = overlay.get('_mtime') or ''
        if remote_m >= local_m and bool(entry.get('removed')) == bool(overlay.get('removed')):
            with _library_write_lock:
                current = _library_writes.get(item_id)
                if (
                    isinstance(current, dict)
                    and (current.get('_mtime') or '') <= remote_m
                    and bool(current.get('removed')) == bool(entry.get('removed'))
                ):
                    _library_writes.pop(item_id, None)
            out.append(entry)
        else:
            out.append(overlay)
        if item_id:
            seen.add(item_id)
    for item_id, item in pending.items():
        if item_id not in seen:
            out.append(item)
    return out


def _fetch_library_entries(store):
    """The user's Stremio library datastore, or [] when logged out or the
    call fails. A library failure must never sink the whole screen - the
    local played bands work fully offline and logged out, which is
    exactly the state a fresh device is in - so this logs and degrades to
    empty rather than propagating (`open_library()`'s old behaviour was
    to notify and show nothing at all)."""
    import xbmc

    from lib.stremio.api import ApiError, StremioAPI
    from lib.ui.compat import log

    auth = store.get_auth()
    if not auth:
        return []
    try:
        entries = StremioAPI().datastore_get(auth.get('authKey'), collection='libraryItem', all=True) or []
    except ApiError as exc:
        log('mystuff: datastore_get failed, showing local bands only: %r' % (exc,), xbmc.LOGWARNING)
        # A write this session already pushed still belongs on the row.
        return _apply_library_writes([])
    # Copy measured account positions into progress.json so the existing
    # resume prompt (which only reads the local cache) works on this
    # device. A seed failure must not hide the library itself.
    try:
        from lib.librarysync import seed_progress
        seed_progress(store, entries)
    except Exception as exc:  # noqa: BLE001 - Continue still renders from the rows just fetched
        log('mystuff: account progress seed failed: %r' % (exc,), xbmc.LOGWARNING)
    return _apply_library_writes(entries)


def _enrich(items):
    """Fill in name/poster for merged items that have none - the played
    bands on a logged-out device, where no library entry supplied them.

    Mirrors `lib.ui.continuewatching.open_continue_watching()`'s caching
    discipline exactly, and for the same measured reasons: each item is
    fetched with `views._fetch_meta(..., store=False)` so a cache-miss
    result is not written on its own, and every genuinely fresh result
    from the whole fan-out is written in ONE `store_cached_metas()` call
    afterwards. Cache HITS are deliberately excluded from that batch -
    `store_cached_metas()` re-stamps `ts` on everything it is given, so
    batching hits back in would re-arm every entry's TTL on every reopen
    and the cache would never re-check the addon as long as the screen
    keeps being reopened inside `metacache.TTL_SECONDS`.

    Returns `(metas, items)` filtered to the items that resolved to
    something showable, so the two stay index-aligned for the caller.
    """
    from lib.ui import views

    # A next-up item is fetched even when it already has name and poster:
    # those come from the library entry, which carries no `videos`, and
    # without that list `_label_next_episodes()` cannot say which episode
    # is next. That is the COMMON case - a series you are part-way through
    # is usually also in your library - so skipping it left the band
    # showing a bare "NEXT UP" exactly where the episode matters most.
    needs_fetch = [
        item for item in items
        if not item.get('name') or not item.get('poster') or item.get('band') == BAND_NEXT_UP
    ]
    if not needs_fetch:
        return items

    def _fetch(item):
        """One item's meta, plus whether it was a genuine cache miss - the
        flag `store_cached_metas()` below needs to avoid re-stamping TTLs
        on entries that were already cached."""
        was_fresh = []
        meta = views._fetch_meta(
            item['type'], item['id'], store=False,
            on_miss=lambda: was_fresh.append(True),
        )
        return meta, bool(was_fresh)

    # `_map_addons()` drops a None slot in place of the (meta, was_fresh)
    # tuple for an addon call that missed the soft deadline - treat it the
    # same as a failed fetch rather than crash unpacking None.
    fetched = [
        result if result is not None else (None, False)
        for result in views._map_addons(_fetch, needs_fetch)
    ]

    store = get_store()
    cache_dir = getattr(store, 'data_dir', None)
    if cache_dir is not None:
        from lib.ui.metacache import store_cached_metas
        store_cached_metas(cache_dir, [
            (item['type'], item['id'], meta)
            for item, (meta, was_fresh) in zip(needs_fetch, fetched)
            if meta and was_fresh
        ])

    for item, (meta, _was_fresh) in zip(needs_fetch, fetched):
        if not meta:
            continue
        item['name'] = item.get('name') or meta.get('name')
        item['poster'] = item.get('poster') or meta.get('poster')
        item['background'] = item.get('background') or meta.get('background')
        # The hero's right-quarter panel reads these. Copy only what this
        # fetch already returned; a library row with none of them stays
        # blank rather than triggering another request.
        for key in (
            'year', 'releaseInfo', 'released', 'runtime', 'imdbRating',
            'genres', 'rottenTomatoes', 'rtRating', 'tomatoMeter',
            'metascore', 'metacritic', 'ratings',
        ):
            if item.get(key) or meta.get(key) in (None, '', []):
                continue
            item[key] = meta[key]
        # Kept for resolve_next_up(): the grid never draws `videos`, but
        # re-fetching the same meta later just to answer "which episode
        # is next" would double this screen's addon traffic.
        if item.get('band') == BAND_NEXT_UP and meta.get('videos'):
            item['videos'] = meta['videos']
    return [item for item in items if item.get('name')]


def _label_next_episodes(items):
    """Fill in `next_label` ("S1E3") on every next-up item whose series
    meta `_enrich()` already fetched, so the card can name the episode it
    would actually play rather than a bare "NEXT UP".

    Uses the `videos` list `_enrich()` stashed on the item, so this costs
    no extra addon traffic.

    Also demotes a series that turns out to have NO next episode: if its
    meta arrived and nothing follows the episode just finished, the title
    is finished rather than next-up, so it moves to `BAND_RECENT` before
    `group_by_band()` splits the list. An item whose meta never arrived is
    left where it is - with no `videos` there is no way to tell "final
    season" from "not fetched yet". Mutates `items` in place, like the
    enrich pass above it.
    """
    for item in items:
        if item.get('band') != BAND_NEXT_UP:
            continue
        videos = item.get('videos') or []
        video = resolve_next_up(item, {'videos': videos})
        if not video:
            # No next episode. If the meta actually arrived and simply has
            # nothing after this one - a finished final season - the title
            # is not "next up" at all; it is finished, and belongs with the
            # other watched titles. Without a meta we cannot tell the two
            # apart, so the band is left alone and the card keeps its
            # unqualified "NEXT UP".
            if videos:
                item['band'] = BAND_RECENT
            continue
        season, episode = video.get('season'), video.get('episode')
        if season is None or episode is None:
            continue
        from lib.ui.playbackmeta import episode_code
        item['next_label'] = episode_code(season, episode)


def _restrict_bands(items, bands):
    """Keep entries whose `band` is in `bands`.

    `None` is Continue: every band, unchanged. Home's Watch Later row
    passes `(BAND_LIBRARY,)` so the grid shows saved titles that have
    not been started on this device and nothing else. This filters the
    list `merge_entries()` already built. It does not read another
    datastore collection, and it does not ask the catalog addons for
    anything the unfiltered screen would not have asked for.
    """
    if bands is None:
        return items
    wanted = frozenset(bands)
    return [item for item in items if item.get('band') in wanted]


def _empty_notice(bands, signed_in):
    """The notification when the grid would open empty.

    Continue keeps its existing "nothing here" string. Watch Later says
    why: signed out there is no library to read, and signed in the
    library may exist but every saved title was already started (those
    live on Continue).
    """
    from lib.ui.compat import L

    if bands is None:
        return L(30030)
    if not signed_in:
        return L(30424)
    return L(30426)


def open_my_stuff(bands=None):
    """Fetch both sources, merge them, and show the result in the grid.

    `bands` limits which bands are drawn (see `_restrict_bands`). The
    default, `None`, is the Continue screen and must stay that way:
    Home calls this with no argument. Returns True if the caller
    (HomeWindow) should also close (playback started somewhere down
    the open_detail() chain)."""
    import xbmc

    from lib.ui.compat import L, log, notify
    from lib.ui.uicommon import CANCELLED, run_cancellable

    store = get_store()

    def _load():
        # Restrict before `_enrich`: a Watch Later open must not fan out
        # a meta fetch for every in-progress title just to throw those
        # rows away. Library entries already carry name and poster.
        merged = merge_entries(store.get_progress_entries(), _fetch_library_entries(store))
        merged = _restrict_bands(merged, bands)
        items = _enrich(merged)
        _label_next_episodes(items)
        return items

    items = run_cancellable(_load, L(30033))
    if items is CANCELLED:
        return False

    if not items:
        notify(_empty_notice(bands, bool(store.get_auth())))
        return False

    if bands is None:
        heading = L(30241)
    else:
        heading = L(30422)

    log('mystuff: opening grid (%d items)' % len(items), xbmc.LOGINFO)
    try:
        from lib.ui.gridwindow import open_grid
        selected = open_grid(group_by_band(items), heading=heading)
    except Exception as exc:  # a skin/UI failure must surface, not vanish
        log('mystuff: grid failed to open: %r' % (exc,), xbmc.LOGERROR)
        notify(L(30032))
        return False
    if not selected:
        return False

    from lib.ui.detailwindow import open_detail
    return open_detail(selected.get('type'), selected.get('id'))
