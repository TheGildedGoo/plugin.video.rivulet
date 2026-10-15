# Library and playback sync

Investigation only. No addon code was changed and no pull request was opened.

Dylan uses Rivulet/RevRivulet on two Kodi devices signed into the same Stremio account. Two things fail:

1. A title he adds to his library in the Stremio phone app does not show up in RevRivulet.
2. He watched American Horror Story season 13 on the bedroom Kodi. On the living-room Kodi that show is not under Continue, and the episode is not marked watched.

He wants the addon to sync with the Stremio account when every movie or episode starts and when it stops.

Playback, resume, and the Stremio API client may be changed on this fork if the sync needs them. Those three are easy to break, so the plan below says exactly which of their lines move and which tests have to pass before that is safe. This document does not make those changes.

## Findings

### Same account, separate profile

RevRivulet is `plugin.video.revrivulet`. Official Rivulet is `plugin.video.rivulet`. Kodi gives each addon its own `addon_data` directory (`docs/REVRIVULET.md`, `lib/addonid.py`).

The Stremio login for this addon is `auth.json` in that profile (`lib/store.py` lines 18-19, `lib/ui/views.py` `login()` at lines 704-726). The UI store and the background service both use that same profile (`lib/ui/compat.py` `addon_profile_dir()` lines 34-39; `lib/service_runner.py` `main()` lines 1552-1587). They do not read official Rivulet's `auth.json`.

A device that is "signed into Stremio" only in the phone app, or only in official Rivulet, is logged out inside RevRivulet. Home shows that as "Not logged in" (`lib/ui/homewindow.py` `_status_text()` lines 215-229, string `#30190`). Every library call bails out before the network when `get_auth()` is empty.

`sync_progress` defaults to on (`resources/settings.xml` lines 139-142, label "Sync playback progress to your Stremio account"). Turning it off stops the remote push and leaves the local resume file alone.

### How Continue and the library are read

Continue and Watch Later are the same screen. `open_my_stuff()` with no argument is Continue. Watch Later calls `open_my_stuff(bands=(BAND_LIBRARY,))` (`lib/ui/homewindow.py` lines 279-294, `docs/UI_MAP.md` lines 39-47 and 114-118).

Each open does two reads and merges them (`lib/ui/mystuff.py` `open_my_stuff()` lines 453-457):

| Source | Call | What it is |
|---|---|---|
| Local playback | `Store.get_progress_entries()` | `progress.json` in this device's profile |
| Account library | `StremioAPI.datastore_get(authKey, collection="libraryItem", all=True)` | Live `POST /api/datastoreGet` |

There is no library-item cache and no library TTL. The docstring on `library_add_payload()` says this on purpose (`lib/library.py` lines 277-280). `datastoreMeta` exists (`lib/stremio/api.py` lines 159-176) and is covered by `tests/test_api.py`, but nothing in `lib/` except the client itself calls it. Every Continue or Watch Later open downloads the whole `libraryItem` collection again.

`lib/ui/metacache.py` `TTL_SECONDS = 1800` (lines 51-60) is a different cache. It stores addon metadata (description, episode list) for 30 minutes. A library row already carries `name` and `poster` from the datastore record, so that TTL cannot hide a newly added library title.

The merge (`merge_entries()`, lines 162-216) builds four bands, in this order:

| Band | Rule | Source |
|---|---|---|
| `resume` | Local progress from 1% up to 95% | `progress.json` only |
| `next_up` | Local progress at or above 95%, and the title is a series | `progress.json` only |
| `recent` | Local progress at or above 95%, movie or finished series | `progress.json` only |
| `library` | Datastore row with `removed` false, and this device has no local progress for that `(type, id)` | `libraryItem` |

`library_metas()` (lines 144-159) keeps a datastore row when `removed` is false and `_id` is present. It does not look at `temp`. A row with `removed` true is dropped, including the `removed: true, temp: true` record Stremio writes for "watched, never added to the library" (`lib/library.py` `build_library_item()` lines 120-150). `tests/test_mystuff.py` `test_merge_entries_drops_removed_library_entries` locks that drop in.

`_band_for()` (lines 100-115) drops anything under `RESUME_MIN_PERCENT` (1%). Official continue-watching does the opposite for a 1 ms pointer: it shows the item. See the stop-push section below.

Caps, applied after that split: 24 played titles (`MAX_PLAYED_ITEMS`, line 75), then 200 library titles in whatever order `datastoreGet` returned (`MAX_LIBRARY_ITEMS`, line 81, loop at lines 208-215). The cap is not "newest 200".

A failed `datastoreGet` is logged and turned into an empty library (`_fetch_library_entries()` lines 269-288). Continue still opens on local progress. Watch Later, if the account is present but the call failed, uses the same empty-library string as a genuinely empty library (`#30426`, "No unstarted library titles"). The failure is not distinguishable on screen.

Resume, the episode list, and New Episodes do not read the account either:

