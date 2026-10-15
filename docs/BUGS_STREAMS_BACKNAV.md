# Streams empty-result and Stop back-navigation

Dylan approved both fixes. They are implemented on this branch. The notes below are the investigation that the fix follows. Line numbers are from `origin/main` at `8236870` and have shifted where the fix edited the file.

What landed:

- Stream, meta, and search fan-outs retry a failed addon twice, with a short backoff, while the spinner stays up. The picker opens as soon as a real stream arrives. An empty success is not retried.
- A meta counts only when it is a dict with a non-empty id. `{}` is not cached and does not beat a later addon.
- Meta misses toast `#30430`. A stream fan-out where every addon failed toasts `#30431`. `#30030` stays for a genuine empty answer. Search's total-outage string (`#30382`) no longer tells the user to try again.
- Each fan-out worker using `AddonClient` gets its own `requests.Session`. The constructing thread keeps `.session`, so a substituted test session is still shared.
- A bare plugin-root launch is ignored whenever the UI heartbeat is fresh. `Dialog.Close(all)` does not run from that second launch. After Stop, the phase stays `player` until the restored picker's `doModal`.

Left alone, on purpose: hub and home skin XML, `lib/service_runner.py`, `player.py` now-playing, `mystuff.py`, and detail-window progress pulls. The hub can still toast `#30030` for an empty row set. That path was not part of the approved fix.

## Bug 1 — "No streams found" or an empty list, gone on an immediate retry

### What the toast actually is

`#30030` is the English string "No streams found". It is not specific to the streams picker. The same id is the empty outcome for a meta miss, a catalog, the hub, My Stuff, a discover link, and a resolve that produced no URL:

| Call | File |
|---|---|
| Meta fetch returned nothing | `lib/ui/detailwindow.py:797-798` |
| Stream fan-out produced no pairs | `lib/ui/streamswindow.py:1545`, `:1587` |
| Catalog page empty | `lib/ui/catalogpicker.py:333-335` |
| Hub has no rows left | `lib/ui/hubwindow.py:354-357` |
| My Stuff grid empty | `lib/ui/mystuff.py:431-432` |
| Discover results empty | `lib/ui/infowindow.py:874-875` |
| `resolve_stream` returned no URL | `lib/ui/player.py:1415-1416` |

Search does **not** use this string. A finished search with no titles notifies `#30380` "No results found" (`lib/ui/searchwindow.py:139-149`). A catalog opened with a `search` extra still uses `#30030` (`lib/ui/catalogpicker.py:271-278` then `:333-335`).

So "opening a show / movie / episode shows No streams found" is often the meta or hub fetch failing, before any stream resource is requested. A movie with a good meta then goes on to `open_streams` (`lib/ui/detailwindow.py:801-807`). An episode click goes straight to `open_streams` (`lib/ui/detailwindow.py:774-778`).

### Dylan's guess, against the code

The picker is not painted before the requests return, and the toast is not an early return on the first empty addon.

`open_streams` starts every stream addon at once, then stays on the spinner until **some addon has returned at least one stream**, every addon has answered, or the user cancels:

```python
# lib/ui/streamswindow.py:1566-1588
        while not pairs:
            if dialog.iscanceled():
                break
            result = consume_next(dialog.iscanceled)
            if result is None:
                break
            ...
            with pairs_lock:
                pairs = list(late_pairs)
        canceled = dialog.iscanceled()

    if not pairs:
        ...
        if canceled:
            ...
            return False
        notify(L(30030))
        return False
```

An addon that returns `[]` successfully does not end that loop. The next answer is consumed. The window is built only after `pairs` is non-empty (`lib/ui/streamswindow.py:1621-1630`, and `StreamsWindow.start` returns immediately when `pairs` is empty at `:347-348`).

What the code **does** do on purpose is open the picker on the first **non-empty** addon and paint the rest as they arrive (`lib/ui/streamswindow.py:78-81` and `:1525-1528`). That is a partial list with "Loading more sources..." (`#30185`, appended while `_loading` at `:639-640`). It is not the `#30030` toast. Backing out of that first window sets `stop_event` and `feed.stop()` (`:1669-1670`), so a later reopen uses only what had already been merged. Late addons that had not answered yet are dropped. That can make one visit look short and the next visit, which asks again, look full. It does not by itself toast "No streams found".

