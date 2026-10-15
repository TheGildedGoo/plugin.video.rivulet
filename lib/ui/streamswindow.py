# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""StreamsWindow: the resolved-source picker for one title/episode -
Rivulet's custom replacement for the classical `streams()` directory.

Picking a row resolves and plays it DIRECTLY via
`lib.ui.player.play_direct` (no ADDON_HANDLE/`setResolvedUrl` - see that
function's docstring), so Kodi's player takes over the full screen.

Once playback actually starts and later stops - or never starts at all
within a short timeout, see `_wait_for_playback_end()` - `open_streams()`
reopens a fresh `StreamsWindow` over the SAME already-fetched
pairs/heading/art/poster (no addon re-fetch) so the user lands back on
the picker instead of falling all the way through to Kodi's main menu;
"Back" out of THAT reopened window is what finally returns control to
whatever opened `open_streams()` in the first place. Consequently
`open_streams()` now only ever returns False: once for the user backing
out of a window (the first one, or a reopened one) with no pick, and
once more for a fetch/window failure - it never returns True. Every
`if open_streams(...): self.close()` (or `return open_streams(...)`)
branch up the call chain (`DetailWindow`, `CatalogPickerWindow`,
`SearchWindow` via `open_detail`) is consequently dormant: those
callers stay open underneath for the round trip's "reopen" to sit on
top of, and simply resume (natural Back navigation) once
`open_streams()` finally returns.

The wait between "play" and "reopen" is phase 2 of `lib.ui.uicommon`'s
three UI phases (see its "UI phases" notes): from the handoff until Kodi
has announced the player closed - which is after CVideoPlayer::CloseFile()
returned, up to seconds after `isPlaying()` went False - every Rivulet
screen ignores input and a Kodi re-run of the plugin root is a no-op. Only
then does the phase end and ONE picker open.

`open_streams()`/`StreamsWindow.start()` also take optional `heading`/
`art` context kwargs (`heading='<title>'`, `art={'poster': ...,
'fanart': ...}`) - the pre-agreed cross-agent contract `DetailWindow`
(an episode's "<Show> - SxxExx <Title>" + the show's own art) and
`ShowcaseWindow`'s movie path (the movie's own title/art) both call into.
Both default to "nothing supplied" (`''`/`None`) so a bare `poster=`
kwarg, or no context at all, keeps every pre-existing call site working
unchanged: an empty heading falls back to a generic localized "Streams"
title, and no `art` simply means the side poster panel stays empty.

`meta` is a similar optional caller-context kwarg - the same Stremio
meta dict `DetailWindow`/`ShowcaseWindow`/`open_detail()` already have in
hand - rendered read-only into the side info panel (year/runtime/
rating/genres, plus a single-provider dedupe note); omitted or `None`
leaves that panel empty exactly like today.

`open_streams()`/`StreamsWindow.start()` also take an optional
`video_id=None` kwarg - the id of the episode whose streams are being
shown, threaded from `lib.ui.detailwindow`'s episode click (the only
caller that has one; a movie or any other context-free call keeps
defaulting to `None`, so nothing below ever runs for it). Near the end
of a series episode (see `binge_lead_seconds`; there is no credits
timestamp on the meta), or after a natural end when the duration was
never known, `_after_playback()` shows an Up next card. Select or the
countdown auto-plays the next episode's cached-highest stream (see
`lib.ui.binge.pick_up_next_stream`). Back, a user Stop, the series
ending, a cached-only miss, or a failed resolve all fall back to the
SAME "reopen the picker" round trip described above - `open_streams()`
still only ever returns False. Continue Resume calls the same helper
and returns Home instead of reopening a picker.

Every installed addon's own stream fetch runs CONCURRENTLY, not one at
a time: real user logs showed the old serial `for` loop - each addon
call bounded by `AddonClient`'s own 15s timeout - taking as long as
27.6s to open this picker, and 5.0s even in the ordinary case, because
one slow or unresponsive addon held up every addon queued behind it
(`streamswindow: 1 addon(s) failed` on every single fetch, whether or
not that addon was the slow one). `_fetch_stream_pairs()` (still used
by `_try_binge_watch()`) fetches every addon concurrently but still
blocks until all of them answer; `open_streams()` goes
further and opens the picker as soon as the FIRST addon answers with
streams. A timeout or error is retried silently (see
`_STREAM_ATTEMPTS`) while the spinner stays up; an empty success is
the addon's answer and is not retried. The rest stream their own
results in live onto the open
`StreamsWindow` (`StreamsWindow.add_pairs()`/`set_loading()`) exactly
like `infowindow.ShowcaseWindow`'s background meta-enrich worker feeds
an already-open coverflow - see that module's docstring and
`add_pairs()`'s own docstring below for the worker->GUI handoff both
share. That live phase only ever feeds the FIRST window a picker opens;
every reopen after a played pick (or a binge-watched one) works off
whatever `StreamsWindow.pairs` had already accumulated by then, a
static snapshot, never resumes listening for more addons.

Opening on the first answer used to leave the list blank: the only
status was a "Loading more sources..." line in the side panel, under
the poster, and Kodi's list selects the LAST row when items are added
(and again when the list takes focus). A title with many sources
therefore opened scrolled to the bottom of a list that had not finished
painting. The column header now shows "Loading all sources…" with how
many addons have answered (`set_load_progress()`) until `set_loading(False)`.
Until the user moves the cursor, every rebuild during that fan-out —
including the one that clears the line — puts the cursor back on row 0,
the best stream after `sort_streams()`.
"""
import queue
import threading

import xbmcgui

from lib.stremio import streaminfo
from lib.ui.binge import next_video, pick_up_next_stream
from lib.ui.dependencies import get_client, get_store
from lib.ui.uicommon import (
    BaseWindow,
    busy_dialog,
    close_windows_for_playback,
    deliver_queued_input,
    end_player_phase,
    escape_label,
    gated_input,
    open_window,
)

BACKGROUND = 30000
LIST = 30002
POSTER = 30004
HEADING = 30005
INFO_PANEL = 30008
#: The left column's "NN SOURCES" / "NN ADDONS" / "NN CACHED" summary -
#: three separate labels (see StreamsWindow.xml) rather than 3 lines of
#: INFO_PANEL, since a textbox only supports one font/colour for its
#: whole content and the CACHED line needs its own green tint.
SOURCES_COUNT = 30100
ADDONS_COUNT = 30101
CACHED_COUNT = 30102
#: Column-header status while the fan-out is still outstanding. Python
#: owns its visibility (no static `<visible>` in the skin): a hardcoded
#: false would outrank `setVisible(True)` on real Kodi, the same trap
#: BusyDialog.xml's progress bar documents. Sits in the list column,
#: not the side panel — the old INFO_PANEL line was under the poster
#: and the list itself looked empty.
LOADING_STATUS = 30110

#: Cap on concurrent addon HTTP calls a streams fan-out below opens at
#: once - mirrors `lib.ui.views._MAX_ADDON_WORKERS`'s bounded-pool
#: convention (kept as its own local constant, since each fan-out point
#: in this addon bounds its OWN pool rather than sharing one - this one
#: also runs on low-power ARM boxes, where an unbounded thread-per-addon
#: fan-out would be its own liability). Each AddonClient call still
#: carries its own 15s timeout; this only lets that timeout run
#: concurrently across addons instead of serializing N of them one
#: after another - see the module docstring for the measured 5.0s/
#: 27.6s cost of the old serial loop this replaces.
_MAX_STREAM_ADDON_WORKERS = 8

#: strings.po ids for LOADING_STATUS. 30452 is the answered/total
#: form. The numbers are a fraction, not an inflected noun — the
#: catalogs have no plural machinery that would get "3 addons" right
#: in Polish or Arabic. 30185 stays in the catalogs; it was the old
#: side-panel line this header replaced.
_LOADING_HEADING_STRING_ID = 30451
_LOADING_PROGRESS_STRING_ID = 30452

#: Action ids that mean the user moved the cursor. Kodi selects the
#: last row on its own when items are added; treating that as a choice
#: is how the finished list opened on the bottom. The noop wake the
#: fan-out uses (`Action(noop)`) and Back are deliberately absent.
_CURSOR_MOVE_ACTIONS = frozenset({
    3, 4,  # up, down
    5, 6,  # page up, page down
    14, 15,  # next item, previous item
    104, 105,  # mouse wheel
    111, 112,  # scroll
})

#: strings.po ids for the left column's localized 'N SOURCE(S)' / 'N
#: ADDON(S)' / 'N CACHED' summary counts (see _rebuild_list()) -
#: singular msgstr picked for a count of exactly 1, plural otherwise
#: (0 included, matching the plural rule every target language's own
#: translation uses for "not one"). CACHED has only one form: it
#: describes how many of the sources are cached, not a countable noun
#: of its own.
_SOURCE_STRING_ID = 30200
_SOURCES_STRING_ID = 30201
_ADDON_STRING_ID = 30202
_ADDONS_STRING_ID = 30203
_CACHED_STRING_ID = 30208

#: strings.po id for the range terminator a still-running series gets in
#: place of a dangling dash ('2022–now') - see `_rebuild_list()`. The
#: same id DetailWindow and the coverflow hero use.
_NOW_STRING_ID = 30234

#: resources/settings.xml keys for the four 'playback_*' stream-filter
#: controls (see that file's 'playback' category). Read fresh on every
#: `_rebuild_list()` call by `_read_stream_filters()` below rather than
#: cached anywhere on the window - Kodi's Settings dialog is its own
#: modal the user can open and change these in without ever closing
#: this picker first.
_MIN_QUALITY_SETTING = 'playback_min_quality'
_MAX_SIZE_GB_SETTING = 'playback_max_size_gb'
_EXCLUDE_CAM_SETTING = 'playback_exclude_cam'
_CACHED_ONLY_SETTING = 'playback_cached_only'

#: `playback_min_quality`'s select values -> `streaminfo.filter_streams()`'s
#: `min_height`. 'any' (and anything unrecognised, e.g. a stale value
#: left over from a settings.xml downgrade) maps to 0, filter_streams()'s
#: own "no filtering on this axis" sentinel.
_MIN_QUALITY_HEIGHTS = {'480p': 480, '720p': 720, '1080p': 1080, '2160p': 2160}

#: strings.po ids for the INFO_PANEL's "N hidden by filters" line and the
#: "filters matched nothing" fallback notice - see `_rebuild_list()`'s
#: filtering step. Singular/plural picked the same way as
#: `_SOURCE_STRING_ID`/`_SOURCES_STRING_ID` above.
_HIDDEN_STRING_ID = 30262
_HIDDEN_PLURAL_STRING_ID = 30263
_FILTERS_MATCHED_NOTHING_STRING_ID = 30264

#: Settle pause between "Kodi announced the player closed"
#: (`_wait_for_playback_end()`) and the player phase ending
#: (`uicommon.end_player_phase()`): spent calling into Kodi, which is what
#: delivers - to screens still ignoring input - whatever was queued while
#: the player owned the screen, so none of it reaches the picker that opens
#: right after. Also reused after each binge-watching auto-played episode,
#: below.
_REOPEN_SETTLE_SECONDS = 0.5

#: `_wait_for_playback_end()`'s default `start_timeout` - how long it
#: waits for `xbmc.Player().isPlaying()` to first report True before
#: giving up on a stream that never actually started. Raised from an
#: original 20.0: a live desktop measurement of an inputstream.adaptive
#: (HLS/DASH) stream opening through Kodi's player showed a real 19.8s
#: gap between `play_direct()` returning and `isPlaying()` finally going
#: True - a slower device, or a plain ffmpeg-fallback stream competing
#: for CPU with muxing, has essentially no margin left at 20.0. This is
#: purely an upper BOUND on the give-up wait, not a floor a fast stream
#: is held to: the poll loop below breaks the instant `isPlaying()` goes
#: True, and every `tick`-second step still re-checks `monitor.
#: waitForAbort()`, so a user cancel/Kodi shutdown during that wait
#: exits within one `tick`, exactly as promptly as before this change.
_PLAYBACK_START_TIMEOUT_SECONDS = 45.0

#: Upper bound on how long `_wait_for_playback_end()` waits, AFTER
#: `isPlaying()` went False, for Kodi's stop/end/error callback. Kodi flips
#: `isPlaying()` at the START of CVideoPlayer::CloseFile() but announces the
#: callbacks only once it RETURNED - and CloseFile() cannot return while the
#: HTTP cache thread is blocked in a read it has no way to cancel (kodi.log
#: 01:07:53.96 CloseFile -> 01:07:59.98 "finished waiting": 6s, against a
#: torrent whose next piece had not arrived; the service's callback landed at
#: 01:08:00.137). The reopen must wait for that, or the new window is queued
#: behind a frozen GUI thread and the Videos window's own refresh lands on top
#: of it. Generous because a stalled stream can take the whole
#: `curllowspeedtime` (resources/advancedsettings.xml); on expiry the wait
#: gives up and reopens anyway, so a callback that never comes cannot strand
#: the user on an empty screen.
_PLAYER_CLOSE_TIMEOUT_SECONDS = 60.0

#: resources/settings.xml keys for the two binge-watching controls.
_BINGE_ENABLE_SETTING = 'binge_enable'
_BINGE_COUNTDOWN_SETTING = 'binge_countdown'

#: Fallback/floor for the 'binge_countdown' setting - mirrors its own
#: <default>/<constraints><minimum> in resources/settings.xml.
_BINGE_COUNTDOWN_DEFAULT_SECONDS = 10
_BINGE_COUNTDOWN_MIN_SECONDS = 3

#: How early the Up next card appears. There is no credits timestamp on
#: a Stremio video, so this window IS the credits. Default 30s.
_BINGE_LEAD_SETTING = 'binge_lead_seconds'
_BINGE_LEAD_DEFAULT_SECONDS = 30
_BINGE_LEAD_MIN_SECONDS = 5

#: `binge_quality` select values -> a max height. `highest` (and anything
#: unrecognised) is 0, "no cap". Known heights above the cap are dropped;
#: an unparsed resolution is kept.
_BINGE_QUALITY_SETTING = 'binge_quality'
_BINGE_QUALITY_CAPS = {'1080p': 1080, '2160p': 2160}

_BINGE_CACHED_ONLY_SETTING = 'binge_cached_only'

#: How many episodes THIS chain may start before "Are you still watching?".
#: 0 asks every time. The episode the user pressed play on is not counted.
_BINGE_STILL_WATCHING_SETTING = 'binge_still_watching'
_BINGE_STILL_WATCHING_DEFAULT = 3

#: strings.po ids for the countdown dialog. The heading is "Up next".
#: The message is the '%s'/'%d' "Playing <label> in <N> s" line, which
#: `_binge_countdown()` re-formats on every tick. The still-watching
#: prompt reuses the same window with its own heading and a message
#: that does not promise the timer will start playback.
_BINGE_DIALOG_MESSAGE_STRING_ID = 30183
_UP_NEXT_HEADING_STRING_ID = 30445
_STILL_WATCHING_HEADING_STRING_ID = 30449
_STILL_WATCHING_MESSAGE_STRING_ID = 30450


def _read_stream_filters():
    """Read the four 'playback_*' settings into
    `streaminfo.filter_streams()`'s kwargs (see the constants above).
    `playback_max_size_gb` is a GB slider - a human picks a size in GB,
    not bytes - converted here to the byte unit `filter_streams()`/
    `parse_stream()`'s own `size_bytes` already uses."""
    from lib.ui.compat import ADDON, setting_bool, setting_int

    min_quality = ADDON.getSetting(_MIN_QUALITY_SETTING) or 'any'
    max_size_gb = setting_int(_MAX_SIZE_GB_SETTING, 0, minimum=0)
    return {
        'min_height': _MIN_QUALITY_HEIGHTS.get(min_quality, 0),
        'max_size_bytes': max_size_gb * 1024 ** 3,
        'exclude_cam': setting_bool(_EXCLUDE_CAM_SETTING, False),
        'cached_only': setting_bool(_CACHED_ONLY_SETTING, False),
    }