- Resume asks only `Store.get_progress()` (`lib/ui/player.py` `_maybe_resume_offset_ms()` lines 236-263). The prompt is between 1% and 95% and only if `resume_ask` is on.
- Each episode row's watched percent is that same local entry (`lib/ui/detailwindow.py` `_build_episode_items()` lines 411-448, `_episode_progress()` lines 452-465). The comment at lines 440-441 says this is independent of `state.watched`.
- New Episodes follows series that have a local progress entry (`lib/ui/catalogpicker.py` `_followed_series()` lines 397-423).

`progress.json` is capped at 500 entries and entries older than 180 days are swept (`lib/store.py` lines 93-117). The service rewrites it about every 15 seconds during playback (`LOCAL_PROGRESS_WRITE_INTERVAL_SECONDS`, `lib/service_runner.py` line 80). That file is per device. The living room never sees the bedroom's copy.

### How watch state is written

Local progress is written by the background service, not by `play()`. `lib/ui/player.py` `_record_now_playing_and_maybe_resume()` (lines 266-301) writes `now_playing.json` and, if the user accepts, a one-shot `resume_offset.json`. The service player (`lib/service_runner.py` `build_progress_player()`, lines 735-942) notices that context.

While Kodi is playing a context this player instance accepted in `onAVStarted`:

- About every 15 seconds it writes `progress.json` (`_flush()` lines 904-911).
- On the first sample, then every 90 seconds, then again on stop, it pushes one `libraryItem` (`LIBRARY_PUSH_INTERVAL_SECONDS` line 74, `should_push_now()` lines 691-701, `_push()` lines 917-941).

The push is skipped when `sync_progress` is off or `authKey` is missing (tests `test_push_skipped_when_sync_setting_disabled_zero_api_calls` and `test_push_skipped_when_logged_out_zero_api_calls`). A network error is logged and swallowed. The local file was already written.

The push itself:

1. `datastoreGet` for that one id, `all=false`.
2. If the account has no row, `build_library_item()`, which sets `removed: true` and `temp: true`.
3. `merge_playback()` (`lib/library.py` lines 166-263).
4. `datastorePut` of that one item. `lib/stremio/api.py` `datastore_put()` (lines 143-157) posts `{authKey, collection: "libraryItem", changes: [...]}`. No other collection is used.

`merge_playback()` updates `lastWatched`, `timeOffset`, `duration`, `timeWatched`, `overallTimeWatched`, `video_id`, and, once `timeWatched` passes 90% of duration, `flaggedWatched` and `timesWatched`. It copies `state.watched` through untouched. The module docstring (lines 35-42) forbids inventing that field: it is a `stremio-watched-bitfield` blob, and a wrong value corrupts the account the next time a real Stremio client reads it. `test_push_merges_existing_remote_item_preserving_watched_bitfield` locks the carry-through.

The 90% threshold is deliberate and stricter than Stremio. Upstream `WATCHED_THRESHOLD_COEF` is 0.7 (`lib/library.py` lines 51-62).

Changing episode clears the series-level watched flag. When `video_id` changes, `merge_playback()` sets `flaggedWatched` back to 0, zeroes `timeWatched`, and zeroes `timeOffset` (lines 226-246). The per-episode record official clients show as a checkmark is `state.watched`, which this addon never writes. `flaggedWatched` is one number for the whole library item. The detail context menu uses that one number for "Mark as watched" (`lib/ui/detailwindow.py` lines 594-595 and `_toggle_watched()` lines 690-715). It is not an episode checkmark.

Stop does not sample the player. Kodi's stop/end/error callbacks run after the file is closed, and `getTime()` then raises. The final flush replays the last successful sample (`_flush()` lines 887-893). If playback ends before any sample (stop inside the first poll, or `duration_ms <= 0`), the flush logs "no playback sample to flush at stop" and does not push.

`onAVStarted` (lines 783-802) resets the local-write clock and the last sample. It does not reset `_last_pushed_at`. The first episode pushes immediately. A later episode inside the same 90 second window does not push until the interval elapses or that later episode stops. Its stop flush does push, because `final=True` bypasses the interval (`test_final_flush_bypasses_the_push_throttle`).

The service poll that takes the first sample is `HEALTHY_POLL_INTERVAL = 2.0` (line 109). "Start" today means "first poll after `onAVStarted`", not the moment `play()` is called. A start sample is a real `getTime()`, so a title opened and stopped before that poll never reaches the account.

`_terminate()` (lines 819-836) always deletes `now_playing.json` and `resume_offset.json`, even when the context on disk is no longer the one this callback accepted. The plugin process and the service process are different OS processes. Binge writes the next episode's `now_playing.json` from the plugin (`lib/ui/streamswindow.py` `_try_binge_watch()` calls `play_direct()` after `_wait_for_playback_end()`). The service's final `datastorePut` runs inside the stop callback before that delete. `StremioAPI` times out at 15 seconds (`lib/stremio/api.py` line 20). If the next episode's `play_direct()` writes `now_playing.json` during that put, the callback's unconditional `set_now_playing(None)` deletes the next episode's context. That race already exists. A start/stop change that does more network work on the callback makes it worse. The plan below closes it.

