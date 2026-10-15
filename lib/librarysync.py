# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Account library pull, progress merge, and the playback push job.

Pure Python -- no ``xbmc*`` imports. The service and the UI both call
in here so the rules live in one place:

* Continue rows are the official Stremio predicate, not a second
  invention: ``type != "other"`` and ``(not removed or temp)`` and
  ``timeOffset > 0``. "Not removed or temp" is that predicate
  (``!removed || temp``). An explicit removal is ``removed`` without
  ``temp`` and stays off Continue. An implicit watch is both flags
  true and stays on Continue while its offset is still positive.
* Where a local ``progress.json`` row and an account row name the same
  episode, the newer of ``updated_at`` and ``state.lastWatched`` wins.
  A tie keeps the local row.
* ``progress.json`` is seeded only from a measured account position
  the resume prompt can offer (``duration > 0``, at least 1% watched,
  a real timestamp, remote strictly newer, and not the title currently
  playing). A next-episode pointer (``timeOffset`` 1, ``duration`` 0,
  or 1ms of a real duration) is still a Continue row; it is not written
  into the resume cache.
"""
import datetime

from lib import library
from lib.stremio.watchedbitfield import sorted_video_ids, watched_video_ids

_OTHER = 'other'


def _number(value):
    """A real number, rejecting bool (a ``bool`` is an ``int`` subclass)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def is_account_continue(item):
    """True when an account ``libraryItem`` belongs on Continue.

    Mirrors stremio-core ``LibraryItem::is_in_continue_watching``
    (library_item.rs): not type ``other``, not an explicit removal, and
    ``state.timeOffset > 0``.
    """
    if not isinstance(item, dict):
        return False
    if item.get('type') == _OTHER or not item.get('_id'):
        return False
    if item.get('removed') and not item.get('temp'):
        return False
    state = item.get('state')
    if not isinstance(state, dict):
        return False
    offset = _number(state.get('timeOffset'))
    return offset is not None and offset > 0


def remote_progress_entry(item):
    """One account Continue row, shaped like a ``progress.json`` entry.

    ``from_library`` marks rows that did not come from this device's
    cache, so the Continue merge can keep a duration-0 pointer that
    local "barely started" rows still drop. ``name``/``poster`` travel
    with it because an implicit watch (``removed`` and ``temp``) is
    absent from ``library_metas`` and would otherwise have nothing to draw.
    """
    state = item.get('state') or {}
    position = _number(state.get('timeOffset')) or 0
    duration = _number(state.get('duration')) or 0
    return {
        'type': item.get('type'),
        'id': item.get('_id'),
        'video_id': state.get('video_id') or None,
        'position_ms': position,
        'duration_ms': duration,
        'updated_at': state.get('lastWatched') or item.get('_mtime') or '',
        'from_library': True,
        'name': item.get('name'),
        'poster': item.get('poster'),
        'background': item.get('background'),
    }


def _episode_key(entry):
    return (entry.get('type'), entry.get('id'), entry.get('video_id') or '')


def merge_progress_sources(local_entries, library_entries):
    """One row per episode: the newer of local ``updated_at`` and account
    ``lastWatched``. Local wins a tie, so a playback sample and a push
    that share a timestamp do not flap. Entries with no id are dropped.
    """
    merged = {}
    remote = [remote_progress_entry(item) for item in library_entries or [] if is_account_continue(item)]
    for entry in list(local_entries or []) + remote:
        if not isinstance(entry, dict) or not entry.get('id'):
            continue
        key = _episode_key(entry)
        current = merged.get(key)
        if current is None:
            merged[key] = entry
            continue
        if (entry.get('updated_at') or '') > (current.get('updated_at') or ''):
            merged[key] = entry
    return list(merged.values())


def _playing_id(store):
    getter = getattr(store, 'get_now_playing', None)
    if getter is None:
        return None
    current = getter()
    if isinstance(current, dict):
        return current.get('id')
    return None


def seed_progress(store, library_entries):
    """Copy measured account positions into ``progress.json``.

    Skips the title that is playing right now (the service is the
    writer for that row), anything without a positive duration, and
    anything the local cache already has at the same instant or later.
    The stored ``updated_at`` is the account's ``lastWatched``, not
    "now", so the next merge still knows which side is newer.
    """
    playing_id = _playing_id(store)
    for item in library_entries or []:
        if not is_account_continue(item):
            continue
        entry = remote_progress_entry(item)
        if playing_id and entry['id'] == playing_id:
            continue
        if not entry.get('updated_at'):
            continue
        if entry['duration_ms'] <= 0 or entry['position_ms'] <= 0:
            continue
        # Under 1% the resume prompt will not offer the row
        # (lib.ui.player.RESUME_MIN_PERCENT). Seeding it anyway writes a
        # local cache entry that ties lastWatched and then loses the
        # account pointer: Continue drops local sub-1% rows. Leave those
        # on the account side, where the pointer still shows.
        if (entry['position_ms'] / entry['duration_ms']) * 100.0 < 1.0:
            continue
        local = store.get_progress(entry['type'], entry['id'], entry['video_id'])
        local_at = (local or {}).get('updated_at') or ''
        if local and local_at >= entry['updated_at']:
            continue
        store.set_progress(
            entry['type'], entry['id'], entry['video_id'],
            int(entry['position_ms']), int(entry['duration_ms']), entry['updated_at'],
        )


