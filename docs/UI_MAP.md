# UI map

Confirmed in `addon.xml`: upstream **0.30.1**. This fork's Home pass is **0.30.1-ui.1**.

The addon draws its own 1920×1080 skin (`resources/skins/Default/1080i/`). Kodi calls `default.py`. A bare launch (`action` missing or `home`) ends the directory handle and opens `HomeWindow`. Any other action goes to `lib/ui/router.py`. If `HomeWindow` itself raises, `default.py` falls back to `lib/ui/views.py:home()`, a recovery directory with a notice and Settings only.

Later UI work should stay in the files named for that screen. Shared helpers are listed at the bottom; changing one changes every screen that imports it.

## Home

| Piece | Path |
|---|---|
| Skin | `resources/skins/Default/1080i/HomeWindow.xml` |
| Window | `lib/ui/homewindow.py` (`HomeWindow`, `open_home`) |
| Row icons | `resources/media/<action>.png` |
| Entry | `default.py` when `action` is `home` |

Three lists, because a Kodi list has one row height:

| List | Control | Rows |
|---|---|---|
| Watch | `30002` | Continue (`mystuff`), Watch Later (`watchlater`) |
| Browse | `30010` | Movies, Series, Anime, Other. A row is hidden when its setting is off or no enabled addon publishes that type. |
| More | `30011` | Search, Add-ons, Settings |

If no type row is visible, Search / Add-ons / Settings move onto the Browse list so Down from Watch still reaches them. `Window.Property(HomeTools)` is set only when the More strip is separate.

| Row | Opens | Closes Home when playback starts |
|---|---|---|
| Continue | `lib/ui/mystuff.py:open_my_stuff()` | yes |
| Watch Later | `open_my_stuff(bands=(BAND_LIBRARY,))` | yes |
| Movies, Series, Anime, Other | `lib/ui/catalogpicker.py:open_catalog_picker()` | yes |
| Search | `lib/ui/searchwindow.py:open_search()` | yes |
| Add-ons | `lib/ui/addonswindow.py:open_addons()` | no |
| Settings | `lib/ui/compat.py` `ADDON.openSettings()` (Kodi's dialog) | no |

Back on Home still closes the window (`BaseWindow` / `BACK_ACTIONS`). That path is unchanged.

## Continue and the library

Continue is not its own window. `lib/ui/mystuff.py` merges local playback progress with the Stremio `libraryItem` datastore and hands the bands to the grid.

| Piece | Path |
|---|---|
| Merge and open | `lib/ui/mystuff.py` |
| Grid | `lib/ui/gridwindow.py`, `resources/skins/Default/1080i/GridWindow.xml` |
| Bands, in order | resume, next up, watched recently, library (saved, never started here) |

A picked title goes to `open_detail`. The grid does not resolve streams.

## Detail

| Piece | Path |
|---|---|
| Window | `lib/ui/detailwindow.py`, `resources/skins/Default/1080i/DetailWindow.xml` |
| Open | `open_detail(type, id)` |

A series shows seasons and episodes, then `lib/ui/streamswindow.py`. A movie has no episode to pick, so `open_detail` skips this window and opens the source list directly. The context menu can add or remove a library title and mark watched. Those writes go through `lib/stremio/api.py` and `lib/library.py`. Leave both alone on a UI pass.

## Settings

There is no settings window in the skin. Both Home and the recovery directory call Kodi's native dialog.

| Piece | Path |
|---|---|
| Definitions | `resources/settings.xml` |
| Home | `lib/ui/homewindow.py:_open_settings` |
| Router action `settings` | `lib/ui/views.py:open_settings` |

`server_enable` stays first in the server category. Kodi otherwise opens the dialog inside the server URL field and traps the arrow keys.

## Other screens

| Screen | Python | Skin |
|---|---|---|
| Catalog picker (Movies / Series / Anime / Other) | `lib/ui/catalogpicker.py` | `CatalogPickerWindow.xml` |
| Coverflow | `lib/ui/infowindow.py` (`ShowcaseWindow`) | `ShowcaseWindow.xml` |
| Search | `lib/ui/searchwindow.py` | `SearchWindow.xml` |
| Add-ons | `lib/ui/addonswindow.py` | `AddonsWindow.xml` |
| Addon catalogs | `lib/ui/addoncatalogwindow.py` | `AddonCatalogWindow.xml` |
| Source list | `lib/ui/streamswindow.py` | `StreamsWindow.xml` |
| Busy / progress / confirm / options | `lib/ui/dialogs.py` | `BusyDialog.xml`, `ProgressDialog.xml`, `ConfirmDialog.xml`, `OptionListDialog.xml`, `CountdownDialog.xml` |

The source list (`streamswindow`) is the last screen before playback. A Home-only pass does not restyle it.

## Shared helpers

Used by more than one screen. A change here is not local to Home.

| Module | Role | Home uses it |
|---|---|---|
| `lib/ui/uicommon.py` | Modal stack, `BaseWindow`, `gated_input`, `open_window`, Back ids, the playback-phase heartbeat, cancellable spinners | yes |
| `lib/ui/compat.py` | `L()`, `log()`, settings reads, addon paths. The only place that papers over Kodi 19 vs 20+. | yes |
| `lib/ui/dependencies.py` | `get_store()`, `get_client()`, `get_api()` | yes |
| `lib/ui/dialogs.py` | Busy, progress, confirm, option list | indirectly, via the screens Home opens |
| `lib/ui/mystuff.py` | Continue, and Watch Later via the optional `bands` argument | yes |
| `lib/ui/playbackmeta.py` | Episode codes and art. No `xbmc` import. | no |
| `lib/ui/urlutil.py` | Plugin URLs. No `xbmc` import. | no |
| `lib/ui/views.py` | Catalog and meta fan-out, login, the recovery directory. Home does not fetch catalogs itself. | no |
| `lib/ui/metacache.py` | Meta cache used by the grid and the coverflow | no |

`open_my_stuff(bands=None)` is the one shared helper this Home pass changes. `bands=None` is still Continue. Watch Later passes `(BAND_LIBRARY,)`, which filters the list already merged from local progress and `libraryItem`. It does not add a fetch.

## Leave these alone on a UI pass

Playback, resume, next episode, the streaming server, subtitles, and the Stremio client:

- `lib/ui/player.py`, `lib/ui/binge.py`
- `lib/ui/streamswindow.py` (source list and stream resolution)
- `lib/service_runner.py`, `service.py`, `lib/serverbin.py`, `lib/libserver.py`
- `lib/stremio/` (protocol and HTTP)
- `lib/library.py`, `lib/store.py` (wire format and persistence; read them, do not change them for a skin pass)

## Watch Later

Stremio's library record (`lib/library.py`) is a `libraryItem`. A real saved title has `removed` false and `temp` false. A title that was only played, never added, is stored with both flags true and is dropped by `library_metas()`. There is no watch-later field and no second datastore collection. Local progress (`store.get_progress_entries()`) is resume data, not a list the user curates.

So Watch Later on Home is the library band Continue already shows at the bottom: saved titles with no started playback on this device. Started titles stay on Continue. The empty states are string `#30424` (signed out) and `#30426` (signed in, nothing unstarted).

A separate Watch Later list would need a new addon-data file in `lib/store.py`, or a new Stremio collection plus read/write support in `lib/stremio/api.py` and `lib/library.py`. Neither exists today, and both are outside a UI-only pass.