Search also waits. `_collect_answers` blocks until every catalog has queued an answer or the user cancels (`lib/ui/searchwindow.py:523-538`). A cancel is silent (`:140-144`), not "No results found".

### Root cause

Three mechanisms produce an empty outcome that a second attempt does not. They stack. None of them is "the local server on port 11470 was not probed before the list was drawn."

**1. A failed fan-out is reported as an empty success.**

Each stream worker turns a timeout, HTTP error, or unexpected exception into `([], True, reason)` and never raises (`lib/ui/streamswindow.py:1086-1097`). `AddonClient.streams` returns whatever `streams` list the body contained, including `[]`, and unlike `catalog()` / `meta()` it does not turn an AIOStreams error placeholder into `AddonError` (`lib/stremio/addons.py:440-484`). A HTTP 200 `{"streams": []}` is a successful empty.

When the loop ends with nothing to show, `open_streams` logs the failures and still notifies `#30030` (`lib/ui/streamswindow.py:1578-1588`). Search does the opposite: every catalog failing is "Search failed… Try again" (`#30382`, `lib/ui/searchwindow.py:428-429`), not "No results found".

The same collapse exists on the hub. `_one_catalog_page` waits for the first page, then:

```python
# lib/ui/homewindow.py:262-272
        page = next(iter_catalog_pages(...))
    except StopIteration:
        return []
    except Exception:
        return []
```

There is no log. `_fill_prefix` deletes any row whose page is empty (`lib/ui/hubwindow.py:173-181`). If that removes every row, the hub notifies `#30030` and closes (`:354-357`). Opening the hub again builds fresh descriptors and fetches again (`posters: None` means "not fetched yet", `:78-79` and `:161-162`). An immediate retry works. Staying on the same window does not: an empty list is stored on the descriptor and is not `None`, so it is not fetched again.

`_fetch_meta` does wait for a non-`None` object, or for every addon, before it returns (`lib/ui/views.py:303-313`). `AddonError` inside a worker becomes `None` (`:278-280`). If every addon times out (the client timeout is 15s, `lib/stremio/addons.py:329`), the function returns `None`, nothing is cached (the write is guarded by `if result`, `:315-317`), and `open_detail` notifies `#30030` (`lib/ui/detailwindow.py:797-798`). The next open tries the network again.

One real "first answer wins" hole sits in that same loop: any non-`None` value breaks the wait, including `{}`. `client.meta` returns `{}` for `{"meta": {}}` (`lib/stremio/addons.py:430-433`). `{}` is not `None`, so slower addons are abandoned (`lib/ui/views.py:306-313`). `if not meta_obj` then treats it as a miss (`lib/ui/detailwindow.py:797`). It is not cached, because `{}` is falsy (`lib/ui/views.py:315`). A later open can take a different winner. A **truthy** partial meta (a name and id, no `videos`) is cached for `TTL_SECONDS` (1800, `lib/ui/metacache.py:60`) and would make the retry show the same bad page. The report says the retry works, so the intermittent case is the uncached one: `None` or `{}`, not a poisoned cache.

**2. One path really does give up while addons are still in flight.**

`_map_addons` stops collecting after `_SOFT_DEADLINE_S` (4.0s) and leaves `None` for anyone still running (`lib/ui/views.py:69-80`, `:141-150`). Callers must treat `None` as "did not answer". My Stuff does (`lib/ui/mystuff.py:335-340`) and then drops items with no name (`:365`). If every fetch misses the deadline, `open_my_stuff` notifies `#30030` (`lib/ui/mystuff.py:467-468`). New Episodes uses the same helper (`lib/ui/catalogpicker.py:437-441`). Those abandoned threads keep running; the next open often hits `metacache` or a warm connection and fills in. This matches "rendered before the responses return" for Continue / New Episodes. It is not the streams picker and it is not search.

**3. One `requests.Session` is shared by every worker.**