def pull_title(store, api, content_id):
    """Fetch one library item and seed its measured progress.

    ``None`` when logged out or the account has no row. Network and
    decode failures propagate -- the UI caller logs them and still
    opens the screen on local data.
    """
    auth = store.get_auth() if store is not None else None
    auth_key = auth.get('authKey') if isinstance(auth, dict) else None
    if not auth_key or not content_id:
        return None
    item = api.get_library_item(auth_key, content_id)
    if not isinstance(item, dict):
        return None
    seed_progress(store, [item])
    return item


def video_is_watched(item, videos, video_id):
    """True when ``item['state']['watched']`` marks ``video_id``.

    Unparseable bitfields and unknown anchors are not watched -- the
    episode list shows no remote checkmark rather than a guessed one.
    """
    if not isinstance(item, dict) or not video_id:
        return False
    state = item.get('state')
    if not isinstance(state, dict):
        return False
    watched = watched_video_ids(state.get('watched'), sorted_video_ids(videos))
    if watched is None:
        return False
    return video_id in watched


def should_mark_watched(position_ms, duration_ms, natural_end, playback_error):
    """Whether a stop push should run :func:`library.finish_playback`.

    A player error records the position and does not mark the episode.
    A natural end (Kodi's playback-ended callback) does, even when the
    last sample landed a little under 90%. A user stop marks only once
    the position is past ``WATCHED_THRESHOLD_RATIO`` of the duration.
    """
    if playback_error:
        return False
    if natural_end:
        return True
    position = _number(position_ms)
    duration = _number(duration_ms)
    if position is None or duration is None or duration <= 0:
        return False
    return position > duration * library.WATCHED_THRESHOLD_RATIO


def build_push_job(context, position_ms, duration_ms, finished, updated_at=None):
    """The offline-queue record for one library push.

    ``updated_at`` is fixed when the job is built, before any background
    thread runs, and it is the ``lastWatched`` the put will write. A
    later retry skips the job when the account row is already at least
    that new, so a put that actually landed cannot increment
    ``timesWatched`` twice.
    """
    context = context or {}
    return {
        'id': context.get('id'),
        'type': context.get('type') or '',
        'video_id': context.get('video_id'),
        'position_ms': int(position_ms or 0),
        'duration_ms': int(duration_ms or 0),
        'name': context.get('name') or '',
        'poster': context.get('poster'),
        'video_ids': list(context.get('video_ids') or []),
        'next_video_id': context.get('next_video_id'),
        'finished': bool(finished),
        'updated_at': updated_at or library.iso8601_utc(),
    }


def _moment(updated_at):
    try:
        parsed = datetime.datetime.strptime(updated_at, '%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=datetime.timezone.utc)


def push_library_job(api, auth_key, job):
    """GET the current library item, merge or finish ``job``, PUT it.

    Returns ``'skipped'`` when the account row's ``lastWatched`` is
    already at least ``job['updated_at']`` (the put landed earlier, or
    a newer playback has since moved the row). Returns ``'put'`` after
    a datastore write. Raises on transport failure so the caller can
    keep the job queued.
    """
    item_id = job.get('id')
    existing = api.datastore_get(auth_key, ids=[item_id], all=False)
    if existing:
        base = existing[0]
        remote_at = ((base.get('state') or {}).get('lastWatched')) or ''
        job_at = job.get('updated_at') or ''
        if remote_at and job_at and remote_at >= job_at:
            return 'skipped'
    else:
        base = library.build_library_item({
            'id': item_id,
            'type': job.get('type') or '',
            'name': job.get('name') or '',
            'poster': job.get('poster'),
        })
    moment = _moment(job.get('updated_at'))
    if job.get('finished'):
        merged = library.finish_playback(
            base, job.get('video_id'), job.get('video_ids') or [],
            next_video_id=job.get('next_video_id'), now=moment,
        )
    else:
        merged = library.merge_playback(
            base, job.get('position_ms') or 0, job.get('duration_ms') or 0,
            video_id=job.get('video_id'), now=moment,
        )
        merged = library.apply_library_flags(merged)
    api.datastore_put(auth_key, [merged])
    return 'put'


def flush_pending(store, api, auth_key):
    """Replay queued pushes in order. Stop at the first failure and
    leave that job plus everything after it queued.

    Returns True when the queue is empty afterwards. A skipped job
    (the account is already newer) counts as done and is dropped.
    """
    jobs = list(store.get_pending_sync() or [])
    if not jobs:
        return True
    for index, job in enumerate(jobs):
        try:
            push_library_job(api, auth_key, job)
        except Exception:  # noqa: BLE001 - one dead job must not drop the rest or raise into playback
            store.set_pending_sync(jobs[index:])
            return False
    store.set_pending_sync([])
    return True
