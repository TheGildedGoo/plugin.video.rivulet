# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Pure-Python LibraryItem construction and playback-progress merging --
Rivulet's half of what stremio-core calls the "library" ctx layer (no
``xbmc*`` imports anywhere in this module, so it is safe to unit test
with a plain ``python3`` interpreter).

Wire shape verified against ``~/M0Rf30/stremio-core`` (read-only checkout,
HEAD 7f69095a):

* ``src/types/library/library_item.rs:17-42`` (``LibraryItem`` field names
  and casing -- ``_id``/``_ctime``/``_mtime`` keep their underscore
  prefix, every other field is ``camelCase``) and ``:215-261``
  (``LibraryItemState`` -- ``timeWatched``/``timeOffset``/
  ``overallTimeWatched``/``duration`` are all MILLISECONDS; ``video_id``
  is the one field that keeps its snake_case wire name -- an explicit
  ``#[serde(rename = "video_id")]`` on an otherwise
  ``rename_all = "camelCase"`` struct).
* ``src/types/library/library_item.rs:176-195`` (``From<(&MetaItemPreview,
  PhantomData<E>)>`` -- the exact constructor stremio-core's own ctx
  layer uses the first time a title is watched without ever having been
  explicitly "Added to Library": ``removed``/``temp`` both start
  ``true``. See :func:`build_library_item`.
* ``src/types/library/library_item.rs:244-250`` (``state.video_id``'s doc
  comment) and ``src/models/player.rs:523-577``
  (``ActionPlayer::TimeChanged``'s handler -- the merge logic
  :func:`merge_playback` below mirrors step for step).
* ``src/unit_tests/ctx/add_to_library.rs:35-37`` pins the exact
  ``datastorePut`` wire body (key names, order, and ``null``/``0``/
  ``false`` defaults) that ``lib.stremio.api.StremioAPI.datastore_put``
  posts -- every dict this module builds uses that exact key order so a
  caller can hand one straight to ``datastore_put`` unmodified.

CRITICAL -- read this before touching ``state.watched`` anywhere:
``state.watched`` is a ``stremio-watched-bitfield`` string (see
:mod:`lib.stremio.watchedbitfield`). :func:`merge_playback` and
:func:`mark_watched_payload` NEVER compute or touch it -- a periodic
sample and an explicit series-level flag are not an episode bitmap.
:func:`finish_playback` is the only writer, and only when the existing
string parses against the show's video ids. An unparseable string, or
one whose anchor video is not in that list, is copied through
byte-for-byte. Replacing it with a blank or a guess would wipe the
user's real Stremio library the next time an official client read it.
"""
import datetime

from lib.stremio import watchedbitfield

#: Default `posterShape` for a freshly-built item. stremio-core's own
#: `PosterShape` enum defaults to `Poster` for anything else
#: (`#[default]` variant, src/types/resource/meta_item.rs:307-315).
DEFAULT_POSTER_SHAPE = 'poster'

#: Fraction of a video's `duration` that `state.timeWatched` must exceed
#: before this addon flags it "watched" (`flaggedWatched=1`, `timesWatched`
#: incremented once -- see `merge_playback`).
#:
#: NOTE: stremio-core's own player model uses a DIFFERENT, lower
#: coefficient for this exact check (`WATCHED_THRESHOLD_COEF = 0.7`,
#: src/constants.rs:43, consumed by `ActionPlayer::TimeChanged` at
#: src/models/player.rs:571-573) -- this addon deliberately requires a
#: stricter 90% instead (project decision for this feature), so the real
#: upstream figure is documented here rather than left for a future
#: reader to assume this constant is upstream-verified.
WATCHED_THRESHOLD_RATIO = 0.9

#: Every `LibraryItemState` time field is milliseconds on the wire
#: (library_item.rs:228-243); a playback position sampled off Kodi's own
#: `xbmc.Player.getTime()`/`getTotalTime()` is seconds (float). Callers
#: doing that conversion (see `lib.service_runner`) multiply by this
#: rather than a bare magic `1000`.
MS_PER_SECOND = 1000


def iso8601_utc(dt=None):
    """Format `dt` (default: now) as upstream's `_ctime`/`_mtime`/
    `state.lastWatched` wire format -- seconds-precision ISO 8601 UTC
    with a literal 'Z' suffix, matching chrono's `DateTime<Utc>`
    Serialize impl for a timestamp with no fractional seconds (see the
    pinned `"2020-01-01T00:00:00Z"` values in
    src/unit_tests/ctx/add_to_library.rs:37,65-68). A naive `dt` (no
    tzinfo) is treated as already being UTC.
    """
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _default_state(now_iso):
    """A brand-new `LibraryItemState` dict, key order matching the
    pinned `datastorePut` fixture exactly (`lastWatched` first, `watched`/
    `noNotif` last) -- see the module docstring."""
    return {
        'lastWatched': now_iso,
        'timeWatched': 0,
        'timeOffset': 0,
        'overallTimeWatched': 0,
        'timesWatched': 0,
        'flaggedWatched': 0,
        'duration': 0,
        'video_id': None,
        'watched': None,
        'noNotif': False,
    }


def _behavior_hints(meta):
    """`MetaItemBehaviorHints`'s 3 named wire fields (src/types/resource/
    meta_item.rs:422-431), read off `meta['behaviorHints']` with
    upstream's own per-field defaults. Any OTHER key that dict carries
    (upstream flattens unknown keys into a separate `.other` map) is
    dropped -- a `LibraryItem.behaviorHints` on the wire only ever has
    these three."""
    hints = (meta or {}).get('behaviorHints') or {}
    return {
        'defaultVideoId': hints.get('defaultVideoId'),
        'featuredVideoId': hints.get('featuredVideoId'),
        'hasScheduledVideos': bool(hints.get('hasScheduledVideos', False)),
    }


def build_library_item(meta, now=None):
    """Build a brand-new LibraryItem dict from a Stremio meta dict
    (`{'id', 'type', 'name', 'poster', 'posterShape', 'behaviorHints'}` --
    every key but `id` optional).

    Mirrors stremio-core's `From<(&MetaItemPreview, PhantomData<E>)>`
    (library_item.rs:176-195) field for field: `removed`/`temp` both
    start `true`. This is the SAME constructor stremio-core's own ctx
    layer uses the very first time a title is watched without ever
    having been explicitly "Added to Library" (see
    models/ctx/update_library.rs:159-163's `MetaItemMarkAsWatched`
    branch) -- it produces exactly the transient "recently watched, not
    in your library" record every official Stremio client also creates,
    never a permanent library entry (an explicit "Add to Library" action
    is what would flip `removed`/`temp` to `false` -- outside this
    module's scope).
    """
    now_iso = iso8601_utc(now)
    return {
        '_id': meta['id'],
        'name': meta.get('name', ''),
        'type': meta.get('type', ''),
        'poster': meta.get('poster'),
        'posterShape': meta.get('posterShape') or DEFAULT_POSTER_SHAPE,
        'removed': True,
        'temp': True,
        '_ctime': now_iso,
        '_mtime': now_iso,
        'state': _default_state(now_iso),
        'behaviorHints': _behavior_hints(meta),
    }


def _resolve_video_id(item, video_id):
    """The fallback chain library_item.rs:244-250 documents for
    `state.video_id`: the actually-played episode id when given, else
    `behaviorHints.defaultVideoId`, else the item's own `_id` (a movie,
    or any meta with no separate episodes, has no other video to name)."""
    if video_id:
        return video_id
    default_video_id = (item.get('behaviorHints') or {}).get('defaultVideoId')
    if default_video_id:
        return default_video_id
    return item.get('_id')


def merge_playback(item, position_ms, duration_ms, video_id=None, now=None):
    """Return a NEW LibraryItem dict (`item` is never mutated) merging
    one playback sample into `item['state']` -- mirrors stremio-core's
    `ActionPlayer::TimeChanged` handler (src/models/player.rs:523-577)
    step for step:

    1. `state.lastWatched` = now.
    2. Resolve the played video id (see `_resolve_video_id`). If it
       differs from the item's CURRENT `state.video_id` (a fresh item,
       or the user moved to a different episode): fold the old video's
       `timeWatched` into `overallTimeWatched` and restart
       `timeWatched`/`flaggedWatched` at 0 for the new video.
    3. Otherwise (same video as last sample): the delta since the
       item's last known `timeOffset` -- never negative, so a backward
       seek cannot *subtract* watched time -- is added to both
       `timeWatched` and `overallTimeWatched`.
    4. `timeOffset`/`duration` only advance when `position_ms` is
       actually AHEAD of the stored `timeOffset` -- guards against a
       backward seek corrupting the resume position (upstream's own
       comment: "if we seek forward, time will be < time_offset [...]
       for both backward and forward seeking we expect the apps to send
       the right actions").
    5. The first time (and only the first time -- gated by
       `flaggedWatched == 0`) `timeWatched` exceeds
       `duration_ms * WATCHED_THRESHOLD_RATIO`, `flaggedWatched` flips
       to 1 and `timesWatched` increments by exactly one.

    `state.watched` -- the per-episode `stremio-watched-bitfield` this
    addon does not implement -- is copied over completely UNTOUCHED, see
    the module docstring's CRITICAL note. Every other top-level field
    (`removed`/`temp`/`name`/`poster`/`behaviorHints`/...) is copied
    unchanged; only `_mtime` and `state` differ in the result.

    `position_ms`/`duration_ms` are clamped to `>= 0` (a negative sample
    -- e.g. a bogus `getTime()` reading -- must never corrupt stored
    progress); an item with no prior `state` at all gets a fresh default
    one first.

    Only shallow-copies what it actually mutates -- the top-level dict
    and `state` -- rather than `copy.deepcopy`-ing the whole item (which
    can run 8-12 KB, sampled on every playback-progress tick). Every
    field this function never writes (`poster`, `behaviorHints`, and
    `state.watched` itself) is carried into the result BY REFERENCE,
    shared with `item`'s own copy of it -- safe precisely because
    nothing below ever mutates one of those shared objects in place.
    """
    now_iso = iso8601_utc(now)
    original_state = item.get('state')
    if isinstance(original_state, dict):
        state = dict(original_state)
    else:
        state = _default_state(now_iso)

    position_ms = max(0, int(position_ms))
    duration_ms = max(0, int(duration_ms))
    resolved_video_id = _resolve_video_id(item, video_id)
    previous_offset = int(state.get('timeOffset') or 0)

    state['lastWatched'] = now_iso

    if state.get('video_id') != resolved_video_id:
        state['overallTimeWatched'] = int(state.get('overallTimeWatched') or 0) + int(state.get('timeWatched') or 0)
        state['timeWatched'] = 0
        state['flaggedWatched'] = 0
        state['video_id'] = resolved_video_id
        # A NEW video starts its own timeline: the previous video's
        # timeOffset/duration are meaningless for it (e.g. episode 1
        # finished at 100000ms, episode 2 starts at position~0) --
        # written directly (not just the local `previous_offset` below)
        # so a call landing at EXACTLY position_ms=0 for the new video
        # still clears the stale value (the `position_ms >
        # previous_offset` guard a few lines down is a strict `>`, so a
        # merely-reset local variable would leave `state['timeOffset']`
        # itself untouched for that one boundary sample). Upstream
        # achieves the same reset via a SEPARATE explicit
        # `advance_to_video`/next-video action fired before its own
        # TimeChanged; this addon has no such separate step, so the
        # reset lives here instead.
        state['timeOffset'] = 0
        state['duration'] = 0
        previous_offset = 0
    else:
        delta = max(0, position_ms - previous_offset)
        state['timeWatched'] = int(state.get('timeWatched') or 0) + delta
        state['overallTimeWatched'] = int(state.get('overallTimeWatched') or 0) + delta

    if position_ms > previous_offset:
        state['timeOffset'] = position_ms
        state['duration'] = duration_ms

    if not state.get('flaggedWatched') and duration_ms > 0 and state['timeWatched'] > duration_ms * WATCHED_THRESHOLD_RATIO:
        state['flaggedWatched'] = 1
        state['timesWatched'] = int(state.get('timesWatched') or 0) + 1

    item = dict(item)
    item['state'] = state
    item['_mtime'] = now_iso
    return item


def library_add_payload(meta, now=None):
    """Build the LibraryItem an EXPLICIT "Add to Library" action pushes --
    the branch `build_library_item()`'s own docstring named but left
    "outside this module's scope" (library_item.rs:176-195's PhantomData
    constructor only ever produces the IMPLICIT `removed=True`/
    `temp=True` "recently watched, never added" record). Reuses
    `build_library_item()` for every other field (identity/type/name/
    poster/behaviorHints, a brand-new `state`) and flips just those two
    flags to `False` -- the wire signal that this record is a real,
    permanent library entry rather than a transient one.

    Deliberately built fresh from `meta` alone, never from any existing
    server-side record for this id: this addon caches no library items
    (`lib.ui.mystuff._fetch_library_entries()` re-fetches live every
    time for the same reason), and an explicit "Add" from a title the
    user has never played has no prior `state` to preserve anyway. A
    title that already has a `removed=True` implicit record (e.g. from
    `lib.service_runner`'s playback-progress push) simply gets that
    record's tombstone flag cleared by this same fresh payload landing
    on the SAME `_id` key server-side -- its `state` is not carried
    forward, matching the narrow "meta only" shape this function is
    given.
    """
    item = build_library_item(meta, now)
    item['removed'] = False
    item['temp'] = False
    return item


def library_add_from_existing(meta, existing=None, now=None):
    """The ``datastorePut`` body for an explicit Add to Library.

    ``existing`` is the account row pulled immediately before the put.
    Its ``state`` is kept, so the write does not replace another
    client's playback with a blank record. ``removed`` and ``temp``
    become false. ``_mtime`` is now. ``_ctime`` is now when the row is
    new or was a tombstone, which is the added time Library sorts on.
    An item that is already in the library keeps its original
    ``_ctime``. With no account row this is :func:`library_add_payload`.
    """
    meta = meta or {}
    if not isinstance(existing, dict) or not existing.get('_id'):
        return library_add_payload(meta, now)
    now_iso = iso8601_utc(now)
    result = dict(existing)
    state = result.get('state')
    result['state'] = dict(state) if isinstance(state, dict) else _default_state(now_iso)
    was_removed = bool(result.get('removed'))
    result['removed'] = False
    result['temp'] = False
    result['_mtime'] = now_iso
    if was_removed or not result.get('_ctime'):
        result['_ctime'] = now_iso
    if meta.get('name') and not result.get('name'):
        result['name'] = meta.get('name')
    if meta.get('type') and not result.get('type'):
        result['type'] = meta.get('type')
    if meta.get('poster') and not result.get('poster'):
        result['poster'] = meta.get('poster')
    return result


def library_remove_payload(item, now=None):
    """Return a NEW LibraryItem dict (`item` is never mutated) flagging
    `item` removed -- Stremio's library "delete" is a tombstone
    (`removed=True`), never an actual deletion, precisely so the removal
    itself syncs to every other device on the next `datastoreGet`
    instead of the record just vanishing locally and resurrecting the
    moment another device's own pull re-adds it.

    Every OTHER field of `item` -- including `temp`, `state`, and
    everything else `library_add_payload()`/`merge_playback()` may have
    already set -- is carried through completely unchanged; only
    `removed` and `_mtime` differ in the result, the same "only
    shallow-copy what actually changed" shape `merge_playback()` already
    uses above.
    """
    result = dict(item)
    result['removed'] = True
    result['_mtime'] = iso8601_utc(now)
    return result


def mark_watched_payload(item, watched, now=None):
    """Return a NEW LibraryItem dict (`item` is never mutated) setting
    `item['state']['flaggedWatched']` to `watched` -- the explicit
    "Mark as watched"/"Mark as unwatched" action, using exactly the
    `flaggedWatched`/`timesWatched` pair `merge_playback()` already
    flips automatically at the 90% threshold (see
    `WATCHED_THRESHOLD_RATIO`); this function just lets the user set the
    same two fields by hand instead of waiting for enough playback.

    `timesWatched` increments by exactly one ONLY on the 0->1
    transition (`flaggedWatched` was falsy and `watched` is True) --
    mirrors `merge_playback()`'s own "gated by flaggedWatched == 0"
    increment, and is what makes this function idempotent: feeding its
    own output back in with the same `watched` value is a no-op past the
    first call, since the second call's `was_watched` reads back the
    `True` the first call just wrote. Marking unwatched never
    decrements `timesWatched` -- that counter is a history of how many
    times the title WAS completed, not a live flag, so un-marking must
    not erase that history.

    An `item` with no `state` at all yet (never played, never added)
    gets a fresh default one first, same as `merge_playback()`. The
    `state.watched` per-episode bitfield is never touched here either --
    see the module docstring's CRITICAL note; this function only ever
    writes `flaggedWatched`/`timesWatched`.
    """
    now_iso = iso8601_utc(now)
    original_state = item.get('state')
    state = dict(original_state) if isinstance(original_state, dict) else _default_state(now_iso)

    was_watched = bool(state.get('flaggedWatched'))
    state['flaggedWatched'] = 1 if watched else 0
    if watched and not was_watched:
        state['timesWatched'] = int(state.get('timesWatched') or 0) + 1

    result = dict(item)
    result['state'] = state
    result['_mtime'] = now_iso
    return result


def apply_library_flags(item):
    """Return a NEW LibraryItem with the player's ``removed``/``temp`` rules.

    After every library write, stremio-core's player does two assignments
    and nothing else to those flags: if the record is still ``temp`` and
    ``timesWatched`` is still 0, force ``removed``; then if it is
    ``removed``, force ``temp``. An explicit library add (both flags
    false) stays in the library. A temp record that has already been
    counted watched is not forced back to ``removed`` by the first
    assignment, and a record that was already ``removed`` stays removed.
    ``state`` is shallow-copied so the caller can keep mutating the
    result; it is not otherwise changed.
    """
    result = dict(item)
    state = result.get('state')
    result['state'] = dict(state) if isinstance(state, dict) else state
    times_watched = 0
    if isinstance(result.get('state'), dict):
        times_watched = int(result['state'].get('timesWatched') or 0)
    if result.get('temp') and times_watched == 0:
        result['removed'] = True
    if result.get('removed'):
        result['temp'] = True
    return result


def advance_to_video(item, next_video_id, now=None):
    """Return a NEW LibraryItem pointing at ``next_video_id``.

    Port of ``LibraryItem::update_state``'s ``LibraryItemState::advance``
    path (library_item.rs, the ``next_video`` branch): fold this video's
    ``timeWatched`` into ``overallTimeWatched``, clear ``timeWatched`` and
    ``flaggedWatched``, set ``video_id`` to the next episode, and park
    ``timeOffset`` at 1 with ``duration`` 0. Offset 1 is the "just
    started" pointer -- ``timeOffset > 0`` is what puts the show back on
    Continue -- and duration 0 keeps it from looking like a measured
    resume position. ``state.watched`` is not modified here; the caller
    sets the bit for the episode that just finished before advancing.
    """
    now_iso = iso8601_utc(now)
    original_state = item.get('state')
    state = dict(original_state) if isinstance(original_state, dict) else _default_state(now_iso)
    state['overallTimeWatched'] = int(state.get('overallTimeWatched') or 0) + int(state.get('timeWatched') or 0)
    state['timeWatched'] = 0
    state['flaggedWatched'] = 0
    state['video_id'] = next_video_id
    state['timeOffset'] = 1
    state['duration'] = 0
    state['lastWatched'] = now_iso
    result = dict(item)
    result['state'] = state
    result['_mtime'] = now_iso
    return result


def finish_playback(item, video_id, video_ids, next_video_id=None, now=None):
    """Return a NEW LibraryItem for a playback that reached the end.

    The episode (``video_id``) is marked in ``state.watched`` when that
    string can be parsed against ``video_ids``. Otherwise the existing
    string is left exactly as it was, including ``None``. ``flaggedWatched``
    flips to 1 and ``timesWatched`` increments once, unless this video was
    already flagged -- a periodic sample that crossed 90% must not be
    counted a second time when the stop push lands.

    A series with ``next_video_id`` (and a different id from the one that
    just finished) then :func:`advance_to_video`. A movie, or the last
    episode, keeps ``flaggedWatched`` at 1 and sets ``timeOffset`` to 0
    so Continue drops it. ``apply_library_flags`` runs last so a brand-new
    implicit record still follows the temp/removed rules after
    ``timesWatched`` moves.
    """
    now_iso = iso8601_utc(now)
    original_state = item.get('state')
    state = dict(original_state) if isinstance(original_state, dict) else _default_state(now_iso)
    resolved = video_id or state.get('video_id')
    if resolved and state.get('video_id') != resolved:
        state['overallTimeWatched'] = int(state.get('overallTimeWatched') or 0) + int(state.get('timeWatched') or 0)
        state['timeWatched'] = 0
        state['flaggedWatched'] = 0
        state['video_id'] = resolved
    if resolved:
        updated = watchedbitfield.set_video_watched(state.get('watched'), video_ids or [], resolved, True)
        if updated is not None:
            state['watched'] = updated
    if not state.get('flaggedWatched'):
        state['flaggedWatched'] = 1
        state['timesWatched'] = int(state.get('timesWatched') or 0) + 1
    state['lastWatched'] = now_iso
    result = dict(item)
    result['state'] = state
    result['_mtime'] = now_iso
    if next_video_id and next_video_id != resolved:
        result = advance_to_video(result, next_video_id, now)
    else:
        result['state'] = dict(result['state'])
        result['state']['timeOffset'] = 0
    return apply_library_flags(result)
