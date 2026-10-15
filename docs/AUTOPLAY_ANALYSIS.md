# Auto-play next episode (rev11) — what already exists

Written before the rev11 playback changes. This is a map of the code that
already moves from one episode to the next, and the decisions rev11 follows
from that map. The behavior Dylan asked for is at the end of each section.

## Binge today is after the file ends

`lib/ui/binge.py` is Kodi-free. `next_video(meta, current_video_id)` walks
`meta['videos']` in season, then episode, then release date. Season 0
(Specials) and a video with no season or episode sort last. The walk never
steps from a real episode into that tail: a season finale does not auto-play
a Special. Unknown id, last episode, or that guard all return `None`.

A season boundary is not a special case. S1's last episode is followed by
S2E1 when both are in `videos`, because season is the first sort key. The
series end is `next_video` returning `None`.

`pick_binge_stream(pairs, binge_group)` prefers the pair whose
`info['binge_group']` equals the stream that just played
(`behaviorHints.bingeGroup`). Otherwise it takes `pairs[0]`. The caller has
already sorted by the user's `stream_sort` (default quality). It does not
look at the debrid cache flag.

`lib/ui/streamswindow._try_binge_watch` is the only caller, and only after
`_wait_for_playback_end()` reports `ended_naturally`. A user Stop never
enters it. The loop is: next video, fetch its streams, sort, pick, show
`RivuletCountdown`, `play_direct`, wait again. Settings are `binge_enable`
(default on) and `binge_countdown` (default 10, minimum 3, maximum 60).
Strings `#30182` "Next episode" and `#30183` "Playing %s in %d s".

The countdown's `run()` blocks. True means the timer ran out or the user
pressed Select ("play now"). None means Back. False means Kodi is shutting
down; the caller reopens nothing. The countdown window is shown with
`show()`, not `doModal()`, and its `onAction` is deliberately not behind
`@gated_input`, so Back and Select work while the rest of Rivulet is ignoring
input.

There is no "still watching?" cap. The loop runs until the series ends, the
user stops, the countdown is cancelled, or a fetch or resolve fails.

There is no credits timestamp on a Stremio video. `meta['videos']` entries
carry id, season, episode, title, released. "Credits" in rev11 means the
configurable seconds-before-the-end window, not a marker from the addon.

## The player service, the resume file, and sync

`lib/service_runner.build_progress_player` is a long-lived `xbmc.Player`.
Every callback no-ops unless `now_playing.json` is a Rivulet context.