### What the phone and the other Kodi actually look at

Upstream `LibraryItem::is_in_continue_watching` (`stremio-core` `src/types/library/library_item.rs`, development, lines 55-58) is:

```text
type != "other" && (!removed || temp) && state.time_offset > 0
```

A saved library title has `removed: false, temp: false`. A title that was only played has `removed: true, temp: true`. Both stay on the phone's Continue row while `timeOffset > 0`. RevRivulet's library band drops every `removed` row, and its resume band never reads `timeOffset`.

When playback passes the credits threshold, upstream `item_state_update` (`src/models/player.rs`) sets `timeOffset` to 0 and, if there is a next episode, calls `LibraryItem::advance_to_video`. That sets `video_id` to the next episode, `flaggedWatched` to 0, and `timeOffset` to 1 (`library_item.rs` lines 143-153). `timeOffset == 1` is what keeps the show on Continue, pointed at the next episode. The finished episode's checkmark is the bit in `state.watched`, set with `WatchedBitField::set_video` when the 70% threshold flips. The serialized form is `{anchorVideoId}:{anchorLength}:{base64 zlib bitfield}` (`stremio-watched-bitfield` README). The anchor id can itself contain colons, so a parser has to split from the right.

`LibraryItemState::watched_bitfield` sorts videos by season, then episode, then release time, and a video with no `series_info` sorts first (`season`/`episode` missing become `i64::MIN`). That is not `lib/ui/binge.py` `_sort_key()`, which sorts season 0 and missing seasons last so "next episode" does not walk into Specials. The bitfield must use the library sort. Next-episode selection must keep using `binge.next_video()`.

### Root cause: phone library adds

An explicit add in the phone app is a `libraryItem` with `removed: false`. RevRivulet already requests that collection, live, with no TTL. Those rows are eligible for the `library` band (Continue, bottom row, heading "Your library", string `#30247`) and for Watch Later.

They are absent from the resume / next-up / recent rows, because those rows are `progress.json` on this device. A title nobody has started here will not appear under "Continue watching" (`#30245`). It appears under "Your library", or on the Watch Later row.

If it is missing from Watch Later as well, the code supports three causes, in this order:

1. This RevRivulet profile has no `authKey`. The fetch returns `[]` before any HTTP call. Watch Later then shows `#30424` ("Sign in to see library titles you have not started."). Official Rivulet being logged in does not count.
2. `datastoreGet` failed. The warning is `mystuff: datastore_get failed, showing local bands only`. Watch Later shows `#30426`, the same text as an empty library, so a dead token or a timeout looks like "the phone add never arrived".
3. The account has more than 200 not-removed rows and the new id is past the first 200 in API order (`MAX_LIBRARY_ITEMS`).

A stale library cache is not a possible cause. There is not one. `temp` is not filtered on this path. A second collection is not involved: Watch Later is the `library` band of the same `libraryItem` list (`docs/UI_MAP.md` lines 114-118).

### Root cause: bedroom watch missing on the living room

Both parts of this report are the same gap.

The bedroom, when logged in with `sync_progress` on, does push a `libraryItem` for the series: `video_id` of the episode, `timeOffset` / `duration` in milliseconds, `lastWatched`, and `flaggedWatched` if that episode's accumulated `timeWatched` crossed 90%. The living room never reads those fields.

- Continue on the living room builds resume / next-up / recent only from its own `progress.json`. The bedroom's file is not on that machine, so American Horror Story is not in those bands.
- If the series was never explicitly added, the pushed row has `removed: true, temp: true`. `library_metas()` drops it, so it is also absent from "Your library" and Watch Later. The phone would still show it in Continue, because `(!removed || temp) && timeOffset > 0`.
- The episode list marks a row from local `get_progress()` only. The living room has no row for that `video_id`.
- Even a living room that learned to read `flaggedWatched` would be wrong for a single episode. That flag is reset to 0 when playback moves to another episode, and it was never the per-episode checkmark. `state.watched` is still the previous account value, or `null` if RevRivulet created the row. The phone will not check the episode off either.

So the bedroom push is real and incomplete, and the living room does not consume it.

## Implementation plan

Do the read side and the write side together. Doing only the push leaves the living room blind. Doing only the pull cannot mark the episode watched on the phone, because the bitfield is still never written.

Keep `lib/stremio/api.py` unchanged. `datastore_get`, `datastore_put`, `get_library_item`, and `put_library_item` already have the right bodies. New call sites should use those methods. `datastore_meta` can stay unused; a full `datastoreGet` on each Continue open is the right refresh until a profile shows that payload is too large.

### 1. Project account rows into the two lists Continue already understands

Add pure functions in `lib/ui/mystuff.py` (no `xbmc` import; `tests/test_mystuff.py` calls this module with plain dicts).