`get_client()` is a process-wide singleton (`lib/ui/dependencies.py:73-77`). Stream, search, and meta fan-outs all call it from up to 8 daemon threads (`_MAX_STREAM_ADDON_WORKERS`, `_MAX_SEARCH_WORKERS`, `_MAX_ADDON_WORKERS`). `requests.Session` is not safe for concurrent use. A collided request surfaces as `AddonError` or a bogus body, which path (1) then shows as "nothing found". A retry, with less overlap or a live connection, succeeds.

### What was checked and is not the cause

- **Empty results are not cached** on the title or search path. `store_cached_meta` / `store_cached_metas` require a truthy meta (`lib/ui/metacache.py:189-190`, `lib/ui/views.py:315-317`). There is no stream-result cache. The search ranking feed refuses to persist a bad download (`lib/ui/searchfeed.py:84-87`). An immediate retry refetches. The in-process addon-catalog cache does store an empty list for 300s (`lib/stremio/addoncatalogs.py:241`, `:319-321`), but that cache is the addon browser, not a title's streams or a search.
- **Port 11470 is not on the list or search path.** Addon requests go straight to each addon's transport URL (`AddonClient._get_json`). The streaming server is consulted only when a chosen stream is a magnet, ftp, or carries a server-dependent key (`lib/ui/player.py:1389-1394`). That wait is 5 probes, 1s apart (`_SERVER_WAIT_ATTEMPTS` / `_SERVER_POLL_INTERVAL_SECONDS`, `lib/ui/player.py:117-122`, `:1144-1155`). Failure notifies `#30031` "Streaming server unavailable", a different string. `resolve_stream` for an `infoHash` builds `http://127.0.0.1:11470/...` locally and does not need the process to be warm (`lib/stremio/server.py:841-847`). The service probe (`probe_listening`, 2s, `lib/service_runner.py:60` and `:367`) only decides whether to spawn the binary. Waiting on 11470 before drawing a catalog would not fix this bug. A first-run binary download can still exceed the 5s play wait and show `#30031`; that is a separate, already-specific message.

### Proposed fix

Keep the "open the picker on the first real stream" behaviour. The serial loop it replaced was measured at 5.0s typical and 27.6s worst (`lib/ui/streamswindow.py:70-76`). Do not block the window on the slowest addon once any stream exists.

1. In `open_streams`, if the loop ends with no pairs and `failures` is non-empty, do not notify `#30030`. Notify a failure/retry string (the search wording at `#30382` is the model) and run the failed addons once more. A second all-empty, all-success pass can keep `#30030`.
2. In `_fetch_meta`, treat only a meta that has an id as usable. Keep waiting when the fast answer is `None` or `{}`. Do not cache either.
3. In `_one_catalog_page`, catch `AddonError`, log it with `addon_error_detail`, and return a sentinel the hub can retry once. Do not bare-`except` into `[]`.
4. Give each fan-out worker its own `requests.Session` (or a client built for that call). A lock around the shared session would serialize the fan-out and bring back the 27s stall. Stay on the `requests==2.22.0` floor.
5. Leave `_map_addons`'s 4s deadline in place for Home, but do not use that helper for a screen whose only content is the fan-out (My Stuff, New Episodes) without a second chance for the `None` slots. One retry of the slots that are still `None`, or waiting out the 15s client timeout when every slot missed, is enough.
6. Split `#30030` into distinct ids for "no meta", "no catalog rows", "no streams", and "nothing to play" so a log line and the toast name the step that failed. New ids go above the current maximum, in all 14 locales.

Do not cache empties. That part is already correct. Do not add a 11470 readiness gate to catalog, meta, or search.

### Risks and whether to implement

Safe to implement in `lib/ui/streamswindow.py` (the empty-vs-failure branch only), `lib/ui/views.py` `_fetch_meta`, and `lib/stremio/addons.py` if stream error placeholders should match catalog/meta. Those edits do not touch the stop/reopen loop, `service_runner`, or skin XML.

`_one_catalog_page` and `hubwindow.py` overlap the hub UI that just landed. Propose the sentinel there; do not edit those files while that work is still moving.

Risks: a single retry doubles a genuine outage from ~15s to ~30s; per-worker sessions drop cross-addon connection reuse (acceptable); changing `#30030`'s meaning without new ids would break every caller that shares it. The existing fetch tests in `tests/test_streamswindow_fetch.py` pin the current "all empty → `#30030`" behaviour and would need a new case for "all failed → retry, then a different notice".