class StreamsWindow(BaseWindow):
    """See module docstring. Built/run via `open_streams()`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pairs = []
        self.stype = 'movie'
        self.sid = None
        self.poster = None
        self.heading = ''
        self.art = None
        self.meta = None
        self.video_id = None
        self.played = False
        self.played_pair = None
        #: Set by start() when Continue already chose Resume. The first
        #: successful pick seeks here and skips the confirm. Cleared on
        #: success so a later pick in this same window asks as usual.
        self._forced_resume_ms = None
        #: True once close() has run - add_pairs()/set_loading() become
        #: silent no-ops from then on, so a straggling addon answering
        #: after the user backed out (or after playback started) never
        #: touches a torn-down window. See close()/add_pairs().
        self._closed = False
        #: True while `onClick()` is preparing a pick - see onClick() for
        #: why a second pick arriving meanwhile is dropped.
        self._pick_in_progress = False
        #: Guards `_pending_batches`/`_pending_loading` below - written
        #: by add_pairs()/set_loading() from a background fetch thread,
        #: drained by `_merge_pending()` on the GUI thread only. Mirrors
        #: `infowindow.ShowcaseWindow`'s `_enrich_lock`/`_enrich_pending`
        #: worker->GUI handoff exactly.
        self._pending_lock = threading.Lock()
        self._pending_batches = []
        self._pending_loading = None
        #: `(answered, total)` queued by `set_load_progress()`, or None
        #: when the count has not changed. Same lock as the batches.
        self._pending_progress = None
        #: True while `open_streams()`'s own fan-out still has an addon
        #: outstanding. LOADING_STATUS stays visible until the last one
        #: answers (`set_loading(False)`).
        self._loading = False
        #: Addons answered so far, and how many were asked. Fed by
        #: `set_load_progress()`; 0/0 means the count is not known yet
        #: and the header falls back to the heading with no fraction.
        self._load_answered = 0
        self._load_total = 0
        #: True once the user moves the cursor (see `_CURSOR_MOVE_ACTIONS`).
        #: While this is false and a fan-out is in progress, a rebuild
        #: puts the cursor on row 0 instead of keeping whichever row
        #: Kodi selected — the last one, after `addItems()`.
        self._user_moved_cursor = False
        #: The prefix of `self.pairs` (by OBJECT IDENTITY, oldest-first)
        #: LIST currently holds - set by `_rebuild_list()` every time it
        #: runs. `_append_prefix_length()` compares this against a fresh
        #: `self.pairs` to decide whether `_apply_pending()` can append
        #: just the new suffix instead of a full reset()+rebuild - see
        #: both methods.
        self._rendered_pairs = []
        #: The `single_provider` value `_rebuild_list()` used to build
        #: `self._rendered_pairs` above - a second addon's batch turning
        #: a single-provider list into a multi-provider one changes line
        #: 1 of every ALREADY-rendered row (the addon-name dedupe), so
        #: `_append_prefix_length()` must catch that even when every
        #: pair's own identity is unchanged.
        self._rendered_single_provider = None
        #: The `display_pairs` sequence (by OBJECT IDENTITY, in
        #: `self.pairs` order) `_rebuild_list()` last actually put into
        #: LIST - a strict superset check against `self._rendered_pairs`
        #: above is not enough: a pending batch can flip
        #: `_stream_filter_view()`'s "filters matched nothing" fallback
        #: from true to false (the batch gives a previously-starved
        #: filter something real to keep), which changes which of the
        #: OLD prefix's rows are still visible even though none of them
        #: moved and `single_provider` didn't change either -
        #: `_append_prefix_length()` compares against this to catch it.
        self._rendered_visible_pairs = []
        #: `_row_render()`'s cache of each `info` dict's OWN
        #: (line1, line2, properties) row material, keyed by `id(info)` -
        #: see that method's docstring for why only `line1` (never
        #: `line2`/`properties`) needs redoing when `include_addon` flips.
        self._row_cache = {}

    def start(
        self, pairs, stype, sid, poster=None, heading='', art=None, meta=None,
        video_id=None, resume_offset_ms=None,
    ):
        """doModal() showing `pairs` (a list of `(info, stream)` as
        `lib.stremio.streaminfo.parse_stream`/`sort_streams` produce).
        `heading`/`art`/`meta` are the optional caller-context kwargs
        described in the module docstring; `video_id` is the episode
        `pairs` belongs to (`None` for a movie or a context-free call -
        see the module docstring's binge-watching paragraph). A caller
        wanting the picker to open before every addon has answered
        calls `set_loading(True)`/`add_pairs()` on this window BEFORE
        this method (see `open_streams()`) - neither is reset here, so
        anything already queued still lands in `onInit()`'s first
        build. Returns True if playback started (the caller should
        also close)."""
        self.pairs = list(pairs or [])
        self.stype = stype
        self.sid = sid
        self.poster = poster
        self.heading = heading or ''
        self.art = art
        self.meta = meta
        self.video_id = video_id
        self.played = False
        self.played_pair = None
        self._forced_resume_ms = resume_offset_ms if resume_offset_ms else None
        self._closed = False
        self._pick_in_progress = False
        if not self.pairs:
            return False
        self.doModal()
        return self.played

    def close(self):
        # Any exit path must stop accepting further live updates before
        # the underlying window (and its controls) actually goes away -
        # see add_pairs()/set_loading()'s own no-op-after-close contract.
        # A force-close for playback reopens THIS window. The fan-out
        # drops updates while `_closed` is set, including the
        # `set_loading(False)` that means it finished, so the reopened
        # picker must not keep "Loading all sources…" up forever.
        self._closed = True
        self._loading = False
        super().close()

    def add_pairs(self, pairs):
        """Thread-safe: queue one addon's OWN batch of `(info, stream)`
        pairs - called by `open_streams()`'s streaming fan-out as each
        addon answers, from a background fetch thread, NEVER the GUI
        thread. Mirrors `infowindow.ShowcaseWindow._enrich_fetch()`'s
        worker->GUI handoff exactly: this never touches a control or
        `self.pairs` directly - it only queues the batch, then wakes the
        GUI thread with `Action(noop)`, which lands on `onAction()`'s
        own `_apply_pending()` drain below. A silent no-op once this
        window has closed, or for an empty batch."""
        if not pairs:
            return
        with self._pending_lock:
            if self._closed:
                return
            self._pending_batches.append(list(pairs))
        self._wake()

    def set_loading(self, loading):
        """Thread-safe toggle for the "Loading all sources…" header
        (see `_refresh_loading_label()`) - `True` while
        `open_streams()`'s fan-out still has an addon outstanding,
        `False` once the last one has answered. Same worker->GUI
        handoff as `add_pairs()`; a silent no-op once this window has
        closed."""
        with self._pending_lock:
            if self._closed:
                return
            self._pending_loading = bool(loading)
        self._wake()

    def set_load_progress(self, answered, total):
        """Thread-safe answered/total count for the loading header.

        `answered` is how many addons have returned (including an empty
        list — that is still an answer) and `total` is how many were
        asked. A count-only tick refreshes the label without rebuilding
        LIST, so it cannot move the cursor. A silent no-op once this
        window has closed."""
        with self._pending_lock:
            if self._closed:
                return
            self._pending_progress = (int(answered), int(total))
        self._wake()

    def _wake(self):
        import xbmc
        xbmc.executebuiltin('Action(noop)')

    def _merge_pending(self):
        """Pull whatever `add_pairs()`/`set_loading()` queued onto
        `self.pairs`/`self._loading` - GUI thread only. Re-sorts the
        WHOLE list with the user's `stream_sort` setting, since a fast
        addon landing after a slow one can outrank rows already on
        screen. Returns True if anything actually changed, so a caller
        only rebuilds the list when there is something new to show."""
        with self._pending_lock:
            if (not self._pending_batches and self._pending_loading is None
                    and self._pending_progress is None):
                return False
            batches, self._pending_batches = self._pending_batches, []
            loading, self._pending_loading = self._pending_loading, None
            progress, self._pending_progress = self._pending_progress, None
        if batches:
            for batch in batches:
                self.pairs.extend(batch)
            from lib.ui.compat import ADDON
            sort_key = ADDON.getSetting('stream_sort') or 'quality'
            self.pairs = streaminfo.sort_streams(self.pairs, key=sort_key)
        if loading is not None:
            self._loading = loading
        if progress is not None:
            self._load_answered, self._load_total = progress
        # A count tick on its own must not rebuild LIST. `addItems()` —
        # even of nothing — is what moves Kodi's cursor, and the header
        # is a label, not a row.
        changed = bool(batches) or loading is not None
        if progress is not None and not changed:
            self._refresh_loading_label()
        return changed

    def _apply_pending(self):
        """`onAction()`'s live-merge drain - GUI thread only. Rebuilds
        LIST/INFO_PANEL when `_merge_pending()` finds something new.
        `_rebuild_list()` takes an append-only fast path (see
        `_append_prefix_length()`) whenever the previously-rendered rows
        are still an untouched PREFIX of the freshly re-sorted
        `self.pairs` - the common case, since a fast addon landing after
        a slow one usually sorts after what is already on screen.

        Either way, the focused row is re-found by OBJECT IDENTITY (`is`,
        not `==` - two different streams can compare equal as `(info,
        stream)` tuples) in `self._rendered_visible_pairs` - the VISIBLE
        list `_rebuild_list()` just built into LIST - never in raw
        `self.pairs`: a filter can hide any number of pairs ahead of the
        focused one, so a `self.pairs` index and LIST's row index are not
        the same number, and passing the former to `selectItem()` picks
        the wrong row (or one past the end of LIST) the moment filtering
        is involved. Falls back to the same numeric ROW position
        (clamped to the new, possibly-shorter, visible list) when the
        previously-focused pair is no longer visible at all - a filter
        change hid it, or there was no focused pair to begin with -
        since landing on whatever now occupies that slot keeps the
        cursor in a stable spot on screen, rather than jumping to some
        unrelated stream elsewhere in the list just because it happens
        to share the old raw index.

        That identity restore is skipped while a fan-out is in progress
        (and on the rebuild that ends it) until the user moves the
        cursor. Kodi selects the last row when items are added, and
        keeping that row is how the finished list opened on the bottom
        instead of the best stream."""
        control = self.getControl(LIST)
        focused = control.getSelectedItem()
        focus_index = control.getSelectedPosition()
        focus_pair = None
        if focused is not None:
            try:
                pos = int(focused.getProperty('position'))
            except (TypeError, ValueError):
                pos = -1
            if 0 <= pos < len(self.pairs):
                focus_pair = self.pairs[pos]

        loading_before = self._loading
        if not self._merge_pending():
            return

        start = self._append_prefix_length()
        self._rebuild_list(0 if start is None else start)
        visible = self._rendered_visible_pairs
        if not visible:
            return
        # The fan-out, and the rebuild that ends it, have no user choice
        # yet unless they already moved. Kodi selects the last row when
        # items are added; keeping that identity opens the finished list
        # on the bottom instead of the best stream.
        if not self._user_moved_cursor and (loading_before or self._loading):
            self._focus_first_stream()
            return
        if focus_pair is not None:
            for index, pair in enumerate(visible):
                if pair is focus_pair:
                    control.selectItem(index)
                    return
        control.selectItem(min(max(focus_index, 0), len(visible) - 1))

    def _stream_filter_view(self):
        """`(matched_nothing, display_pairs, hidden_count,
        single_provider, provider_count)` for `self.pairs` and the
        CURRENT 'playback_*' filter settings - shared by
        `_rebuild_list()` (which renders `display_pairs`) and
        `_append_prefix_length()` (which must invalidate its append-only
        fast path the instant filtering changes which addon(s) drive
        the single-provider dedupe, exactly like a raw addon batch
        arriving already does). Computed fresh every call, never cached
        on the window - see `_read_stream_filters()`'s own docstring
        for why.

        `matched_nothing` is true only when the filtered result is
        EMPTY but `self.pairs` itself is not - the "misconfigured
        filter" escape hatch: `display_pairs` then falls back to every
        pair, UNFILTERED, rather than an empty list, so a filter that
        happens to match nothing (e.g. 'minimum quality 2160p' against
        an addon that only found 1080p) can never look indistinguishable
        from `open_streams()`'s own "no sources found" empty-result
        path. `hidden_count` is 0 in that case too - nothing was
        actually left out of what's shown."""
        filters = _read_stream_filters()
        kept_pairs = streaminfo.filter_streams(self.pairs, **filters)
        matched_nothing = bool(self.pairs) and not kept_pairs
        display_pairs = self.pairs if matched_nothing else kept_pairs
        hidden_count = 0
        if not matched_nothing:
            _total, hidden_count = streaminfo.filter_summary(len(self.pairs), len(kept_pairs))
        providers = {info.get('addon') for info, _stream in display_pairs if info.get('addon')}
        single_provider = next(iter(providers)) if len(providers) == 1 else None
        return matched_nothing, display_pairs, hidden_count, single_provider, len(providers)

    def _append_prefix_length(self):
        """Returns how many of `self.pairs`, counted from the front, are
        the SAME already-rendered run `_rebuild_list()` last built into
        LIST - safe for `_apply_pending()` to leave untouched and only
        append past - or `None` if a full reset()+rebuild is required.
        Three things invalidate the prefix: (1) the re-sort moved one of
        those pairs (checked by OBJECT IDENTITY, `is` - pairs are reused
        across a merge, never rebuilt, see `_merge_pending()`, so an
        unmoved row is still the exact same tuple at the exact same
        index), (2) the single-provider addon-name dedupe
        (`_rebuild_list()`'s `single_provider`) flipped - that changes
        line 1 of every ALREADY-rendered row too, e.g. the picker
        opening on one addon's own results (no addon segment shown) and
        a second addon's batch then arriving (now shown on every row,
        including the ones already on screen) - or (3) which of the OLD
        prefix's pairs `_stream_filter_view()` actually DISPLAYS
        changed, even though none of them moved and `single_provider`
        stayed put: its "filters matched nothing" fallback can flip from
        true to false the instant this same batch gives a previously-
        starved filter something real to keep, which means some rows
        the fallback was showing unfiltered a moment ago are now hidden
        by the very filter that just started matching. Appending only
        the new suffix in that case would leave those stale fallback
        rows on screen forever, since nothing past `start` ever gets
        re-examined - see `self._rendered_visible_pairs`."""
        prev = self._rendered_pairs
        if not prev or len(prev) > len(self.pairs):
            return None
        for old, new in zip(prev, self.pairs):
            if old is not new:
                return None
        _matched_nothing, display_pairs, _hidden_count, single_provider, _n = self._stream_filter_view()
        if single_provider != self._rendered_single_provider:
            return None
        prev_ids = {id(pair) for pair in prev}
        visible_prefix = [pair for pair in display_pairs if id(pair) in prev_ids]
        if len(visible_prefix) != len(self._rendered_visible_pairs):
            return None
        for old, new in zip(self._rendered_visible_pairs, visible_prefix):
            if old is not new:
                return None
        return len(prev)

    def _rebuild_list(self, start=0):
        """Build LIST's rows from `self.pairs[start:]`, INFO_PANEL's text
        and the SOURCES_COUNT/ADDONS_COUNT/CACHED_COUNT summary labels
        from `self.meta`/`self.pairs` - shared by `onInit()` and
        `_apply_pending()`'s live merge so both build rows identically
        (single-provider dedupe included) instead of duplicating this
        logic. `start=0` (the default - `onInit()`'s first build, and
        `_apply_pending()`'s full-rebuild fallback) rebuilds every row
        via reset()+addItems(); `start` > 0 is `_apply_pending()`'s
        append-only fast path (see `_append_prefix_length()`) - only
        `self.pairs[start:]`'s rows get built and appended
        (`control.addItems()`, no `reset()`), instead of reconstructing
        Label/properties Kodi already has on screen for rows that never
        changed. Measured: a 400-stream, 20-addon-batch progressive
        fetch built 4200 rows total the old reset()+rebuild-everything-
        per-batch way (N*(M+1)/2), 400 with this path taken every time -
        it also removes the mid-scroll reset()/redraw that motivated
        `_apply_pending()`'s own focus-preservation workaround in the
        first place. INFO_PANEL and the summary counts below are always
        recomputed in full either way - they're label text, not per-row
        ListItem churn, so there is nothing to save there. Each row's
        ListItem carries both the packed Label/Label2
        (format_label()/format_details()) AND the discrete
        `streaminfo.stream_fields()` properties StreamsWindow.xml's row
        layout reads column-by-column; the packed pair is the skin's own
        fallback for a row with no discretely parsed quality/source/
        addon. Never touches focus - callers position the cursor
        themselves once this returns.

        Rows for a pair `streaminfo.filter_streams()` (via
        `_stream_filter_view()`) drops for the user's 'playback_*'
        settings are skipped here rather than removed from `self.pairs`
        itself - `position` stays a `self.pairs` index either way, so
        `_apply_pending()`'s focus-by-identity restore and this
        method's own append-only fast path both keep working exactly
        as if filtering didn't exist. When the filtered result would be
        EMPTY but `self.pairs` is not, `_stream_filter_view()` falls
        back to showing every pair unfiltered instead - a misconfigured
        filter must never look identical to `open_streams()`'s own "no
        sources found" empty-result path."""
        matched_nothing, display_pairs, hidden_count, single_provider, provider_count = self._stream_filter_view()
        kept_ids = {id(pair) for pair in display_pairs}

        items = []
        for index in range(start, len(self.pairs)):
            pair = self.pairs[index]
            if id(pair) not in kept_ids:
                continue
            info, _stream = pair
            line1, line2, properties = self._row_render(info, include_addon=not single_provider)
            item = xbmcgui.ListItem(line1, label2=line2)
            row_properties = dict(properties)
            row_properties['position'] = str(index)
            item.setProperties(row_properties)
            items.append(item)
        control = self.getControl(LIST)
        if start == 0:
            # reset() before addItems(): a full rebuild - onInit()
            # reopening a screen force-closed for playback, or a live
            # add_pairs() merge whose re-sort touched the already-
            # rendered prefix - onto a retained list would double every
            # item. The append-only path above (start > 0) skips this:
            # its rows are new, past the end of what LIST already has.
            control.reset()
        control.addItems(items)
        self._rendered_pairs = list(self.pairs)
        self._rendered_single_provider = single_provider
        self._rendered_visible_pairs = list(display_pairs)

        from lib.ui.compat import L
        from lib.ui.playbackmeta import year_range

        meta = self.meta or {}
        # A still-running series' open-ended range is closed with the
        # localized "now" rather than left as a dangling dash - see
        # `playbackmeta.year_range()`; DetailWindow and the coverflow
        # hero print the same range from the same id.
        year = year_range(meta.get('releaseInfo') or meta.get('year') or '', L(_NOW_STRING_ID))
        runtime = meta.get('runtime') or ''
        top_line = ' \u00b7 '.join(part for part in (year, runtime) if part)
        lines = [top_line] if top_line else []
        rating = meta.get('imdbRating')
        if rating:
            lines.append('\u2605 %s' % rating)
        genres = (meta.get('genres') or [])[:3]
        if genres:
            lines.append(' / '.join(genres))
        if single_provider:
            # single_provider is an addon-supplied name (untrusted
            # third-party JSON) rendered straight into INFO_PANEL text -
            # escape_label() neutralises any embedded markup first.
            lines.append('via %s' % escape_label(single_provider))
        if matched_nothing:
            lines.append(L(_FILTERS_MATCHED_NOTHING_STRING_ID))
        elif hidden_count:
            lines.append(L(_HIDDEN_STRING_ID if hidden_count == 1 else _HIDDEN_PLURAL_STRING_ID) % hidden_count)
        self.getControl(INFO_PANEL).setText('\n'.join(lines))
        self._refresh_loading_label()

        # Left column summary counts (design's stacked 'NN SOURCES' /
        # 'NN ADDONS' / 'NN CACHED' lines) - their own labels, not more
        # INFO_PANEL text, since INFO_PANEL is a textbox (one font/colour
        # for its whole content) and CACHED needs its own green tint.
        # `provider_count` is the distinct-addon count already computed
        # by `_stream_filter_view()` above for the single-provider
        # dedupe. Singular/plural msgstr picked per count - '1 ADDONS'
        # is wrong in English, and worse once translated, since most
        # locales don't pluralize like English.
        cached_count = sum(1 for info, _stream in display_pairs if info.get('cached') is True)
        source_count = len(display_pairs)
        addon_count = provider_count
        self.getControl(SOURCES_COUNT).setLabel(
            L(_SOURCE_STRING_ID if source_count == 1 else _SOURCES_STRING_ID) % source_count
        )
        self.getControl(ADDONS_COUNT).setLabel(
            L(_ADDON_STRING_ID if addon_count == 1 else _ADDONS_STRING_ID) % addon_count
        )
        self.getControl(CACHED_COUNT).setLabel(L(_CACHED_STRING_ID) % cached_count)

    def _refresh_loading_label(self):
        """Show or hide LOADING_STATUS from `self._loading` and the
        answered/total count. GUI thread only. A known total uses the
        fraction; otherwise the heading alone, so the list column is
        never blank while addons are still out."""
        from lib.ui.compat import L

        control = self.getControl(LOADING_STATUS)
        if not self._loading:
            control.setLabel('')
            control.setVisible(False)
            return
        total = self._load_total
        if total:
            answered = self._load_answered
            if answered < 0:
                answered = 0
            elif answered > total:
                answered = total
            control.setLabel(L(_LOADING_PROGRESS_STRING_ID) % (answered, total))
        else:
            control.setLabel(L(_LOADING_HEADING_STRING_ID))
        control.setVisible(True)

    def _focus_first_stream(self):
        """Put the cursor on row 0.

        That row is the best stream: `sort_streams()` ordered `self.pairs`
        before this list was built. Kodi selects the last row when items
        are added and again when the list takes focus, which is why a
        caller has to do this AFTER `setFocusId()` and AFTER `addItems()`,
        not before."""
        control = self.getControl(LIST)
        if control.size():
            control.selectItem(0)

    def _row_render(self, info, include_addon):
        """Cache `info`'s own (line1, line2, properties) row material by
        OBJECT IDENTITY across every `_rebuild_list()` call - each
        'playback_*' filter toggle re-runs that loop for every VISIBLE
        pair, and `streaminfo.format_details()`/`stream_fields()` never
        depend on `include_addon` (only `format_label()`'s own gray
        addon-segment does), so recomputing all three on every single
        toggle was pure waste. Only `line1` is redone when
        `include_addon` actually flips (the single-provider dedupe
        changing display_pairs' distinct-addon count) - `line2`/
        `properties` are computed once and kept forever.

        `line2` and the plain-text `properties` values (`release`/
        `flags`/`provider`) are addon-supplied text straight out of a
        third-party JSON payload rendered into a label/skin property -
        `escape_label()` neutralises any embedded `[B]`/`$INFO[...]`/...
        markup before either reaches a control. `line1` is left as-is
        here: `format_label()` packs its OWN intentional BBcode
        (`[COLOR ...]`/`[B]`) around the same untrusted fragments, and
        blanket-escaping the packed result would strip that wrapper
        right along with it - fixing that means escaping the
        interpolated fields inside `format_label()` itself, in
        `lib.stremio.streaminfo` (Kodi-independent, cannot import this
        module's `escape_label()`), not here. Its bare `raw`-text
        fallback (no markup of its own) is escaped instead."""
        cache = self._row_cache
        entry = cache.get(id(info))
        if entry is None or entry['include_addon'] != include_addon:
            line1 = streaminfo.format_label(info, include_addon=include_addon) or escape_label(info.get('raw')) or '?'
            line1 = line1.replace('\r', ' ').replace('\n', ' ')
            if entry is None:
                line2 = escape_label(streaminfo.format_details(info)).replace('\r', ' ').replace('\n', ' ')
                properties = streaminfo.stream_fields(info)
                properties['release'] = escape_label(properties.get('release'))
                properties['flags'] = escape_label(properties.get('flags'))
                properties['provider'] = escape_label(properties.get('provider'))
                entry = {'line2': line2, 'properties': properties}
                cache[id(info)] = entry
            entry['include_addon'] = include_addon
            entry['line1'] = line1
        return entry['line1'], entry['line2'], entry['properties']

    def onInit(self):
        from lib.ui.compat import L, addon_fanart
        from lib.ui.playbackmeta import resolve_art

        # Open again: ModalStackWindow.doModal() reopens a screen that
        # close_windows_for_playback() force-closed without going through
        # start(), and onClick() refuses picks on a closed window.
        with self._pending_lock:
            self._closed = False

        # A reopen (playback force-closed this same window) is a fresh
        # list. The previous session's cursor move must not keep the
        # next paint on the bottom.
        self._user_moved_cursor = False

        # Pick up anything open_streams() queued via set_loading()/
        # set_load_progress()/add_pairs() before doModal() actually
        # opened this window, so the ONE initial build below already
        # reflects it.
        self._merge_pending()

        # resolve_art() folds the legacy `self.poster` kwarg into `art`'s
        # own poster slot before running the poster/fanart/thumb fallback
        # (down to self.meta's own poster/background/logo) every other
        # Rivulet ListItem builder already uses, replacing this window's
        # own hand-rolled fanart-or-poster-or chain.
        effective_art = dict(self.art or {})
        if not effective_art.get('poster') and self.poster:
            effective_art['poster'] = self.poster
        resolved_art = resolve_art(effective_art, self.meta)
        background = resolved_art.get('fanart') or resolved_art.get('poster') or addon_fanart()
        self.getControl(BACKGROUND).setImage(background)
        self.getControl(POSTER).setImage(resolved_art.get('poster') or '')
        # self.heading carries a caller-supplied title (a Stremio
        # catalog/meta name off an untrusted third-party addon) straight
        # into a rendered label - escape_label() neutralises any [B]/
        # $INFO[...]/... markup it might contain first.
        self.getControl(HEADING).setLabel((escape_label(self.heading) or L(30041)).upper())

        self._rebuild_list()
        self.setFocusId(LIST)
        # After setFocusId: giving the list focus is the second place
        # Kodi selects the last row. Row 0 is the best stream.
        self._focus_first_stream()

    @gated_input
    def onAction(self, action):
        # Drain first, on the GUI thread, exactly like
        # infowindow.ShowcaseWindow.onAction() calls _apply_enriched()
        # before its own per-focus work - see add_pairs()/set_loading().
        self._apply_pending()
        # After the drain, so a Down that arrives together with a batch
        # still starts from row 0 and THEN moves. Recording the move
        # first would treat Kodi's own last-row selection as the user's.
        if action.getId() in _CURSOR_MOVE_ACTIONS:
            self._user_moved_cursor = True
        super().onAction(action)

    @gated_input
    def onClick(self, control_id):
        if control_id != LIST:
            return
        # Kodi queues a window's click callbacks and delivers them on this
        # script thread the next time it calls into Kodi - including from
        # inside a pick that is still preparing (the dialog's update(),
        # Monitor.waitForAbort(), Player.play()) and after this window was
        # closed for the player handoff. Replayed, each queued click started
        # its own "Preparing stream" for another source, nested inside the
        # first and competing with it for the same server (kodi.log: five
        # reopenings in 25s while the first stream failed to open). A pick
        # only counts on an open window with no pick already in progress.
        if self._closed or self._pick_in_progress:
            import xbmc

            from lib.ui.compat import log
            log('streamswindow: ignoring a pick queued while another was in progress', xbmc.LOGINFO)
            return
        self._pick_in_progress = True
        try:
            self._play_focused()
        finally:
            self._pick_in_progress = False

    def _play_focused(self):
        focused = self.getControl(LIST).getSelectedItem()
        if focused is None:
            return
        info, stream = self.pairs[int(focused.getProperty('position'))]

        # item_meta carries the content title/art/meta this window
        # already has in hand (see the module docstring's heading/art/
        # meta kwargs) into the player's OSD - only the keys actually
        # known are included, so a bare "no context" open still behaves
        # exactly like item_meta=None to play_direct(). on_ready fires
        # right before Kodi actually starts playing (play_direct()'s own
        # docstring), and _close_for_player_handoff() below is what
        # tears down every OTHER live screen AND this picker itself at
        # that exact instant, so no Rivulet modal - not even this one -
        # is still live when xbmc.Player().play() runs. This window is
        # closed WITHOUT _closed_for_playback, unlike its ancestors, so
        # ModalStackWindow.doModal() does not immediately reopen it;
        # open_streams()'s own reopen loop is what brings the picker
        # back once playback actually ends.
        item_meta = {}
        # self.heading/meta name are both addon-supplied text flowing
        # into play_direct()'s OSD ListItem label - escape_label()
        # neutralises any embedded markup before that happens.
        label = escape_label(self.heading or (self.meta or {}).get('name') or '')
        if label:
            item_meta['label'] = label
        art = self.art or ({'poster': self.poster} if self.poster else None)
        if art:
            item_meta['art'] = art
        if self.meta:
            item_meta['meta'] = self.meta

        from lib.ui.player import play_direct
        # Only the Continue fallback passes an offset, and only as a
        # keyword, so every existing play_direct stand-in keeps its
        # signature. A successful pick clears it: the reopen after Stop
        # is a new window, and a second pick in this one asks again.
        play_kwargs = {
            'item_meta': item_meta,
            'on_ready': lambda: _close_for_player_handoff(self),
            'video_id': self.video_id,
        }
        if self._forced_resume_ms:
            play_kwargs['resume_offset_ms'] = self._forced_resume_ms
        if play_direct(stream, self.stype, self.sid, **play_kwargs):
            self._forced_resume_ms = None
            self.played = True
            self.played_pair = (info, stream)
            self.close()  # no-op: on_ready above already closed this window


def _close_for_player_handoff(picker):
    """`play_direct()`'s `on_ready` hook for `StreamsWindow.onClick()`:
    fires immediately before `xbmc.Player().play()` (see that
    function's docstring), so this is the ONE moment every live Rivulet
    modal - including `picker` itself - must already be gone, or Kodi
    keeps routing play/pause and the OSD to whichever WindowXMLDialog
    is still topmost rather than to the player (see uicommon's module
    docstring).

    `close_windows_for_playback(exclude=picker)` tears down every OTHER
    live screen, marking each ancestor `_closed_for_playback` so
    `ModalStackWindow.doModal()` restores it once `open_streams()`'s own
    post-playback reopen loop brings a fresh picker back. `picker`
    itself is then closed the same plain way `onAction()`'s Back
    handling does - deliberately WITHOUT `_closed_for_playback`, since
    that flag would also trip `ModalStackWindow.doModal()`'s own reopen
    loop and pop a second, premature picker up immediately behind the
    player; bringing the picker back afterwards is `open_streams()`'s
    reopen loop's job alone.
    """
    close_windows_for_playback(exclude=picker)
    picker.close()


def _wait_for_playback_end(player=None, monitor=None, start_timeout=_PLAYBACK_START_TIMEOUT_SECONDS, tick=0.5, up_next=None):
    """Block until playback `open_streams()` just started has both begun
    and ended, so it can safely reopen the streams picker underneath
    Kodi's player instead of unwinding the whole custom-window stack.

    `play_direct()`/`xbmc.Player().play()` is fire-and-forget - there is
    a short real-world gap before `xbmc.Player().isPlaying()` actually
    reports True - so this first polls up to `start_timeout` seconds (in
    `tick`-second steps) waiting for playback to begin - see
    `_PLAYBACK_START_TIMEOUT_SECONDS`'s own docstring for why the
    default is 45.0, not the original 20.0 (inputstream.adaptive/
    slow-start streams measured close to that ceiling on real
    hardware); a user cancel/Kodi abort during this wait is still seen
    within one `tick` either way - only the GIVE-UP ceiling for a
    stream that never starts at all moved, not how quickly this loop
    reacts to either. If it never does start (resolution failed past
    the point `play_direct()` still returned True, or Kodi itself
    couldn't play the url), there is nothing left to wait out: the user
    already saw `play_direct()`'s own failure notification, so this
    returns `(True, False)` (safe to reopen,
    Once playback DOES begin, it polls again until `isPlaying()` goes
    back to False (stopped/finished), then until Kodi has ANNOUNCED the
    player closed (`_await_player_closed()`: the stop/end/error callback,
    fired only after CVideoPlayer::CloseFile() returned - `isPlaying()`
    already reads False at the start of CloseFile(), up to seconds earlier).
    That also guarantees `ended_naturally` is read AFTER the callback that
    sets it, never before it could have been delivered.

    Returns a `(proceed, ended_naturally)` tuple rather than a bare
    bool, since `isPlaying()` alone cannot tell a natural end apart from
    the user pressing stop. `proceed` keeps the meaning described above
    (and below): False only on a monitor abort or an unexpected
    exception, True otherwise. `ended_naturally` is True only when the
    polled player actually reported Kodi's `onPlayBackEnded()` (played
    through to completion) rather than `onPlayBackStopped()`/
    `onPlayBackError()` (user stop / playback failure); callers use it
    to gate auto-play-next (binge-watching) - it is always False
    whenever `proceed` is False or playback never started.

    Every poll tick is a `monitor.waitForAbort(tick)` call, exactly like
    every other cancellable wait loop in `lib.ui.player` - Kodi shutting
    down mid-wait must be seen within one tick, at either stage, and
    returns `(False, False)` immediately (the caller must NOT reopen
    into a shutting-down Kodi). Any unexpected exception anywhere in
    here (a broken Player/Monitor) degrades to that same `(False,
    False)` - this helper must never raise into
    `StreamsWindow.onClick()`'s caller.

    `player`/`monitor` are injectable (unit tests pass tiny fakes);
    an injected `player` is asked for its own `ended_naturally`
    attribute (`getattr(player, 'ended_naturally', False)`) once it
    stops. Production callers omit `player` and get a
    `_PlaybackEndWatcher` - a tiny `xbmc.Player` subclass, defined here
    rather than at module scope since this module only ever imports
    `xbmc` lazily inside the functions that need it - whose
    `onPlayBackEnded()`/`onPlayBackStopped()`/`onPlayBackError()`
    overrides record which one Kodi actually called.
    """
    import xbmc

    from lib.ui.compat import log

    class _PlaybackEndWatcher(xbmc.Player):
        """Distinguishes a natural end from a user stop/failure, which
        `isPlaying()` alone cannot - it reports False as soon as
        playback stops for ANY reason - and records that Kodi has
        announced the player closed (`playback_finished`), which is the
        only signal that CVideoPlayer::CloseFile() has returned."""

        def __init__(self):
            super().__init__()
            self.ended_naturally = False
            self.playback_finished = False

        def onAVStarted(self):
            # A new item replaced one that was playing (Kodi calls the old
            # item's stop callback first): only a stop AFTER this start counts.
            self.playback_finished = False
            self.ended_naturally = False

        def onPlayBackEnded(self):
            self.ended_naturally = True
            self.playback_finished = True

        def onPlayBackStopped(self):
            self.ended_naturally = False
            self.playback_finished = True

        def onPlayBackError(self):
            self.ended_naturally = False
            self.playback_finished = True

    try:
        if player is None:
            player = _PlaybackEndWatcher()
        if monitor is None:
            monitor = xbmc.Monitor()

        attempts = int(start_timeout / tick)
        for _attempt in range(attempts):
            if player.isPlaying():
                break
            if monitor.waitForAbort(tick):
                return False, False
        else:
            # Never started within the budget - play_direct()'s own
            # failure notification already told the user; just reopen.
            # Nothing played, so nothing to binge into.
            return True, False

        while player.isPlaying():
            # Up next is offered only while the file is actually playing,
            # which is the one place getTime() is safe. `up_next` is None
            # for the direct unit tests of this wait; they keep the old
            # (proceed, ended) pair and never touch the clock.
            if up_next is not None and not up_next.get('cut_request') and not up_next.get('abort'):
                try:
                    _consider_up_next(player, up_next)
                except Exception as exc:  # noqa: BLE001 - a card hiccup must not trap playback
                    log('streamswindow: up-next card failed: %r' % (exc,), xbmc.LOGWARNING)
                    up_next['done'] = True
                if up_next.get('abort'):
                    return False, False
                if up_next.get('cut_request'):
                    # The user accepted, or the timer ran out, while the
                    # file is still playing. Return now so the caller can
                    # resolve the next episode BEFORE stopping this one.
                    # Resolve failure then leaves this episode on screen.
                    return True, False
            if monitor.waitForAbort(tick):
                return False, False
        if not _await_player_closed(player, monitor, tick):
            return False, False
        return True, getattr(player, 'ended_naturally', False)
    except Exception as exc:  # noqa: BLE001 - a wait hiccup must never crash onClick()
        log('streamswindow: wait-for-playback-end failed: %r (treating as stop)' % (exc,), xbmc.LOGWARNING)
        return False, False


def _await_player_closed(player, monitor, tick):
    """Block until `player` has announced it is closed (`playback_finished`,
    set by `_wait_for_playback_end()`'s watcher from Kodi's stop/end/error
    callbacks - delivered only when this thread calls into Kodi, which every
    `monitor.waitForAbort(tick)` here does) - see
    `_PLAYER_CLOSE_TIMEOUT_SECONDS` for why `isPlaying()` going False is not
    enough. Returns False only on a monitor abort. A player without the
    attribute (the injectable test fakes) is treated as already closed, and
    a callback that never arrives within the timeout logs a warning and
    proceeds."""
    import xbmc

    from lib.ui.compat import log

    if getattr(player, 'playback_finished', True):
        return True
    for _attempt in range(max(1, int(_PLAYER_CLOSE_TIMEOUT_SECONDS / tick))):
        if monitor.waitForAbort(tick):
            return False
        if getattr(player, 'playback_finished', True):
            return True
    log('streamswindow: no player-closed callback after %.0fs - reopening anyway' % _PLAYER_CLOSE_TIMEOUT_SECONDS,
        xbmc.LOGWARNING)
    return True


#: Cap on how many failing addons the aggregate WARNING below names by
#: addon+category. This is the fix for issue #34: a stale debrid key
#: surfaced in a user's log as nothing but "3 addon(s) failed", because
#: the per-addon detail that would explain WHICH addon and WHY is
#: logged at LOGDEBUG, and that user's own log showed "Disabled debug
#: logging due to GUI setting" - true of every default-settings bug
#: reporter. Naming every failure is fine for a handful of addons, but
#: a genuinely broken install (40 stale/dead addons) must not turn this
#: into one unbounded line - so this caps how many are spelled out by
#: name; anything past the cap is still counted, just folded into a
#: trailing '+N more'.
_MAX_NAMED_ADDON_FAILURES = 8


def _safe_failure_reason(exc):
    """The short, safe-to-log-at-default-level piece of an `AddonError`
    the aggregate WARNING below can name a failing addon by, without
    repeating `_query_addon_streams()`'s own fuller per-addon DEBUG
    detail: `exc.category` - safe-by-construction ONLY for `AddonError`,
    see that class's own docstring in lib/stremio/addons.py: `category`
    is populated exclusively by `_request_error_category()` or a fixed
    literal at `AddonError` raise sites, so it can never be `str(exc)`
    or a url.

    This function is deliberately typed to `AddonError` alone, and
    callers MUST only reach it from an `except AddonError` branch where
    that guarantee actually holds - never via `hasattr(exc, 'category')`
    duck-typing on an arbitrary exception. A bare attribute check is NOT
    the same contract: any other exception type (a parsing error today,
    anything third-party tomorrow) could carry a `category` attribute
    of its own for unrelated reasons, and nothing stops that value from
    being as sensitive as a credential - exactly the leak this WARNING
    exists to avoid. Every other exception must use its own bare type
    name (e.g. 'ConnectionError') instead, computed directly at the
    call site rather than through this function - see
    `_query_addon_streams()`'s generic `except Exception` branch below."""
    return exc.category or type(exc).__name__


def _summarize_addon_failures(failures):
    """Render `failures` (an ordered `[(addon_name, reason), ...]` list
    built by a `consume_next()` closure in both `_fetch_stream_pairs()`
    and `open_streams()`) into the single WARNING-level line that is
    the ONLY failure detail visible to a user on Kodi's default log
    level (issue #34: their log had nothing but the bare count, because
    the per-addon DEBUG lines that would name the cause are silenced by
    "Disabled debug logging due to GUI setting" for every such user).
    Caps the named addons at `_MAX_NAMED_ADDON_FAILURES`; anything past
    the cap is folded into one trailing '+N more' instead of growing
    this single log line without bound."""
    named = failures[:_MAX_NAMED_ADDON_FAILURES]
    detail = ', '.join('%s (%s)' % (addon_name, reason) for addon_name, reason in named)
    remaining = len(failures) - len(named)
    if remaining:
        detail = '%s, +%d more' % (detail, remaining)
    return '%d addon(s) failed: %s' % (len(failures), detail)


def _query_addon_streams(client, transport_url, addon_name, stype, sid):
    """Fetch+parse one addon's own streams for (stype, sid) - the unit
    of work every fan-out below submits CONCURRENTLY (see
    `_MAX_STREAM_ADDON_WORKERS`) instead of the old serial `for` loop's
    one-at-a-time calls (see the module docstring for the measured
    5.0s/27.6s cost that caused). Returns a `(pairs, failed, reason)`
    tuple; `failed` is True on failure, already logged here (an
    `AddonError` at DEBUG, anything unexpected at ERROR) with the
    addon's NAME plus only `safe_url_for_log()`'s safe scheme+host and
    `addon_error_detail()`'s type-plus-safe-category summary (e.g.
    "AddonError (HTTP 401)") - never the raw url or exception text,
    which may embed credentials/paths/queries - so a caller can
    aggregate a single WARNING across every addon's own outcome
    without re-deriving this per-addon detail itself. The name
    matters: the aggregate is only a count, so without it a user
    reporting "addon X's streams never appear" (issue #32) leaves no
    way to tell WHICH addon dropped out. `reason` is the same safe
    detail in short form: `_safe_failure_reason()`'s `AddonError`
    category for the first branch below, or, for any other exception,
    its own bare type name computed directly at that branch (never
    duck-typed through `_safe_failure_reason()` - see that function's
    own docstring for why) - `None` on success - so
    `_summarize_addon_failures()` can name each failing
    addon in the one aggregate line visible at Kodi's default log
    level, where debug logging (and this function's own per-addon
    line) is off (issue #34).

    Parsing runs inside the same guard as the fetch. A stream resource
    is arbitrary third-party JSON: a body that is a bare list rather
    than an object (`.get` -> AttributeError), or one item hostile
    enough to break `parse_stream`, must not escape to the caller. This
    function IS a worker-thread body (`_start_stream_fetch_workers`),
    and an exception escaping it kills that thread before it can queue
    any result at all - which does not just lose this addon, it leaves
    the consumer blocking forever on a result that will never arrive."""
    import xbmc

    from lib.stremio.addons import AddonError, addon_error_detail, safe_url_for_log
    from lib.ui.compat import log

    try:
        results = client.streams(transport_url, stype, sid)
        pairs = [(streaminfo.parse_stream(stream, addon_name=addon_name), stream) for stream in results or []]
    except AddonError as exc:
        log('streamswindow: %s (%s) failed: %s' % (
            addon_name, safe_url_for_log(transport_url), addon_error_detail(exc)), xbmc.LOGDEBUG)
        return [], True, _safe_failure_reason(exc)
    except Exception as exc:  # noqa: BLE001 - see docstring: a worker thread that dies here wedges its consumer
        log('streamswindow: %s (%s) raised %s' % (
            addon_name, safe_url_for_log(transport_url), type(exc).__name__), xbmc.LOGERROR)
        return [], True, type(exc).__name__
    return pairs, False, None


#: First try plus two silent retries. A dead addon used to become
#: "No streams found" (#30030) the moment its one request timed out,
#: and the same tap a second later succeeded. Only a failed attempt
#: is retried — an addon that answers `[]` has nothing, and asking
#: again would only hold the spinner.
_STREAM_ATTEMPTS = 3

#: Short waits between those retries, long enough for a stalled addon
#: to accept a new connection, short enough that the spinner does not
#: feel stuck. Local to this fan-out, the same way
#: `_MAX_STREAM_ADDON_WORKERS` is: each call site bounds its own pool
#: and its own patience.
_STREAM_RETRY_BACKOFF_SECONDS = (0.4, 0.8)


def _pause_before_stream_retry(seconds):
    """Wait out one silent-retry backoff. Returns True if Kodi is
    aborting, in which case the worker should post the failure it
    already has and stop.

    `Monitor.waitForAbort` is what every other spinner-side wait in
    this addon uses: the test stubs return immediately (they advance a
    fake clock), and a timeout of `<= 0` would wait forever on Kodi,
    so a non-positive `seconds` skips the call entirely."""
    if seconds <= 0:
        return False
    import xbmc

    return xbmc.Monitor().waitForAbort(seconds)


def _query_addon_streams_retrying(client, transport_url, addon_name, stype, sid):
    """`_query_addon_streams()` with silent retries on failure only.

    The consumer still sees one `(pairs, failed, reason)` per addon,
    so the spinner stays up until a real stream arrives or every
    attempt has failed. Backing out does not wait for the backoff:
    the consumer polls cancellation on its own thread while this one
    sleeps."""
    pairs, failed, reason = [], True, None
    for attempt in range(_STREAM_ATTEMPTS):
        pairs, failed, reason = _query_addon_streams(
            client, transport_url, addon_name, stype, sid)
        if not failed or attempt + 1 >= _STREAM_ATTEMPTS:
            return pairs, failed, reason
        if _pause_before_stream_retry(_STREAM_RETRY_BACKOFF_SECONDS[attempt]):
            return pairs, failed, reason
    return pairs, failed, reason


def _supported_stream_addons(stype, sid):
    """Every installed addon whose manifest declares `stream` support
    for (stype, sid) - the exact filter the old serial loop applied
    before its own `for`, factored out so both `_fetch_stream_pairs()`
    and `open_streams()`'s own fan-out share one list."""
    from lib.stremio.addons import addon_supports

    store = get_store()
    addons = []
    for descriptor in store.get_enabled_addons():
        manifest = descriptor.get('manifest') or {}
        if addon_supports(manifest, 'stream', stype, sid):
            addons.append((descriptor, manifest))
    return addons


#: How long each fan-out consumer's `Queue.get()` blocks before giving up
#: and retrying - short enough that `dialog.iscanceled()` keeps getting
#: rechecked while addons are still mid-flight, long enough not to spin
#: the CPU polling an empty queue.
_STREAM_RESULT_POLL_SECONDS = 0.2


def _start_stream_fetch_workers(stype, sid, addons):
    """Fan `_query_addon_streams()` out across a small, genuinely BOUNDED
    pool of raw daemon threads fed by a `queue.Queue` work queue, and
    return the results `Queue` they feed into as `(addon_name, pairs,
    failed, reason)` tuples (`reason` is `None` on success - see
    `_query_addon_streams()`'s own docstring). Exactly
    `min(len(addons), _MAX_STREAM_ADDON_WORKERS)`
    threads are started, each looping `work.get_nowait()` until the work
    queue is empty - bounding BOTH the thread count and the number of
    concurrent addon HTTP calls in flight, unlike spawning one thread per
    addon.

    Deliberately raw `threading.Thread(daemon=True)`, NOT
    `concurrent.futures.ThreadPoolExecutor`: `concurrent.futures.thread`
    registers an atexit hook that JOINS every worker at interpreter
    shutdown regardless of its daemon flag. Measured directly: a single
    addon still inside `AddonClient`'s own 15s timeout blocked process
    exit for a full 6.0s on BOTH Python 3.8 (daemon=True workers) and
    3.13 (daemon=False workers) - `pool.shutdown(wait=False)` does not
    avoid that join, it only stops the POOL itself from waiting, not the
    interpreter's own atexit hook. A raw daemon thread has no such hook:
    the interpreter abandons it outright at exit rather than joining it,
    which is the actual property a fan-out that can return before every
    addon has answered (`open_streams()`) needs."""
    client = get_client()
    work = queue.Queue()
    for descriptor, manifest in addons:
        work.put((descriptor.get('transportUrl'), manifest.get('name', '?')))
    results = queue.Queue()

    def _worker():
        try:
            while True:
                try:
                    transport_url, addon_name = work.get_nowait()
                except queue.Empty:
                    return
                addon_pairs, failed, reason = _query_addon_streams_retrying(
                    client, transport_url, addon_name, stype, sid)
                results.put((addon_name, addon_pairs, failed, reason))
        finally:
            # Drop this thread's private requests session. A fake client
            # has no such method and keeps the object the test substituted.
            release = getattr(client, '_release_worker_session', None)
            if callable(release):
                release()

    for _ in range(min(len(addons), _MAX_STREAM_ADDON_WORKERS)):
        threading.Thread(target=_worker, daemon=True).start()
    return results


def _await_stream_result(results, should_stop=None):
    """Block for the next worker's own `(addon_name, pairs, failed,
    reason)` tuple - in short `_STREAM_RESULT_POLL_SECONDS` slices via a retried
    `Queue.get(timeout=...)` rather than one indefinite `get()`.

    With `should_stop` (a zero-arg callable - the caller's
    `dialog.iscanceled`) each empty slice first lets Kodi deliver the
    window callbacks it has queued (`deliver_queued_input()`; a thread
    parked in `Queue.get()` never reaches Kodi, so a Back press stayed
    undelivered), then returns `None` as soon as `should_stop()` is true
    or Kodi is shutting down. Before this the loop only `continue`d
    inside this function, so the docstring's "keeps re-checking its own
    `dialog.iscanceled()`" never happened: one slow addon held the
    spinner - and Back - hostage for its whole 15 s request timeout.
    Without `should_stop` (the background drain, which has no dialog) it
    blocks until an answer exists, as before."""
    monitor = None
    while True:
        try:
            return results.get(timeout=_STREAM_RESULT_POLL_SECONDS)
        except queue.Empty:
            if should_stop is None:
                continue
            if monitor is None:
                import xbmc

                monitor = xbmc.Monitor()
            if deliver_queued_input(monitor) or should_stop():
                return None


class _StreamAnswerConsumer:
    """The `consume_next()` closure `_fetch_stream_pairs()` and
    `open_streams()` used to each define verbatim - both need the exact
    same "advance by one addon's own answer" step: block on
    `_await_stream_result()`, fold a failing addon into `failures`
    (`(name, reason)`, already safe-to-log per
    `_query_addon_streams()`'s own docstring), or extend a sink list
    with a successful one. `open_streams()`'s own `late_pairs` sink
    needs that extend done under its `pairs_lock` (see that function's
    own docstring on the live->snapshot race) - `_fetch_stream_pairs()`'s
    plain `pairs` list needs no lock at all, nothing else touches it
    concurrently, hence `lock=None` picking the unlocked path.
    `self.consumed` is the running "how many addons have answered"
    count both callers' `busy_dialog.update()` progress bars read;
    calling the instance returns `None` once every addon has answered,
    `(addon_name, addon_pairs)` otherwise - the old closures' own
    contract, unchanged."""

    def __init__(self, results, total, sink_pairs, failures, lock=None):
        self._results = results
        self._total = total
        self._sink_pairs = sink_pairs
        self._failures = failures
        self._lock = lock
        self.consumed = 0

    def __call__(self, should_stop=None):
        if self.consumed >= self._total:
            return None
        answer = _await_stream_result(self._results, should_stop)
        if answer is None:
            return None  # `should_stop` fired: nothing was consumed
        addon_name, addon_pairs, failed, reason = answer
        self.consumed += 1
        if failed:
            self._failures.append((addon_name, reason))
        elif self._lock is not None:
            with self._lock:
                self._sink_pairs.extend(addon_pairs)
        else:
            self._sink_pairs.extend(addon_pairs)
        return addon_name, addon_pairs


def _fetch_stream_pairs(stype, sid):
    """Fetch+parse (not sort) every installed addon's streams for
    (stype, sid) - the exact aggregate pipeline `open_streams()` has
    always run for its own initial fetch, factored out so
    `_try_binge_watch()` can silently re-run it for a next episode's OWN
    id without duplicating the busy_dialog/per-addon-failure bookkeeping.
    Sorting and the "no results" notify()/return-False handling stay the
    CALLER's job - `open_streams()`'s own caller wants a user-visible
    notify(); the binge round trip wants a silent fall-back to reopening
    the picker instead (see `_try_binge_watch()`).

    Every addon is queried CONCURRENTLY (see `_MAX_STREAM_ADDON_WORKERS`)
    rather than one at a time - see the module docstring for why. This
    still BLOCKS until every addon has answered, exactly like the old
    serial loop did - `open_streams()`'s own streaming fan-out is what
    lets THAT caller react before every addon has answered; this
    function's callers (`_try_binge_watch()`, and `open_streams()`
    itself for as long as it used to) want the plain "wait for
    everything, then decide" contract."""
    import xbmc

    from lib.ui.compat import L, log

    addons = _supported_stream_addons(stype, sid)
    pairs = []
    failures = []
    if not addons:
        return pairs

    results = _start_stream_fetch_workers(stype, sid, addons)
    total = len(addons)
    consume_next = _StreamAnswerConsumer(results, total, pairs, failures)

    with busy_dialog(L(30033)) as dialog:
        while True:
            if dialog.iscanceled():
                break
            result = consume_next(dialog.iscanceled)
            if result is None:
                break
            addon_name, _addon_pairs = result
            dialog.update(int(consume_next.consumed * 100 / total), L(30187) % addon_name)

    if failures:
        log('streamswindow: %s' % _summarize_addon_failures(failures), xbmc.LOGWARNING)
    return pairs


def _binge_label(video):
    """'S02E01 \u00b7 Title' - the same shape
    `lib.ui.detailwindow._episode_label()` already renders for the
    episode list, reimplemented here (not imported) so this Kodi-facing
    module never reaches into another window module's private helpers -
    there is no shared, lower-layer module beneath either of them to
    hold one copy instead."""
    title = video.get('title') or video.get('name') or video.get('id') or ''
    return 'S%02dE%02d \u00b7 %s' % (video.get('season') or 0, video.get('episode') or 0, title)


def _binge_heading(show_name, video):
    """'<Show> \u2013 S02E01 \u00b7 Title' - the OSD label for an
    auto-played binge-watching episode, the same shape
    `lib.ui.detailwindow._episode_heading()` builds for a manually
    picked one."""
    code_and_title = _binge_label(video)
    return '%s \u2013 %s' % (show_name, code_and_title) if show_name else code_and_title


def _binge_item_meta(show_name, video, art, poster, meta):
    """`item_meta` for the next episode's auto-played `play_direct()`
    call - the exact same shape `StreamsWindow.onClick()` builds for a
    user-picked stream (see that method's own comment), just keyed off
    `video`'s own heading instead of the picker's static one, since
    every auto-played episode after the first needs its own OSD title."""
    item_meta = {}
    # `_binge_heading()` embeds `show_name` - a series/catalog title off
    # an untrusted third-party addon - straight into the next episode's
    # OSD ListItem label; escape_label() neutralises any embedded markup.
    label = escape_label(_binge_heading(show_name, video))
    if label:
        item_meta['label'] = label
    effective_art = art or ({'poster': poster} if poster else None)
    if effective_art:
        item_meta['art'] = effective_art
    if meta:
        item_meta['meta'] = meta
    return item_meta


def _remaining_seconds(player):
    """Seconds left in the file, or None when the duration is unknown.

    Called only while `isPlaying()` just returned True. A getter that
    raises (the file closed between the two calls) is "unknown", which
    falls back to the post-end card rather than guessing a credits window.
    """
    try:
        total = float(player.getTotalTime() or 0)
        if total <= 0:
            return None
        position = float(player.getTime() or 0)
    except Exception:  # noqa: BLE001 - a clock miss must not kill the wait
        return None
    return max(0.0, total - position)


def _still_playing(player):
    try:
        return bool(player.isPlaying())
    except Exception:  # noqa: BLE001 - treat a broken player as "not playing"
        return False


def _autoplay_limits():
    """`(lead, countdown, still_watching)` from the current settings."""
    from lib.ui.compat import setting_int

    lead = setting_int(
        _BINGE_LEAD_SETTING, _BINGE_LEAD_DEFAULT_SECONDS, minimum=_BINGE_LEAD_MIN_SECONDS,
    )
    countdown = setting_int(
        _BINGE_COUNTDOWN_SETTING, _BINGE_COUNTDOWN_DEFAULT_SECONDS, minimum=_BINGE_COUNTDOWN_MIN_SECONDS,
    )
    still = setting_int(
        _BINGE_STILL_WATCHING_SETTING, _BINGE_STILL_WATCHING_DEFAULT, minimum=0,
    )
    return lead, countdown, still


def _binge_quality_cap():
    from lib.ui.compat import ADDON

    value = ADDON.getSetting(_BINGE_QUALITY_SETTING) or 'highest'
    return _BINGE_QUALITY_CAPS.get(value, 0)


def _up_next_context(stype, meta, poster, art, video_id, played_info, autoplayed=0):
    """The mutable bag `_wait_for_playback_end` and the chain share.

    `cut_request` is set when the card accepted while the file was still
    playing: the caller resolves the next stream before anything stops.
    `preset` is the same pair when the file ended during the card, so
    the caller plays it without a second countdown and without the
    cut marker (the natural end already marks the episode watched).
    `suppress` means Back, a declined still-watching prompt, or a
    resolve failure: do not start another episode.
    """
    show_name = ''
    if isinstance(meta, dict):
        show_name = meta.get('name') or meta.get('id') or ''
    return {
        'stype': stype,
        'meta': meta,
        'poster': poster,
        'art': art,
        'video_id': video_id,
        'played_info': played_info,
        'autoplayed': autoplayed,
        'show_name': show_name,
        'done': False,
    }


def _choose_next_pair(stype, meta, video_id, played_info):
    """The next episode and the stream Up next would play, or None.

    Applies the picker's own playback filters first, then the auto-play
    cap and cached-only switch. See `pick_up_next_stream`.
    """
    if stype != 'series' or video_id is None or not meta:
        return None

    from lib.ui.compat import ADDON, setting_bool

    if not setting_bool(_BINGE_ENABLE_SETTING, True):
        return None
    candidate = next_video(meta, video_id)
    if candidate is None:
        return None
    pairs = _fetch_stream_pairs(stype, candidate.get('id'))
    if not pairs:
        return None
    sort_key = ADDON.getSetting('stream_sort') or 'quality'
    pairs = streaminfo.sort_streams(pairs, key=sort_key)
    pairs = streaminfo.filter_streams(pairs, **_read_stream_filters())
    picked = pick_up_next_stream(
        pairs,
        (played_info or {}).get('binge_group'),
        max_height=_binge_quality_cap(),
        cached_only=setting_bool(_BINGE_CACHED_ONLY_SETTING, False),
    )
    if not picked:
        return None
    info, stream = picked
    return candidate, info, stream


def _arm_autoplay_finish():
    """Mark the episode now playing so its stop flush counts as watched.

    Read before `play()` replaces `now_playing.json`. A missing store
    method or a missing context is logged and ignored: playback of the
    next episode must still start. The word "failed" is avoided on
    purpose; a player test treats that word as a swallowed bug.
    """
    import xbmc

    from lib.ui.compat import log

    try:
        store = get_store()
        context = store.get_now_playing()
        if not isinstance(context, dict) or not context.get('started_at'):
            return
        store.set_autoplay_finish(context.get('started_at'), context.get('video_id'))
    except Exception as exc:  # noqa: BLE001 - the next episode still has to start
        log('streamswindow: autoplay finish marker skipped: %r' % (exc,), xbmc.LOGWARNING)


def _play_up_next(stype, meta, poster, art, show_name, candidate, stream, arm):
    """Start `candidate`. `arm` forces the current episode's stop to
    count as watched, and is True only for a credits cut. A natural end
    already does that, so the post-end path passes False.

    `resume_offset_ms=0` skips the resume confirm and queues no seek.
    The next episode starts at the beginning.
    """
    from lib.ui.player import play_direct

    def on_ready():
        if arm:
            _arm_autoplay_finish()
        close_windows_for_playback()

    item_meta = _binge_item_meta(show_name, candidate, art, poster, meta)
    return play_direct(
        stream, stype, candidate.get('id'), item_meta=item_meta,
        on_ready=on_ready, video_id=candidate.get('id'), resume_offset_ms=0,
    )


def _binge_countdown(label, seconds, accept_on_timeout=True, alive=None, still_watching=False):
    """Thin wrapper around `RivuletCountdown().run()` - the documented
    seam `_try_binge_watch()` calls and the tests pin. True once the
    countdown runs out uninterrupted OR the user presses Select. None
    if the user cancelled via Back. False on a monitor abort. The
    string ``'ended'`` means the file finished while the card was up.

    `still_watching` True does not auto-play when the timer runs out
    (`accept_on_timeout` False) and uses the "Are you still watching?"
    copy. Select is still True.
    """
    import xbmc

    from lib.ui.compat import L
    from lib.ui.dialogs import RivuletCountdown

    if still_watching:
        heading = L(_STILL_WATCHING_HEADING_STRING_ID)
        accept_on_timeout = False
    else:
        heading = L(_UP_NEXT_HEADING_STRING_ID)

    def message(remaining):
        # The Up next line embeds the live countdown ("Playing <title>
        # in 8 s"). The still-watching line does not: the timer running
        # out declines, it does not start the next episode.
        if still_watching:
            return L(_STILL_WATCHING_MESSAGE_STRING_ID) % (label,)
        return L(_BINGE_DIALOG_MESSAGE_STRING_ID) % (label, remaining)

    return RivuletCountdown().run(
        heading, message, seconds, monitor=xbmc.Monitor(),
        accept_on_timeout=accept_on_timeout, alive=alive,
    )


def _consider_up_next(player, ctx):
    """Maybe show the card. Mutates `ctx`. See `_up_next_context`.

    One offer per episode (`done`). Duration 0, or remaining still
    above the lead, waits for a later tick. No next episode, or no
    qualifying stream, leaves the post-end path to notice the same
    thing: this does not set `suppress` for "nothing to play".
    """
    if ctx.get('done') or ctx.get('suppress') or ctx.get('cut_request') or ctx.get('preset'):
        return
    from lib.ui.compat import setting_bool

    if ctx.get('stype') != 'series' or not ctx.get('video_id') or not ctx.get('meta'):
        ctx['done'] = True
        return
    if not setting_bool(_BINGE_ENABLE_SETTING, True):
        ctx['done'] = True
        return
    remaining = _remaining_seconds(player)
    if remaining is None:
        return
    lead, countdown, limit = _autoplay_limits()
    if remaining > lead:
        return
    ctx['done'] = True
    choice = _choose_next_pair(ctx['stype'], ctx['meta'], ctx['video_id'], ctx.get('played_info'))
    if choice is None:
        return
    candidate, info, stream = choice
    label = _binge_label(candidate)
    seconds = min(countdown, max(1, int(remaining)))

    def alive():
        return _still_playing(player)
    if (ctx.get('autoplayed') or 0) >= limit:
        result = _binge_countdown(label, seconds, alive=alive, still_watching=True)
        if result is True:
            ctx['autoplayed'] = 0
        else:
            ctx['suppress'] = True
            if result is False:
                ctx['abort'] = True
            return
    result = _binge_countdown(label, seconds, alive=alive)
    if result is None:
        ctx['suppress'] = True
        return
    if result is False:
        ctx['abort'] = True
        return
    if result == 'ended':
        ctx['preset'] = (candidate, info, stream)
        return
    ctx['cut_request'] = (candidate, info, stream)


def _finish_cut_or_wait(ctx):
    """Play a credits-cut the card already accepted.

    Returns ``'playing'`` when the next episode started, ``'stopped'``
    when resolve failed and the current episode was then waited out
    (stop-return, do not chain), or ``False`` on a Kodi abort.
    """
    import xbmc

    from lib.ui.compat import log

    candidate, info, stream = ctx['cut_request']
    started = _play_up_next(
        ctx['stype'], ctx['meta'], ctx['poster'], ctx['art'], ctx.get('show_name') or '',
        candidate, stream, arm=True,
    )
    if started:
        log('streamswindow: up-next cut to %r' % candidate.get('id'), xbmc.LOGINFO)
        ctx['video_id'] = candidate.get('id')
        ctx['played_info'] = info
        ctx['autoplayed'] = (ctx.get('autoplayed') or 0) + 1
        ctx['cut_request'] = None
        ctx['done'] = False
        return 'playing'
    # Resolve failed. The episode is still on screen: the marker is
    # armed only from on_ready, which did not run. Wait it out and do
    # not offer again.
    ctx['suppress'] = True
    ctx['cut_request'] = None
    ctx['done'] = True
    proceed, _ended = _wait_for_playback_end(up_next=ctx)
    if not proceed or ctx.get('abort'):
        end_player_phase()
        return False
    if xbmc.Monitor().waitForAbort(_REOPEN_SETTLE_SECONDS):
        end_player_phase()
        return False
    return 'stopped'


def _try_binge_watch(
    stype, meta, poster, art, video_id, played_info,
    preset=None, autoplayed=0, already_playing=False,
):
    """After an episode has played through to its natural end, or the
    Up next card already picked a stream (`preset`), keep going.

    The card during the credits is `_consider_up_next`, called from the
    wait below. This loop is the post-end card: it runs when the file
    ended without that offer (unknown duration, or the user seeked past
    the window). `preset` skips the second card for a file that ended
    while the first card was up.

    `already_playing` means `video_id` is on screen right now (a credits
    cut just started it). The first pass waits for THAT episode instead
    of fetching the one after it.

    Returns `None` when the chain stops (not a series, setting off, no
    next episode, nothing eligible, countdown cancelled, the user
    stopped, resolve failed). Returns `False` on a Kodi abort. The phase
    stays `player` on a user stop so the picker's `doModal` is what ends
    it. Continue Resume ends the phase itself, because Home's reopen
    does not.
    """
    if stype != 'series' or video_id is None or not meta:
        return None

    import xbmc

    from lib.ui.compat import log, setting_bool

    if not already_playing and not setting_bool(_BINGE_ENABLE_SETTING, True):
        return None

    show_name = meta.get('name') or meta.get('id') or ''
    current_video_id = video_id
    current_info = played_info
    # A cut already started this episode. Wait for it; do not play the
    # one after it on the first pass.
    skip_play = already_playing

    try:
        while True:
            if not skip_play:
                if preset is None:
                    _lead, countdown, limit = _autoplay_limits()
                    choice = _choose_next_pair(stype, meta, current_video_id, current_info)
                    if choice is None:
                        return None
                    candidate, picked_info, picked_stream = choice
                    if autoplayed >= limit:
                        prompt = _binge_countdown(
                            _binge_label(candidate), countdown, still_watching=True,
                        )
                        if prompt is False:
                            return False
                        if prompt is not True:
                            return None
                        autoplayed = 0
                    countdown_result = _binge_countdown(_binge_label(candidate), countdown)
                    if countdown_result is None:
                        return None
                    if countdown_result is False:
                        return False
                else:
                    candidate, picked_info, picked_stream = preset
                    preset = None

                if not _play_up_next(
                    stype, meta, poster, art, show_name, candidate, picked_stream, arm=False,
                ):
                    return None
                log('streamswindow: binge-watching auto-played %r' % candidate.get('id'), xbmc.LOGINFO)
                autoplayed += 1
                current_video_id = candidate.get('id')
                current_info = picked_info
            skip_play = False

            ctx = _up_next_context(
                stype, meta, poster, art, current_video_id, current_info, autoplayed=autoplayed,
            )
            proceed, ended_naturally = _wait_for_playback_end(up_next=ctx)
            if not proceed or ctx.get('abort'):
                end_player_phase()
                return False
            if ctx.get('cut_request'):
                cut = _finish_cut_or_wait(ctx)
                if cut is False:
                    return False
                if cut == 'stopped':
                    return None
                # The next episode is the one now playing. Loop back to
                # the wait, not to another play().
                autoplayed = ctx['autoplayed']
                current_video_id = ctx['video_id']
                current_info = ctx['played_info']
                skip_play = True
                continue
            if ctx.get('preset'):
                preset = ctx['preset']
            if ctx.get('suppress') or not ended_naturally:
                # Stop, Back on the card, or a declined prompt. Phase
                # stays `player` until the caller's screen comes back.
                return None
            if xbmc.Monitor().waitForAbort(_REOPEN_SETTLE_SECONDS):
                end_player_phase()
                return False
            # Player gone: the next card is a Rivulet screen again.
            end_player_phase()
    except Exception as exc:  # noqa: BLE001 - a binge-chain hiccup must fall back to the picker, never crash open_streams()
        # Leave the phase alone. The caller reopens the picker, and that
        # window's doModal ends `player`. Ending it here is the same gap
        # a Stop refresh uses to Dialog.Close the stack.
        log('streamswindow: binge-watching failed: %r (falling back to the picker)' % (exc,), xbmc.LOGWARNING)
        return None


def _after_playback(stype, meta, poster, art, video_id, played_info):
    """Wait out the player, then run Up next when it should.

    Returns False on a Kodi abort (phase already ended, reopen nothing).
    Returns None when the caller should do its own stop-return. On a
    user Stop the phase is left at `player` so a picker's `doModal` ends
    it. Continue ends it after this returns, because Home does not.

    A credits cut resolves the next episode before this returns to the
    reopen path. Resolve failure waits the current episode out and
    returns None without chaining.
    """
    import xbmc

    ctx = _up_next_context(stype, meta, poster, art, video_id, played_info, autoplayed=0)
    proceed, ended_naturally = _wait_for_playback_end(up_next=ctx)
    if not proceed or ctx.get('abort'):
        end_player_phase()
        return False
    if ctx.get('cut_request'):
        cut = _finish_cut_or_wait(ctx)
        if cut is False:
            return False
        if cut == 'stopped':
            return None
        # The next episode is already playing. Wait for it; do not
        # fetch the one after it. Phase stays `player`.
        if _try_binge_watch(
            stype, meta, poster, art, ctx['video_id'], ctx['played_info'],
            autoplayed=ctx['autoplayed'], already_playing=True,
        ) is False:
            return False
        return None
    if xbmc.Monitor().waitForAbort(_REOPEN_SETTLE_SECONDS):
        end_player_phase()
        return False
    if ctx.get('preset') and ended_naturally and not ctx.get('suppress'):
        end_player_phase()
        if _try_binge_watch(
            stype, meta, poster, art, video_id, played_info, preset=ctx['preset'],
        ) is False:
            return False
        return None
    if ended_naturally and not ctx.get('suppress'):
        end_player_phase()
        if _try_binge_watch(stype, meta, poster, art, video_id, played_info) is False:
            return False
    return None


class _PickerFeed:
    """Bridges `open_streams()`'s background fan-out thread to whichever
    `StreamsWindow` it opens once the first addon answers - buffering
    batches under a lock until `attach()` hands them to a live window's
    `add_pairs()`/`set_loading()`, so nothing a worker delivers in the
    narrow window between "decided to open" and "window fully attached"
    is ever dropped. `stop()` makes every later `add()` a silent no-op,
    the same contract `StreamsWindow.add_pairs()` itself has once
    closed - see `open_streams()` for when each is called."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buffered = []
        self._window = None
        self._done = False
        self._stopped = False
        self._answered = 0
        self._total = 0

    def add(self, pairs):
        with self._lock:
            if self._stopped:
                return
            if self._window is None:
                self._buffered.append(list(pairs))
                return
            window = self._window
        window.add_pairs(pairs)

    def set_counts(self, answered, total):
        """Remember how many addons have answered, and tell the live
        window when one is attached. Empty answers count: the header's
        fraction must move even when an addon found nothing to add."""
        with self._lock:
            self._answered = int(answered)
            self._total = int(total)
            answered = self._answered
            total = self._total
            window = None if self._stopped else self._window
        if window is not None:
            window.set_load_progress(answered, total)

    def counts(self):
        with self._lock:
            return self._answered, self._total

    def mark_done(self):
        """Every addon has now answered - flip the live window's status
        line off, or remember to for whichever window `attach()` next."""
        with self._lock:
            self._done = True
            window = None if self._stopped else self._window
        if window is not None:
            window.set_loading(False)

    def attach(self, window):
        """Flush anything buffered onto `window`, then route every
        subsequent `add()` straight there. Returns True if the fan-out
        was still outstanding at attach time - the caller's initial
        `set_loading()` state."""
        with self._lock:
            if self._stopped:
                return False
            buffered, self._buffered = self._buffered, []
            self._window = window
            still_loading = not self._done
        for batch in buffered:
            window.add_pairs(batch)
        return still_loading

    def stop(self):
        """Nothing may deliver to (or even buffer for) a window again -
        called once the first picker this feeds has closed for good
        (backed out, or handed off to playback); see `open_streams()`'s
        "MUST continue with the accumulated pairs" contract."""
        with self._lock:
            self._stopped = True
            self._window = None
            self._buffered = []


def open_streams(
    stype, sid, poster=None, heading='', art=None, meta=None, video_id=None,
    resume_offset_ms=None,
):
    """Fetch+sort every installed addon's streams for (stype, sid) and
    show them; a pick resolves+plays directly. `heading`/`art`/`meta` are
    forwarded to `StreamsWindow.start()` unchanged, and `video_id` (the
    id of the episode `pairs` is for, `None` for a movie or a
    context-free call) drives the binge-watching round trip below - see
    the module docstring for both.

    `resume_offset_ms`, when set, is the offset Continue already chose.
    It is given to the FIRST picker only. A pick that starts clears it
    inside that window; the picker reopened after Stop does not receive
    it, so a second source asks the usual resume question. Binge calls
    `play_direct` itself and never sees this offset.

    Every installed addon is queried CONCURRENTLY, and the picker opens
    as soon as the FIRST one answers with anything - the rest stream in
    live onto that SAME window (see the module docstring and
    `StreamsWindow.add_pairs()`/`set_loading()`) rather than blocking
    the whole picker open on whichever addon is slowest. Only that
    FIRST window gets live updates; once it closes (a pick, or the user
    backing out), a `threading.Event` tells the fan-out thread to stop
    delivering, and every later reopen below works off the accumulated
    `StreamsWindow.pairs` snapshot instead.

    Once a pick plays, this reopens a fresh `StreamsWindow` over that
    SAME snapshot once playback ends (see `_wait_for_playback_end()`)
    rather than returning - see the module docstring for why this means
    the function now only ever returns False."""
    import xbmc

    from lib.ui.compat import ADDON, L, log, notify

    addons = _supported_stream_addons(stype, sid)
    if not addons:
        notify(L(30030))
        return False

    results = _start_stream_fetch_workers(stype, sid, addons)
    total = len(addons)
    pairs = []
    failures = []
    # Guards `late_pairs` below - `consume_next` runs on `open_streams()`'s
    # own synchronous thread until the background fan-out thread (started
    # below as `drain_remaining`) takes over; both may otherwise call it
    # concurrently with the moment `pairs`/`win.pairs` are read out at the
    # live->snapshot transition further down. See the "accumulated
    # snapshot" contract in that transition's own comment for why every
    # addon answer must be captured under this lock, never appended
    # straight onto a variable the main thread can rebind out from under it.
    pairs_lock = threading.Lock()
    late_pairs = []
    consume_next = _StreamAnswerConsumer(results, total, late_pairs, failures, lock=pairs_lock)

    canceled = False
    with busy_dialog(L(30033)) as dialog:
        while not pairs:
            if dialog.iscanceled():
                break
            result = consume_next(dialog.iscanceled)
            if result is None:
                break
            addon_name, _addon_pairs = result
            with pairs_lock:
                pairs = list(late_pairs)
            dialog.update(int(consume_next.consumed * 100 / total), L(30187) % addon_name)
        canceled = dialog.iscanceled()

    if not pairs:
        if failures:
            log('streamswindow: %s' % _summarize_addon_failures(failures), xbmc.LOGWARNING)
        if canceled:
            # The user pressed Back on the spinner: that is "go back", not
            # "nothing was found" - no notification, just return to the
            # screen they came from.
            log('streamswindow: stream lookup cancelled by the user', xbmc.LOGINFO)
            return False
        # Every addon failed (timeout, HTTP error, exception), after the
        # silent retries above. That is not "this title has no streams":
        # #30030 stays for an addon that actually answered with an empty
        # list. #30431 does not ask the user to try again — the retries
        # already happened.
        if len(failures) == total:
            notify(L(30431))
        else:
            notify(L(30030))
        return False

    sort_key = ADDON.getSetting('stream_sort') or 'quality'
    pairs = streaminfo.sort_streams(pairs, key=sort_key)

    feed = _PickerFeed()
    # The wait loop above already consumed at least one answer (the
    # list is non-empty). The header needs that count before the
    # window exists; later answers, including empty ones, go through
    # set_counts() on the drain thread.
    feed.set_counts(consume_next.consumed, total)
    stop_event = threading.Event()

    def drain_remaining():
        try:
            while True:
                result = consume_next()
                if result is None:
                    break
                _addon_name, addon_pairs = result
                if stop_event.is_set():
                    continue
                feed.set_counts(consume_next.consumed, total)
                if addon_pairs:
                    feed.add(addon_pairs)
        except Exception as exc:  # noqa: BLE001 - nothing else can catch a failure on this background thread; log it as loudly as open_streams()'s own window-construction failures below, rather than let it vanish silently.
            log('streamswindow: fan-out failed: %r' % (exc,), xbmc.LOGERROR)
        finally:
            if not stop_event.is_set():
                feed.mark_done()
            if failures:
                log('streamswindow: %s' % _summarize_addon_failures(failures), xbmc.LOGWARNING)

    still_loading = consume_next.consumed < total
    if still_loading:
        threading.Thread(target=drain_remaining, daemon=True).start()
    else:
        feed.mark_done()
        if failures:
            log('streamswindow: %s' % _summarize_addon_failures(failures), xbmc.LOGWARNING)

    log('streamswindow: opening StreamsWindow (%d streams so far)' % len(pairs), xbmc.LOGINFO)
    live = True
    while True:
        win = None
        try:
            win = open_window(StreamsWindow, 'StreamsWindow.xml')
            if live:
                win.set_loading(feed.attach(win))
                win.set_load_progress(*feed.counts())
            # Pass the offset only while it is set, and only as a
            # keyword. Test doubles of start() predate the argument and
            # do not accept it; the ordinary picker never sets it.
            start_kwargs = {
                'poster': poster, 'heading': heading, 'art': art, 'meta': meta,
                'video_id': video_id,
            }
            if resume_offset_ms:
                start_kwargs['resume_offset_ms'] = resume_offset_ms
            played = win.start(pairs, stype, sid, **start_kwargs)
            resume_offset_ms = None
        except Exception as exc:  # a skin/UI failure must surface, not vanish
            log('streamswindow: window failed to open: %r' % (exc,), xbmc.LOGERROR)
            notify(L(30032))
            if live:
                stop_event.set()
                feed.stop()
            # No window opened, so nothing else will end the phase. A
            # reopen that fails after Stop would otherwise leave every
            # ancestor deaf (`super().doModal()` on the way back does not
            # call `end_player_phase()`).
            end_player_phase()
            return False
        finally:
            # A normal return means StreamsWindow already closed itself (its
            # own onAction/onClick calls self.close()) before .start() returned
            # - but an exception raised from WITHIN .start() (onInit(), or a
            # callback mid-doModal()) skips that self-close entirely. Close
            # unconditionally here so no exit path leaves a zombie modal
            # window behind; closing an already-closed window is a safe no-op.
            if win is not None:
                try:
                    win.close()
                except Exception:
                    pass

        if live:
            # The live streaming phase only ever feeds the FIRST window
            # this picker opens (see the module docstring): once it has
            # closed - a pick, or the user backing out - capture
            # whatever else streamed in before that close as the new
            # `pairs` snapshot, and stop listening for more addons. Every
            # later reopen below reuses THIS SAME list unchanged - there
            # is nothing left updating it once live is False.
            #
            # Read straight off `late_pairs` (under `pairs_lock`) rather
            # than `win.pairs`: `consume_next()` may still be running on
            # `drain_remaining()`'s background thread right up to this
            # instant, and it is the only thing `late_pairs` is ever
            # mutated by - so this is the one point-in-time read that
            # can't race with it, unlike rebinding `pairs` to `win.pairs`
            # (a name/attribute a concurrent `consume_next()` call has no
            # reason to know just got swapped out from under it).
            stop_event.set()
            feed.stop()
            live = False
            with pairs_lock:
                pairs = streaminfo.sort_streams(list(late_pairs), key=sort_key)

        if not played:
            # A pick whose play() raised after the handoff began never
            # reaches the wait below; never leave the phase on `player`.
            end_player_phase()
            return False

        # Playback started: wait it out, then reopen the SAME picker
        # underneath the player that just closed instead of unwinding the
        # whole custom-window stack (see the module docstring). A monitor
        # abort (Kodi shutting down) at any point below returns False
        # immediately, reopening nothing.
        #
        # The wait returns only once Kodi announced the player closed
        # (after CloseFile() returned), and the settle pause that follows
        # is spent calling into Kodi, which is what delivers - to screens
        # that still ignore input, phase `player` - anything queued while
        # the player owned the screen. The phase stays `player` until the
        # restored picker's own `doModal()` (its first line ends the
        # phase). Ending it in this gap is what let a Stop refresh see
        # phase `addon` and `Dialog.Close(all)` the stack that was about
        # to come back. A natural end is the exception: binge's countdown
        # is a Rivulet screen and needs input, so the phase ends before
        # that and `_try_binge_watch()` owns it from there.
        # Up next (during the credits, or the post-end card when the
        # duration was unknown) and the settle live in `_after_playback`.
        # False is a Kodi abort: reopen nothing. None falls through to
        # reopening THIS picker, which is also what a user Stop, a Back
        # on the card, a series end, and a failed resolve do. The phase
        # stays `player` on that path until the restored picker's doModal.
        played_info = win.played_pair[0] if win.played_pair else None
        if _after_playback(stype, meta, poster, art, video_id, played_info) is False:
            return False

        log('streamswindow: reopening StreamsWindow after playback (%d streams)' % len(pairs), xbmc.LOGINFO)