`is_remote_continue(entry)` mirrors upstream lines 55-58:

- `entry.get('type') != 'other'`
- `not entry.get('removed') or entry.get('temp')`
- `int((entry.get('state') or {}).get('timeOffset') or 0) > 0`
- `entry.get('_id')` is present

`remote_progress_entries(library_entries)` returns progress-shaped dicts for those rows:

```python
{
    'type': entry.get('type'),
    'id': entry.get('_id'),
    'video_id': state.get('video_id') or None,
    'position_ms': int(state.get('timeOffset') or 0),
    'duration_ms': int(state.get('duration') or 0),
    'updated_at': state.get('lastWatched') or '',
    'from_library': True,
}
```

`library_metas()` stays as it is: not-removed rows only, for the library band and for poster/name enrichment. Do not start hiding `temp` there.

`merge_entries(progress_entries, library_entries)` gains one step before `latest_by_title()`:

- Build the remote progress list.
- For each `(type, id)`, keep the entry with the greater `updated_at`. Compare the strings Stremio and `iso8601_utc()` already use (`YYYY-MM-DDTHH:MM:SSZ`). A missing timestamp loses to a present one.
- Pass that combined list to the existing `latest_by_title()` / band logic.
- Leave the library-band loop on `library_metas()`, still skipping ids that landed in a played band, still capped at 200.

Sort the library-band candidates by `_mtime` descending before the cap, so a phone add is not the 201st row in an arbitrary API order. `_mtime` is the same ISO string.

`_band_for()` currently returns `None` below 1%. That rule is correct for a local accidental play and wrong for upstream's `timeOffset = 1` pointer (percent of a 40 minute episode is about 0.00004%). Split the rule:

- Local entry (`from_library` absent): keep today's 1% floor.
- Library entry with `position_ms > 0` and percent under 1%: `BAND_RESUME`, not `None`.

A series at or above 95% still goes to `next_up`. After the stop-push in section 4, a finished episode is stored as the next episode at 1 ms, so the other device shows it in Continue watching rather than as a finished episode. That matches the phone.

`open_my_stuff()` already calls `_fetch_library_entries()` on every open. No new timer. Change the helper to return `(entries, status)` with status `logged_out`, `ok`, or `error`. `_empty_notice()` for Watch Later:

- `logged_out`: keep `#30424`.
- `error`: new string `#30427`, added to all 14 `strings.po` files. Wording: "Could not load your Stremio library. Try again." Do not reuse `#30426`.
- `ok` and no unstarted rows: keep `#30426`.

`#30426` is the current highest id in `resources/language/resource.language.en_gb/strings.po`.

### 2. Seed `progress.json` so resume does not call the network

`_maybe_resume_offset_ms()` must stay a local read. A `datastoreGet` inside `_resolve_playable_item()` sits under the "Preparing stream" dialog, on the 15 second API timeout, in the process that is trying to start playback. Do not add that call.

Instead, after a successful library fetch, seed the local cache from `remote_progress_entries()`:

```python
def seed_progress_from_library(store, remote_entries, playing_id=None):
    for entry in remote_entries:
        if entry.get('id') == playing_id:
            continue
        if not entry.get('updated_at') or int(entry.get('duration_ms') or 0) <= 0:
            continue
        local = store.get_progress(entry['type'], entry['id'], entry.get('video_id'))
        local_at = (local or {}).get('updated_at') or ''
        if entry['updated_at'] <= local_at:
            continue
        store.set_progress(
            entry['type'], entry['id'], entry.get('video_id'),
            entry['position_ms'], entry['duration_ms'], entry['updated_at'],
        )
```

Call it from `open_my_stuff()` and from the detail window when it loads the library item (section 3). Pass `store.get_now_playing()`'s `id` as `playing_id` so a seed cannot overwrite the episode currently being sampled.

`set_progress` is already a plain read-modify-write. A lost race with the service's 15 second sample drops one sample; the next sample or the next open corrects it (`lib/store.py` lines 1523-1528). Seeding only when the account timestamp is strictly newer keeps a bedroom that has not pushed yet from being rewound by an older account row.

This is why resume itself does not need a logic change. Once the living room has opened Continue or the series page, `get_progress()` sees the bedroom's offset and the existing 1%–95% prompt runs. Opening the title from search without ever opening Continue still needs the detail-window seed below, or the first play on the living room starts at 0.

Do not also write a `progress.json` row per watched episode. `latest_by_title()` keeps one row per series, the newest `updated_at`. Stuffing every checked episode in there would move the show into the wrong band.

### 3. Episode checkmarks on the detail window

`DetailWindow._build_episode_items()` needs one live `get_library_item` for `self.meta['id']` (the same call `_current_library_state()` already makes, `lib/ui/detailwindow.py` lines 610-657). Fetch it once while the episode list is built, under the existing cancellable busy dialog, and keep the record on the window for the context menu so the menu does not fetch a second time.

