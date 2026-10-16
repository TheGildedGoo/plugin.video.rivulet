# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Binge-watching: "what plays next" - pure logic, no Kodi imports, so
every branch here is exercised directly by tests/test_binge.py with
plain dicts (no tests/kodistubs fakes needed).

Upstream (`stremio-core`) treats "which video comes after this one" and
"which of its streams to auto-play" as two separate, always-computed
questions - `next_video_update()`/`next_streams_update()`/
`next_stream_update()` in `src/models/player.rs` populate `Player.next_video`/
`.next_streams`/`.next_stream` unconditionally; commit 632ef1503e
("fix(Player): next_video streams population", 2025-11-27) even strips
the last `ProfileSettings.binge_watching` check out of
`next_stream_update()` entirely, and commit dad7d619d5 ("fix: player -
populate next_video regardless of User's binge_watching setting",
2025-10-23) does the same one layer up - the user's binge-watching
setting only ever gates whether the picked stream gets AUTO-PLAYED, not
whether it gets computed. `lib.ui.streamswindow` mirrors that split:
this module always answers "what's next" and "which stream matches",
and `streamswindow._try_binge_watch()` is the one place that reads the
Kodi-side 'binge_enable' setting before ever calling in here.

`next_video()` mirrors `types::resource::meta_item::MetaItem::next_video()`
(walks the SAME season/episode-then-release-date ordering
`types::library::library_item::LibraryItemState::watched_bitfield()` sorts
by, lines 264-305) plus its "never cross from a real episode into season 0
Specials" guard (meta_item.rs lines 271-291: the filter rejects a next
candidate whose season is 0 unless the CURRENT video is already in season
0 too). Rivulet additionally treats a video with no season/episode at all
(a malformed/partial addon response) the same as a Special - missing
series_info, deliberately, is exactly as unfit to silently "continue" from
as season 0 is.

`pick_binge_stream()` mirrors `types::resource::stream::Stream::is_binge_match()`
(stream.rs lines 140-149: two streams "binge-match" only when both carry a
`behaviorHints.bingeGroup` and it's equal) plus the Kodi-side fallback the
Rust model leaves to its caller: `sort_streams()` has already ranked the
next episode's own pairs by quality, so "no match" falls back to the best
of THOSE rather than nothing at all.
"""


def next_video(meta, current_video_id):
    """Return the `meta['videos']` entry that follows `current_video_id`
    in season/episode/release-date order, or `None` when there is none -
    including when `current_video_id` isn't found at all, or the next
    entry in order would cross from a real episode into season-0
    Specials (or a video with no season/episode info at all - see the
    module docstring).
    """
    videos = (meta or {}).get('videos') or []
    ordered = sorted(videos, key=_sort_key)

    position = None
    for index, video in enumerate(ordered):
        if video.get('id') == current_video_id:
            position = index
            break
    if position is None or position + 1 >= len(ordered):
        return None

    current, candidate = ordered[position], ordered[position + 1]
    current_season = current.get('season') or 0
    candidate_season = candidate.get('season') or 0
    if candidate_season == 0 and current_season != 0:
        return None
    return candidate


def _sort_key(video):
    """(season==0-or-missing, season, episode, released) ascending -
    Specials/missing-series-info sort after every real season (matching
    `lib.ui.detailwindow._ordered_videos()`'s existing "Specials last"
    convention, which is also exactly what makes `next_video()`'s season-0
    guard above reachable: without it, a regular season finale's "next"
    slot in this ordering IS the first Special/malformed entry), with
    release date (ISO 8601 strings sort correctly as plain text) as the
    final tiebreaker for entries that tie on season/episode - mirroring
    `LibraryItemState::watched_bitfield()`'s three-key sort shape."""
    season = video.get('season') or 0
    episode = video.get('episode') or 0
    return (season == 0, season, episode, video.get('released') or '')


def pick_binge_stream(pairs, binge_group):
    """From `pairs` (the next episode's own already-fetched, already
    quality-sorted `(info, stream)` list - see `sort_streams()`), return
    the first pair whose `info['binge_group']` equals `binge_group` (the
    just-played stream's own binge group - same release group/quality,
    which is precisely what `behaviorHints.bingeGroup` is for), or the
    first pair otherwise. `None` only when `pairs` itself is empty.
    """
    if binge_group:
        for pair in pairs:
            info, _stream = pair
            if info.get('binge_group') == binge_group:
                return pair
    return pairs[0] if pairs else None


#: Known heights only. Copied from `streaminfo._RESOLUTION_HEIGHT` rather
#: than imported so this module stays a pure function of the pairs it is
#: handed. An unparsed resolution is not a height, and `pick_up_next_stream`
#: ranks it below every known one instead of dropping it.
_KNOWN_HEIGHTS = {'2160p': 2160, '1080p': 1080, '720p': 720, '480p': 480}


def _known_height(info):
    return _KNOWN_HEIGHTS.get((info or {}).get('resolution') or '')


def pick_up_next_stream(pairs, binge_group, max_height=0, cached_only=False):
    """The stream Up next auto-plays.

    `pairs` is the next episode's own list, in whatever order the caller
    sorted. `max_height` 0 means no cap. A known height above the cap is
    dropped; an unknown height is kept (same rule as
    `streaminfo.filter_streams`: an unparsed title is not the same thing
    as a 4K file).

    Preference, highest known height first:

    1. A stream `parse_stream` marked cached (`info['cached'] is True`).
       The debrid name and emoji markers live in that flag; this function
       does not re-read the title.
    2. When nothing is cached and `cached_only` is set, `None`. The caller
       does not auto-play.
    3. Otherwise the best remaining stream, same height rule.

    `binge_group` only breaks a tie inside that winning height and cache
    class. It does not pick a lower or uncached stream over a cached
    higher one. `None` when nothing is eligible.
    """
    eligible = []
    for pair in pairs or []:
        info = pair[0] if pair else None
        height = _known_height(info)
        if max_height and height is not None and height > max_height:
            continue
        eligible.append(pair)
    cached = [pair for pair in eligible if (pair[0] or {}).get('cached') is True]
    if cached:
        pool = cached
    elif cached_only:
        return None
    else:
        pool = eligible
    if not pool:
        return None

    def _rank(pair):
        height = _known_height(pair[0] if pair else None)
        # Known heights outrank an unparsed title. The boolean sorts
        # above False, so (True, 2160) beats (True, 1080) beats (False, 0).
        return (height is not None, height or 0)

    best = max(_rank(pair) for pair in pool)
    band = [pair for pair in pool if _rank(pair) == best]
    if binge_group:
        for pair in band:
            if (pair[0] or {}).get('binge_group') == binge_group:
                return pair
    return band[0]