## Bug 2 — Stop sometimes lands on the main Home menu

### What is supposed to happen

Playback from the custom UI does not use `setResolvedUrl` and does not push a plugin directory. `StreamsWindow` calls `play_direct`, which calls `xbmc.Player().play()` (`lib/ui/streamswindow.py:7-9`, `lib/ui/player.py:1524-1529`). `xbmcplugin.setResolvedUrl` remains only for the classical `action=play` route (`lib/ui/player.py:1502-1520`, `lib/ui/router.py:57-60`). Nothing in the window stack builds an `action=play` URL.

`Container.Update` is not how these screens navigate. From a modal it has no directory to update and fails (`lib/ui/uicommon.py:57-66`). The only `Container.Update` in the plugin entry is the recovery path when `HomeWindow` itself raises (`default.py:75-76`).

The return target is not stored. It is the live `_MODAL_WINDOW_STACK`. Forward navigation is nested `doModal()` (`lib/ui/uicommon.py:69-81`). Home → hub → detail → streams is four frames on one stack. `HubWindow`, `DetailWindow`, and `HomeWindow` are all `ModalStackWindow`s (`lib/ui/hubwindow.py:312`, `lib/ui/detailwindow.py:354`, `lib/ui/homewindow.py:660`).

On play, `close_windows_for_playback` marks phase `player`, sets `_closed_for_playback` on every ancestor, and closes those windows (`lib/ui/uicommon.py:679-718`). The streams picker is closed **without** that flag so it does not reappear under the video (`lib/ui/streamswindow.py:818-839`). After Stop, `open_streams` waits until Kodi's stop/end/error callback (`_wait_for_playback_end`, `:1693`) and opens a new picker. When that call returns, each ancestor's `doModal` sees the flag and reopens (`lib/ui/uicommon.py:653-660`). `open_streams` always returns `False` (`lib/ui/streamswindow.py:18-20`), so `if open_detail(...): self.close()` / `if open_hub(...): self.close()` never closes the caller on a successful play (`lib/ui/detailwindow.py:774-780`, `lib/ui/hubwindow.py:449-452`). Restore depends entirely on the flag.

Under the dialogs, the original plugin invocation already ended an empty directory (`default.py:42-44`, `cacheToDisc=False`). When every dialog is closed for playback, that empty Videos window is what sits under Kodi's player.

### The previous fix, and the hole

Kodi reactivates that Videos window when playback stops and re-runs the plugin root about 200ms later (`PLUGIN_REFRESH_DELAY`, described at `lib/ui/uicommon.py:323-330`). An earlier build treated that as a new launch: `dismiss_busy_dialog()` runs `Dialog.Close(all, true)` (`lib/ui/uicommon.py:99-102`, called from `default.py:60`), which closed the picker that had just come back, and a second `HomeWindow` opened on top.

`is_duplicate_launch` is the guard (`lib/ui/uicommon.py:479-505`). It suppresses the second launch when a heartbeat is alive and either the published phase is `player` or nothing is playing. The test matrix records the remaining hole on purpose (`tests/test_uicommon.py:579-586`):

- heartbeat alive, phase `addon`, `isPlaying()` True → **not** a duplicate.

That case is documented as "the user opened Rivulet from Kodi's menus while a video is already playing" (`lib/ui/uicommon.py:490-492`). A container refresh cannot be told apart from it.

Phase is cleared in two places that race the refresh:

- `open_streams` calls `end_player_phase()` after a 0.5s settle, before the new picker exists (`lib/ui/streamswindow.py:1697-1700`).
- Every `ModalStackWindow.doModal` calls `end_player_phase()` before the window is shown (`lib/ui/uicommon.py:643-648`).

The phase bit is a `Window(10000)` property read by a **different** process. `isPlaying()` flips to False at the **start** of `CVideoPlayer::CloseFile()`, while the stop callback is delivered only after `CloseFile()` returns (`lib/ui/streamswindow.py:206-218`; a logged torrent stop took 6s inside `CloseFile` because the HTTP cache read could not be cancelled). A refresh queued when the player opens, or a Stop refresh that runs while `isPlaying()` is still True and the property still says `addon` (not yet updated, or already cleared), takes the "deliberate launch" branch.