For each episode id:

- If local `get_progress()` has a percent, keep today's bar. Local is newer only when its `updated_at` is greater than `state.lastWatched`; otherwise the remote percent for `state.video_id` wins, using `timeOffset / duration`.
- If `watched_bitfield.get_video(video_id)` is true, set the row's watched label even when local progress is missing. Use the existing `#30212` percent string at 100, or the existing `watched` property the grid already understands. Do not write that into `progress.json`.
- If the bitfield string is present but does not parse, leave every remote checkmark off and do not replace the string. Log a warning. A parse failure must not look like "nothing is watched" in a later put.

Movies have no episode list. The context menu's `flaggedWatched` read is already live. No change there for movies beyond the stop-push setting that flag.

This is a `lib/ui/detailwindow.py` change plus the pure bitfield module. It does not touch stream resolution.

### 4. Push at start and at stop

All of this is `lib/service_runner.py` `build_progress_player()`, plus two pure helpers in `lib/library.py`. The API client stays as it is.

**Accepting a new episode resets the push clock.** In `onAVStarted`, after the stale-context check and next to the existing `_last_local_write_at = None` (line 793), set `self._last_pushed_at = None`. Without that, episode 2 of a binge does not push at start when episode 1 pushed less than 90 seconds ago.

**Start push, after the resume seek, without `getTime()`.** `seekTime()` is asynchronous. A `getTime()` in `onAVStarted` can still read 0 and, on a video-id change, `merge_playback()` would store that 0 (lines 244-253). Pass an explicit position:

- If this callback just consumed a resume offset, pass that offset.
- Otherwise pass `1`.

`1` is the upstream `advance_to_video` pointer. `merge_playback()` will not move `timeOffset` backward when the account already has a larger offset for the same `video_id` (the `position_ms > previous_offset` guard, lines 252-254). For a new `video_id` it resets, then stores `1` because `1 > 0`. The other device's `is_in_continue_watching` becomes true immediately.

Do not call `set_progress` with that synthetic `1`. Local resume must keep waiting for a real sample. The start push is `datastoreGet` + `merge_playback` + `datastorePut` only.

Run that put on a daemon thread. `onAVStarted` also performs the resume seek; it must return even when the account is slow. A failure is the same warning `_push` already logs.

**Stop push snapshots, then releases the context, then uploads.** Replace the body of `_terminate()` with this order:

1. Read `now_playing` and copy `_accepted_key`, `_last_sample`, and the context dict.
2. Clear the in-memory clocks, including `_last_pushed_at`.
3. If the on-disk context's `_context_key` still equals the accepted key, delete `now_playing.json` and `resume_offset.json`. If it does not, a newer episode has already been written by the plugin process: leave those files alone and do not push this callback's sample over that newer episode.
4. If this callback owns the context and `_last_sample` matches the key, write `progress.json` from that sample (the final flush already bypasses the 15 second local throttle; keep that).
5. Start a daemon thread that pushes the snapshotted item. The callback must not be inside `datastorePut` when step 3's delete runs, and step 3 must not run again after the thread finishes.

Make the delete a compare-and-swap. Add `Store.clear_now_playing_if(started_at)` in `lib/store.py`: re-read `now_playing.json` (not the memo alone; `_cached_read` is safe across processes because it keys on `os.stat`, but the compare and the delete need to observe the re-read), and remove the file only when `started_at` still matches. Same for the resume-offset file: clear it only when clearing the matching now-playing context. `_context_key` includes `started_at`, so matching `started_at` is enough if it is required on every context. It already is (`player.py` line 299).

The existing unconditional `set_now_playing(None)` at lines 835-836 is the binge hazard. Deleting it without the compare-and-swap would leak a context after a real stop. The compare-and-swap is the replacement, not an extra delete.

If there is no `_last_sample` (stopped before the first poll), still push the start position that `onAVStarted` already sent, if a start push was attempted. Remember it on the instance as `_start_position_ms` next to `_accepted_key`. The final put then uses `max(last_sample_position, _start_position_ms)` only when the sample is missing; a real sample always wins. This covers "opened and backed out within two seconds" without inventing a position ahead of the real one.

The 90 second mid-playback push stays. Dylan asked for start and stop. The periodic push is what makes a crash halfway through an episode visible on the other device before the stop callback. Leave `LIBRARY_PUSH_INTERVAL_SECONDS` at 90. Current upstream `PUSH_TO_LIBRARY_EVERY` is 180 seconds (`player.rs` line 50 on development). This repo intentionally pinned 90 (`service_runner.py` lines 70-74). Do not retune it in the same change.

### 5. On stop, mark the episode and point Continue at the next one

`merge_playback()` stays the periodic updater and still does not write `state.watched`. Add `finish_playback(item, position_ms, duration_ms, video_id, video_ids, next_video_id, now)` in `lib/library.py`, used only by the stop thread:

1. `item = merge_playback(item, position_ms, duration_ms, video_id=video_id, now=now)`.
2. Watched when `flaggedWatched` is set, or when `duration_ms > 0` and `position_ms > duration_ms * WATCHED_THRESHOLD_RATIO`. Use the addon's 0.9 ratio, not upstream's 0.7, so a stop agrees with the samples already pushed during playback.
3. If watched and `video_ids` is a non-empty list, set that `video_id` in the bitfield (section 6) and store the serialized string on `state['watched']`. If `video_ids` is missing, leave `state['watched']` exactly as `merge_playback` copied it.
4. If watched and `next_video_id` is set, `advance_to_video(item, next_video_id)`: fold `timeWatched` into `overallTimeWatched`, set `timeWatched` 0, `flaggedWatched` 0, `video_id` to the next id, `timeOffset` 1, `duration` 0. Do not touch `watched`, `removed`, or `temp`. This is `LibraryItem::advance_to_video`.
5. If watched and there is no next video (movie, or the last episode), set `timeOffset` to 0. Upstream does this so a finished movie leaves Continue. `flaggedWatched` stays 1 from step 1. The library band still shows it when `removed` is false.

`removed` / `temp` keep whatever `datastoreGet` returned. A saved series stays `removed: false`. A never-added series stays `removed: true, temp: true`, which Continue includes because of `temp`. Do not run `build_library_item()` over an id the get actually returned.

**Where `video_ids` and `next_video_id` come from.** The service does not have the series meta. Extend the now-playing dict written in `lib/ui/player.py` `_record_now_playing_and_maybe_resume()` (lines 293-300). The store persists the dict wholesale (`set_now_playing`, `lib/store.py` lines 1401-1415); extra keys do not need a store migration. `_context_key` ignores them.

- `video_ids`: ids from `item_meta['meta']['videos']`, sorted with the library bitfield sort (season, episode, release; missing `series_info` first). Empty list for a movie or a play call that has no `videos`.
- `next_video_id`: `binge.next_video(meta, video_id)` then that video's `id`, or `None`. Keep using `binge.next_video` so Specials stay out of the pointer. Do not sort next-episode with the bitfield sort.

`item_meta['meta']` is already the series meta on the normal play path and on the binge path (`lib/ui/streamswindow.py` lines 794-805 and `_binge_item_meta()` lines 1311-1329). A caller that passes no meta gets no bitfield update and no advance, and the stop push behaves as today's `merge_playback`. That is the safe fallback.

This is the player change. It does not change URL resolution, the resume prompt, the seek, or binge's own "what plays next" loop. Binge keeps deciding the next episode locally. The new fields only tell the service what to put in the account row when this episode stops.

### 6. Bitfield module

New file `lib/stremio/watchedbitfield.py`. No `xbmc` import, same rule as `lib/stremio/api.py`.

Port `constructAndResize` / `construct_with_videos`, `getVideo`, `setVideo`, and `serialize` from `Stremio/stremio-watched-bitfield`. Behavior that has to match, because the phone resizes against it:

- Wire string `{anchorVideoId}:{anchorLength}:{payload}`. Split on the last two colons. The anchor id may contain colons (`tt123:1:5`).
- Payload is the bitfield bytes, zlib-compressed, standard base64.
- `constructAndResize(serialized, video_ids)` shifts when videos were inserted at the front or appended, which is the only change the format allows. Any other shape of change is defined to go inconsistent; do not try to be clever.
- `setVideo` on an id that is not in `video_ids` is a no-op.
- `getVideo` on an unknown id is false.
- Parse failure raises. Callers catch it and keep the previous `state.watched` string.

Copy the crate's own test vectors into `tests/test_watchedbitfield.py` before writing the encoder. Do not invent a sample string. `lib/library.py` lines 35-42 are the constraint: a hand-rolled bit that "looks set" in our UI and does not round-trip through `constructAndResize` will mark the wrong episodes in the phone app.

Python 3.8 is the floor. `zlib` and `base64` from the stdlib are fine. No 3.9 syntax.

`finish_playback` calls this module only in step 3 of section 5. The 15 second and 90 second samples keep using `merge_playback`, which still does not read or write the bitfield. A mid-episode push cannot clear checkmarks.

### Files

| File | Change | Playback / resume / API? |
|---|---|---|
| `lib/ui/mystuff.py` | Remote progress projection, newer-wins merge, library sort before the 200 cap, fetch status | No |
| `lib/ui/detailwindow.py` | One library fetch while building episode rows; bitfield checkmarks; seed progress | No. Does not pick streams |
| `lib/library.py` | `advance_to_video`, `finish_playback`. `merge_playback` unchanged | Wire format used by the service push. No Kodi calls |
| `lib/stremio/watchedbitfield.py` | New. Encode/decode only | No |
| `lib/store.py` | `clear_now_playing_if(started_at)` | Small persistence helper. No resume math |
| `lib/service_runner.py` | Reset push clock; start put; stop snapshot and compare-and-swap; call `finish_playback` | Yes. This is the playback-progress player. Required |
| `lib/ui/player.py` | Add `video_ids` and `next_video_id` to the now-playing dict | Yes. Resume function and resolve/play stay as they are |
| `lib/stremio/api.py` | None | Allowed, and not needed |
| `lib/ui/streamswindow.py`, `lib/ui/binge.py` | None | Binge and next-episode selection stay |
| `resources/language/*/strings.po` | `#30427` in all 14 locales | No |