`onAVStarted` reads `resume_offset.json`, seeks once, and clears it. No
offset means an opening push at 1 ms (Stremio's "just started" pointer), not
a seek. `getTime()` is the wrong source there: the seek is still in flight.
A new episode, including a binge handoff, resets the push clock so the
previous episode's timestamp cannot swallow the new opening push.

`resume_offset.json` is a separate one-shot file on purpose. Do not fold it
into `now_playing.json`. Do not change the consumer.

`sample_if_playing` is the only place that calls `getTime()` /
`getTotalTime()`, and only while `isPlayingVideo()` is true. The stop, end,
and error callbacks must not: they fire after `CVideoPlayer::CloseFile()` and
those getters raise, which Kodi logs even when caught. The final flush
replays the last live sample.

`onAVStarted` snapshots the context it accepted. The stop callback pushes
that snapshot, not whatever `now_playing.json` holds by then, because a binge
handoff may already have replaced the file. `clear_now_playing_if(started_at)`
deletes the file only when `started_at` still matches, so it cannot erase the
next episode. A second terminal callback is ignored so it cannot clear the
next episode's context either.

`should_mark_watched` (`lib/librarysync.py`): a player error never marks
watched. A natural end (`onPlayBackEnded`) always does. A user stop marks
only when the last sample is past 90% of the duration
(`WATCHED_THRESHOLD_RATIO`).

`finish_playback` sets the watched bit only when `video_id` is in
`video_ids`. Otherwise it leaves the existing bitfield alone, including
`None`. If `next_video_id` is a different id, `advance_to_video` points the
library item at that episode, clears the measured offset, and parks
`timeOffset` at 1 with `duration` 0 (Continue shows the show, but not as a
resume position). No next id zeroes `timeOffset` so Continue drops it.
`flaggedWatched` / `timesWatched` still flip on finish.

`play_direct` writes `now_playing` only after the stream resolves. It fills
`video_ids` (`sorted_video_ids`) and `next_video_id` (`binge.next_video`)
from `item_meta['meta']['videos']`. Empty `videos` means an empty list and
no next id, and a finish then cannot mark the episode or advance Continue.
That is why Continue Resume fetches meta before play.

An early cut (stop the file during the credits so the next episode can
start) arrives as `onPlayBackStopped`, not `onPlayBackEnded`. A 40-minute
episode with 30 seconds left is already past 90%, so the stop path marks it
watched anyway. A short episode is not: 30 seconds left of a 60-second file
is under 90%. Rev11 therefore writes a one-shot `autoplay_finish.json`,
keyed by the accepted `started_at` and `video_id`, before `play()` replaces
the item. The final flush ORs that into `finished` and clears it only on a
match. A mismatch is left in place so the new episode's stop cannot consume
the previous episode's flag. The flag is armed from `play_direct`'s
`on_ready`, which runs only after resolve succeeds and before `play()`. A
resolve failure never arms it and never stops the current episode.

The next episode's `play_direct` passes `resume_offset_ms=0`. That skips the
resume confirm and queues no seek, so the new episode does not inherit the
one that just finished. `onAVStarted` then pushes the 1 ms fresh start.
`_remember_last_stream` still records the source that resolved, which is
what the next Continue Resume will replay.

## Stop-return

`close_windows_for_playback` sets the phase to `player` and closes the
stack, marking ancestors so `doModal` reopens them after the nested call
returns. The phase stays `player` through `_wait_for_playback_end` (until
Kodi's stop/end/error callback, which is after `CloseFile()` returns) and
the 0.5 s settle. Ending the phase in that gap is what let a Stop refresh
`Dialog.Close(all)` the stack. The restored picker's `doModal` ends the
phase. Continue has no picker between Home and the player, so the direct
resume path ends the phase itself or Home would stay deaf.

`_wait_for_playback_end` returns `(proceed, ended_naturally)`. `proceed` is
False only on a monitor abort or an unexpected exception. `ended_naturally`
is True only for `onPlayBackEnded`. The poll does not call `getTime()`.
Calling it while `isPlaying()` is true is safe. Calling it from the stop
callback is not.

Back on the Up next card means "do not start the next episode". It does not
stop the episode that is still playing. When that episode later ends, the
usual stop-return runs: the picker if playback started there, Home if it
started from Continue Resume. Select, or the countdown running out, starts
the next episode. A Kodi shutdown still reopens nothing.

## Continue Resume today

`_handle_continue` (`lib/ui/homewindow.py`) asks only for a Continue-shelf
poster whose position is in the resume band. Series: "Resume S#E# from
mm:ss" or "Episode list". Movies: "Resume from mm:ss" or "Details". Back
closes the dialog.

Resume fetches meta (so `videos` is on the context), replays
`get_last_stream`, and `play_direct`s with the saved offset and
`on_ready=close_windows_for_playback`. `_hold_until_playback_ends` waits,
settles, ends the phase, and returns. It discards `ended_naturally`. A
natural end and a user Stop both land on Home. There is no binge.

A missing stream, a store error, or `play_direct` returning False opens the
existing picker with the offset on the first pick only. That picker already
binges on a natural end.

Rev11 keeps the dialog, the last-stream replay, the seek, and the picker
fallback. The direct path joins the same chain as the picker: a natural end,
or an accepted Up next card, rolls into the next episode instead of Home.
User Stop, Back on the card, series end, and a failed resolve still return
Home (or the picker, when playback started from the picker).

## Cache and quality

`lib/stremio/streaminfo.parse_stream` sets `info['cached']` to True, False,
or None from debrid name and emoji markers (`[RD+]`, `[RD download]`,
`(Instant RD)`, the bolt, and the bare-code fallbacks). `filter_streams`
with `cached_only=True` drops anything that is not True. None is not cached.

`playback_min_quality`, `playback_max_size_gb`, `playback_exclude_cam`, and
`playback_cached_only` filter the picker. They are not the auto-play
settings. Auto-play applies those filters first (a CAM the user hid stays
hidden), then its own cap and its own cached-only switch.

There is no max-height filter today. `playback_min_quality` only drops known
heights below a floor. Unknown resolution is kept, on the picker and for
auto-play: hiding an unparsed title would turn a parser gap into a missing
source. A known height above the cap is dropped.

Rev2 has a separate cached regex in `lib/ui/rev2/rank.py`. It stays there.

## What rev11 changes

One card, not two. While the file is playing and the remaining time is
within `binge_lead_seconds` (default 30), show the card. Select or the
countdown (`binge_countdown`) starts the next episode then, cutting the
credits. `on_ready` arms `autoplay_finish.json` so the stop flush marks this
episode watched even under 90%, then `play()` starts the next one fresh.
If the file ends during the card, the next episode starts without a second
card and without the flag: `onPlayBackEnded` already marks it watched.

If the position never enters that window (duration unknown, `getTime`
failed, the user seeked past it), the existing post-end countdown is the
card. Back on either card suppresses the other.

Pick order, after the playback filters and the quality cap:

1. Known heights above the cap are out. `highest` means no cap. `1080p`
   caps at 1080. `2160p` (labeled 4K) caps at 2160.
2. Among what remains, the highest known resolution that is cached
   (`info['cached'] is True`). Unknown resolution ranks below every known
   height.
3. `binge_group` breaks a tie inside that same height and cache class, so
   the old "same release" preference still wins when quality and cache do
   not differ. It does not pick an uncached or lower stream over a cached
   higher one.
4. If nothing is cached and `binge_cached_only` is off, the best remaining
   stream (same height rule, then the caller's order).
5. If nothing qualifies, do not auto-play. Stop-return runs.

`binge_still_watching` (default 3, 0 means ask every time) counts episodes
this chain started by itself, not the one the user pressed play on. At the
cap, the card is "Are you still watching?". Select resets the count and
plays. Back, or the countdown running out, does not play. The episode
ending during that prompt does not play the next one either.

Season boundary: `next_video` already returns the next season's first
episode. Series end: it returns `None`, no card, stop-return. No cached
stream when cached-only is on: no `play_direct`, stop-return. Resolve
failure: the current episode keeps playing (the flag was not armed), the
chain stops, stop-return when it ends. User cancel: the chain stops,
stop-return when the current episode ends.

Settings reused: `binge_enable`, `binge_countdown`. New: `binge_lead_seconds`,
`binge_quality` (`highest` / `1080p` / `2160p`), `binge_cached_only`,
`binge_still_watching`. New strings start at `#30442`. `binge_cached_only`
is also a row in the Rev2 playback pane. The integer and list settings stay
in Kodi's settings dialog, same as `binge_countdown`.

`pick_binge_stream` stays for the tests that pin the old binge-group rule.
The chain calls `pick_up_next_stream`.