`default.py` then calls `Dialog.Close(all, true)`. That close does not set `_closed_for_playback`. The reopen loop only continues while the flag is True, and it clears the flag before the restored `doModal` (`lib/ui/uicommon.py:653-660`). A second close is a real exit. The nested calls return, the stack unwinds Hub, Detail, and Home, and the new interpreter opens a fresh `HomeWindow` (`default.py:61`). The user is on the addon home instead of the hub or the episode list. Backing out of the empty plugin directory underneath goes one step further, to Kodi's home. There is no saved URL to reopen the screen they launched from.

Stop is the intermittent case because Stop is the path that blocks inside `CloseFile` on a stalled read. A natural end usually does not. The 0.5s settle and the "wait for the callback" fix cover the refresh that lands while phase is still `player` or after `isPlaying()` is already False. They do not cover the refresh that observes `isPlaying() == True` together with phase `addon`.

`_await_player_closed` also treats a missing `playback_finished` as already finished (`getattr(player, 'playback_finished', True)` at `lib/ui/streamswindow.py:976` and `:981`). The production watcher sets the attribute, so this default is for test fakes. If a stop callback is delivered at the start of `CloseFile` rather than after it returns, the wait ends while the GUI thread is still inside `CloseFile`, the new window is queued behind that thread, and the Videos refresh paints over it. That is the failure the comment at `:206-218` describes, and it is still possible when the callback and `CloseFile` do not line up.

### now_playing is not this bug

The service player clears `now_playing` on stop, end, and error (`lib/service_runner.py` `_terminate`, reached from `onPlayBackStopped` / `onPlayBackEnded` / `onPlayBackError`). That runs in the service process. It does not close windows and it does not decide the next screen. The UI process has its own `xbmc.Player` subclass for the same callbacks (`lib/ui/streamswindow.py:904-931`). Leave `service_runner.py` and the now-playing store to the sync work. A navigation fix that depends on `now_playing` still being set at stop will race that cleanup.

### Proposed fix

The small change is in the duplicate-launch check, not a new return URL and not a switch back to `setResolvedUrl`.

1. `is_duplicate_launch` should return True whenever `ui_owner_alive()` is True. Drop the `isPlaying()` exception. A second click of the addon while a session is up should do nothing, instead of `Dialog.Close(all)` destroying that session. The 10s heartbeat age limit (`lib/ui/uicommon.py:350-351`, `:464-476`) still lets a dead interpreter be replaced.
2. In `default.py`, if a heartbeat is alive, return after `endOfDirectory` and do not call `dismiss_busy_dialog`. Failing open is safe. `Dialog.Close(all, true)` is not, because it closes windows the flag system is about to restore.
3. Keep phase `player` until the reopened streams window has entered `doModal`. Today `end_player_phase()` runs before that open (`lib/ui/streamswindow.py:1700`) and again as the first line of `doModal` (`lib/ui/uicommon.py:648`). The property the other process reads should still say `player` for the whole gap in which a Stop refresh can run.
4. Do not add `Container.Update` or `ReplaceWindow` as the return mechanism. Both target a directory container these dialogs do not have.

### Risks and whether to implement

Safe to implement, and it should be a separate change from bug 1. The files are `lib/ui/uicommon.py` (`is_duplicate_launch`, and only if step 3 is included, the `end_player_phase()` call inside `doModal`) and `default.py`. Update `test_is_duplicate_launch_matrix` in `tests/test_uicommon.py:579-586`: the row `(True, 'addon', True)` becomes a duplicate. No skin XML, no `service_runner.py`, no `hubwindow.py`.

Risks: someone who starts a Rivulet video and then opens the addon again from Kodi's menu will not get a second Home on top. That is the point; the first session is still under the player and is the thing Stop should return to. A heartbeat that keeps getting refreshed by a stuck UI thread still blocks a new launch for up to 10s after the thread dies, which is the existing crash behaviour. Moving `end_player_phase()` out of `doModal` can leave screens ignoring input if some path forgets to clear the phase; `open_streams` already clears it on every exit, and that call has to stay.

Do not implement bug 2 by editing the service stop callback. That overlaps the sync agent and does not close the `Dialog.Close(all)` hole.