`tests/kodistubs/fakes.py` `_DEFAULT_LOCALIZED` must include `#30427` if production code formats it. It does not need `%` arguments.

## Test plan

Run the whole suite. The gates in `AGENTS.md` are `uvx --with-requirements requirements-dev.txt pytest tests/ -q`, plus `ruff check lib tests` and `mypy`. Do not run `make format`.

New tests, next to the modules they lock:

**`tests/test_mystuff.py`**

- `removed: true, temp: true`, `timeOffset` 50000, `duration` 100000, `video_id` set: lands in `resume`, not dropped.
- Same row with `timeOffset` 0: dropped from played bands and from the library band.
- `removed: false, temp: false`, no progress: still `library`. Phone-add shape.
- Local `updated_at` newer than `lastWatched`: local position wins.
- Remote `lastWatched` newer: remote position wins, and a local sub-1% accidental play does not hide it.
- Remote `timeOffset` 1 and a real duration: `resume`, not dropped.
- Local progress at 0.5%: still dropped (`from_library` absent).
- 210 not-removed rows: the 200 kept are the 200 greatest `_mtime`, so a brand-new `_mtime` is kept.
- `type == 'other'`: not in the remote progress list.

**`tests/test_library.py`**

- `advance_to_video` sets `timeOffset` 1, `flaggedWatched` 0, `video_id` to the argument, folds `timeWatched` into `overallTimeWatched`, and leaves `watched`, `removed`, and `temp` identical.
- `finish_playback` on a series past 90% with `video_ids` and `next_video_id` sets the bit and then advances.
- `finish_playback` on a movie past 90% sets `flaggedWatched` 1 and `timeOffset` 0, and leaves `watched` null.
- `finish_playback` below 90% equals `merge_playback` and does not call the bitfield writer.
- Existing `merge_playback` tests stay green, including the video-id change that zeroes `flaggedWatched` and the "bitfield carried through" cases.

**`tests/test_watchedbitfield.py`**

- Round-trip the crate's vectors: parse, `getVideo`, `setVideo`, serialize, parse again with the same id list.
- Anchor id containing colons.
- `setVideo` of an unknown id does not change the string.
- Garbage input raises and the caller test shows `state['watched']` unchanged.

**`tests/test_service_runner_player.py`**

- Second `onAVStarted` for a new `started_at` within 90 seconds of the previous put performs another put (the clock reset).
- Start put uses the consumed resume offset when there was one, and `1` when there was not.
- Start put does not call `set_progress`.
- `onAVStarted` still seeks once and still clears `resume_offset` once. Existing `test_onavstarted_seeks_when_resume_offset_queued_for_active_context` and `test_onavstarted_clears_resume_offset_so_it_never_reseeks_twice` stay.
- Stop after a sample puts `finish_playback`'s result, not a second periodic merge that leaves `timeOffset` at the end of a finished episode.
- Stop when `get_now_playing()` has a different `started_at` does not delete that context and does not put. This is the binge regression test.
- Stop when the context still matches does delete it.
- Push thread failure does not raise out of `onPlayBackEnded`.
- Existing "bitfield preserved on the periodic put" test stays on the periodic path.

**`tests/test_player.py` / the player callback tests**

- The now-playing dict gained `video_ids` in bitfield order and `next_video_id` from `binge.next_video`.
- A meta with a season-0 special still yields a `next_video_id` that skips it, while `video_ids` lists that special where the library sort puts it.
- No meta: those two keys are absent or empty, and `play_direct` still calls `set_now_playing` with the original five keys' values.
- `play` / `play_direct` do not call `datastore_get` or `datastore_put`. Assert on the fake API.

**`tests/test_store.py`**

- `clear_now_playing_if` removes the file when `started_at` matches.
- It leaves the file when `started_at` differs, including when the difference appeared after the caller first read the file (write the new context between the caller's snapshot and the clear).

**`tests/test_detailwindow.py`**

- Episode id set in the bitfield, no local progress: the row's watched property is set.
- Local progress newer than `lastWatched`: the bar uses the local percent.
- Unparseable `state.watched`: rows still build, and a later mark-watched put is not given a replacement bitfield by the list builder. The context menu's existing lookup-failed refusal (`lookup_ok`) stays.

Update any test that asserts the exact now-playing keys if it compares the whole dict.

## Regression risks

**Resume seek.** `onAVStarted` must seek and clear the one-shot offset before the start put, and the start put must not write `progress.json`. If the synthetic `1` were written locally, the next play would offer to resume at 1 ms, and a seed from the other device could fight it. The tests above lock both.

**Forward-only offset.** A start put of `1` against the same `video_id` with a real offset must leave that offset. `merge_playback` already guarantees it. A start put for a different `video_id` resets the offset. That is correct for "this episode started" and is why the stop of the previous episode has to advance (or finish) first. Order during binge: previous episode's stop callback owns the old `started_at` and pushes the finish; the next `play_direct` writes a new `started_at`; the new `onAVStarted` pushes the start. The compare-and-swap is what keeps the stop callback from deleting the new file.

**Binge / next episode.** `streamswindow._try_binge_watch` and `binge.next_video` are unchanged. The risk is the shared `now_playing.json`, described above. A second risk is `finish_playback` advancing `video_id` to the same episode binge is about to play. That is what we want on the account. It must not change which stream binge plays. Binge does not read the library item.

**Double-counting `timesWatched`.** `merge_playback` increments once, gated on `flaggedWatched == 0`. `advance_to_video` then clears the flag for the next episode. The stop path must call `merge_playback` once and `advance_to_video` after, not `merge_playback` again on the advanced item with a near-zero position. `finish_playback` as specified does that. A second periodic sample after the stop must not run: `_terminate` clears `_accepted_key` before the thread puts.

**Bitfield corruption.** The only writer is `finish_playback` when `video_ids` is non-empty and the threshold is crossed. Parse failure keeps the old string. Wrong sort order would check off the wrong episode on the phone; the season-0 test is there so the bitfield sort and `binge.next_video` cannot silently share one key function.

**Playback start latency.** The start put is off the callback's return only if it is actually on a daemon thread. Joining that thread from `onAVStarted` would stall the seek's callback and can stall Kodi's player thread. Do not join it. Do not put the get/put inside `_resolve_playable_item`.

**Watch Later empties.** Including `temp` rows in the remote progress list must not put them in `BAND_LIBRARY`. `library_metas` still requires `removed` false. A regression test should use a `removed: true, temp: true` row with progress and assert it is absent from Watch Later's band filter.

**Concurrent `progress.json`.** Seeding uses `set_progress`. That is the same race the service already accepts. The `playing_id` skip and the strict timestamp compare are the extra guards. Do not add file locking; the store docstring explains why there is none.

## Two-device check

Unit tests cannot see a real account. After the suite is green, check on two Kodis (or one Kodi plus the phone) that are logged into RevRivulet itself. Home's status line must show the same email on both, not "Not logged in". `sync_progress` stays on.

1. On the phone, add a movie that neither Kodi has played. Open Watch Later on Kodi A. The movie is there without restarting Kodi. Open Continue: it is under "Your library", not under "Continue watching". Repeat on Kodi B.
2. Turn off the network on Kodi A and open Watch Later. The new `#30427` notice appears, not "No unstarted library titles."
3. On Kodi A, start a movie and stop it a few minutes in. Before starting it on Kodi B, open Continue on B. The movie is under Continue watching. Play it on B. The resume prompt offers A's position. Decline, then play again and accept, and confirm playback seeks.
4. On Kodi A, watch a series episode past 90% and let it end (do not press stop). On the phone, that episode is checked and Continue points at the next episode, near the start. On Kodi B, Continue shows the show, and the episode list checks the finished episode and does not check the next one. Play the next episode on B and confirm it starts at the beginning, not at the previous episode's end.
5. On Kodi A, start episode 1 and, with binge on, let it run to the natural end so episode 2 autoplays. Pause on episode 2. On Kodi B, Continue shows episode 2's position, not a cleared row. Kodi A's log has no `final flush failed`, and episode 2's `now_playing` was not deleted mid-play (playback keeps reporting progress). This is the binge regression check.
6. Start a title on A and stop it within a second. B's Continue still shows it (the start put of `timeOffset` 1, or the real sample if one landed). Playing it on B does not resume at a bogus mid-episode point.
7. Log out on B. Continue shows only what was watched on B. Nothing from A appears. Local resume for a video watched on B still works.

## Risk assessment

The living-room bug is not a stale cache. The account row is either not written completely (no bitfield, no next-episode pointer) or not read (Continue and the episode list use `progress.json` only). Phone adds are a separate, smaller gap: they are already fetched live into the library band, and they disappear only when this profile is logged out, the fetch fails silently, or they fall past the 200 cap.

The dangerous part of the fix is the service stop callback and the bitfield, not the Continue merge. The callback already shares `now_playing.json` with binge in another process and already does a blocking put before an unconditional delete. The plan moves the put off that delete and makes the delete conditional. The bitfield is isolated in a new module and is written only when a real episode finishes and the video id list was attached at play time. Resume math, stream resolution, and `lib/stremio/api.py` stay put; resume starts working cross-device because Continue and the detail window copy the account offset into the local file the resume prompt already trusts.

Ship the pure merge, the bitfield tests, and the service-player tests before either Kodi is used to confirm steps 1–7.
