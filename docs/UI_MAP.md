# UI map

This fork is **RevRivulet** (`plugin.video.revrivulet`), version **0.30.1.rev23**. It installs beside official Rivulet. Upstream of the Home redesign was **0.30.1**.

The addon draws its own 1920×1080 skin (`resources/skins/Default/1080i/`). Kodi calls `default.py`. A bare launch (`action` missing or `home`) ends the directory handle and opens `HomeWindow`. Any other action goes to `lib/ui/router.py`. If `HomeWindow` itself raises, `default.py` falls back to `lib/ui/views.py:home()`, a recovery directory with a notice and Settings only.

Later UI work should stay in the files named for that screen. Shared helpers are listed at the bottom; changing one changes every screen that imports it.

## Home

| Piece | Path |
|---|---|
| Skin | `resources/skins/Default/1080i/HomeWindow.xml` |
| Window | `lib/ui/homewindow.py` (`HomeWindow`, `open_home`) |
| Row icons | `resources/media/<action>.png` |
| Entry | `default.py` when `action` is `home` |

The backdrop (`30000`), the optional clearlogo (`30023`), and the hero labels (`30020` title, `30021` meta, `30022` plot) follow the focused poster. Moving onto the top bar keeps the last title on screen.

There is no large card row. Continue and Library are poster rows. The type chips (`30010`) and the tools share one header row: chips on the left, Search, Add-ons and Settings in a right-aligned grouplist (`30011`) on the right, so Settings stays last. Right off the last chip crosses to the tools and Left off the first tool crosses back. Sign in (`30073`) is the leftmost tool and only while this profile has no login (`Window.Property(HomeSignedOut)`). The status line under the wordmark says "Signed in" and never shows the address; Settings > Account shows it read-only (`account_user`).

| Control | What it is |
|---|---|
| `30011` | Top bar grouplist, `align=right`. Buttons `30073` Sign in, `30070` Search, `30071` Add-ons, `30072` Settings. |
| `30010` | Movies, Series, Anime, Other chips. Hidden when none apply (`HomeBrowse`). |
| `30040` | Continue. In-progress titles only. Hidden when the setting is off or the row is empty. |
| `30041` | Library. Stremio library posters. Signed out, one Sign in cell. |
| `30042`–`30045` | First page of the first installed catalog of that type, then More. |
| `30150`–`30155` | "row / rows" on each row heading, counting only the rows showing. Empty with one row. |

A poster click calls `open_detail`. It does not open the merged grid. More and the type chips open the catalog hub.

| Control | Opens | Closes Home when playback starts |
|---|---|---|
| Continue / Library poster | `lib/ui/detailwindow.py:open_detail()` | yes |
| Movies, Series, Anime, Other | `lib/ui/hubwindow.py:open_hub()` | yes |
| Search | `lib/ui/searchwindow.py:open_search()` | yes |
| Add-ons | `lib/ui/addonswindow.py:open_addons()` | no |
| Settings | `lib/ui/compat.py` `ADDON.openSettings()` (Kodi's dialog) | no |

Down from the top bar enters the first visible row. Up from that group returns to the bar (to the tools when no chips show). Down on the last row stays there. Left and right stay inside the focused row. Back on Home still closes the window (`BaseWindow` / `BACK_ACTIONS`). That path is unchanged.

## Fuse look (beta)

Settings > Home > New look switches to a second skin set: `Fuse` plus the classic file name (`FuseHomeWindow.xml`). `lib/ui/fuse.py` picks the file in `open_window` and paints the controls only Fuse files have: `30024` facts (year • runtime • genres), `30025` scores and "Ends at", `30027` the star strip. A Fuse file declares every id its classic file does (`tests/test_fuse.py`), so the window class is unchanged. Screens without a Fuse file keep the classic one (`FUSE_SKINS`). Changing the setting closes Home and `open_home` reopens it in the other look. Drawn so far: Home, the hubs, the coverflow and the episode page (`FUSE_SKINS`), plus the search page (`FuseSearchWindow.xml`, driven by `lib/ui/fusesearch.py`; `FUSE_ONLY_SKINS`). Clearlogos are checked over HTTP (`lib/ui/logocheck.py`). Settings > Refresh cached data: `lib/ui/cacherefresh.py`. The XML is written by `tools/build_fuse_skins.py`; textures come from `tools/make_textures.py` (`write_fuse_assets`). Posters and cards carry a mirror image (flipped art under `fuse_reflect_fade.png`). The episode page adds a Trailer pill (`30012`). Trailers: `lib/ui/trailer.py` (streaming server `/yt/<id>`, else Kodi's YouTube add-on), offered from the episode page, the sources screen's Options and the poster menu (`libraryaction.poster_menu`).

## Catalog hub

| Piece | Path |
|---|---|
| Skin | `resources/skins/Default/1080i/HubWindow.xml` |
| Window | `lib/ui/hubwindow.py` (`HubWindow`, `open_hub`) |

Same hero, the same row band (hero bar ending at y=652, the hairline at y=692) and the same header row as Home. `30005` is the hub's name on that row; the row heading line shows "row / rows" for the focused row. A catalog that does not answer shows one Try again card (OK asks again). Up to eight poster rows (`31010`–`31017`), one per reachable catalog of the type that was opened. Search-only catalogs are skipped. A genre-required catalog uses its first declared genre. Series may pin New Episodes first, by calling `catalogpicker._new_episode_items` and `_mark_episode_seen` without changing them. Catalogs past the eight slots are logged and left off.

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

A series shows seasons and episodes, then `lib/ui/streamswindow.py`. A movie has no episode to pick, so `open_detail` skips this window and opens the source list directly. The context menu can add or remove a library title and mark watched. The Options pill (`30009`, top right) opens the same menu for remotes without a menu key; on the source list it offers the library action. Those writes go through `lib/stremio/api.py` and `lib/library.py`. Leave both alone on a UI pass.

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
| Catalog hub (Movies / Series / Anime / Other) | `lib/ui/hubwindow.py` | `HubWindow.xml` |
| Catalog picker (still in the tree; Home no longer opens it) | `lib/ui/catalogpicker.py` | `CatalogPickerWindow.xml` |
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
| `lib/ui/mystuff.py` | Continue/library merge. Home calls `merge_entries`, `library_metas`, `_fetch_library_entries` and `_enrich`. It does not change them. | yes |
| `lib/ui/playbackmeta.py` | Episode codes and art. No `xbmc` import. | no |
| `lib/ui/urlutil.py` | Plugin URLs. No `xbmc` import. | no |
| `lib/ui/views.py` | Catalog and meta fan-out, login, the recovery directory. Home pages its rows with `iter_catalog_pages_after()`. Home and the hubs call `sign_in()`, which touches no plugin handle; the Settings action `login()` wraps it and ends its RunPlugin handle. | yes |
| `lib/ui/metacache.py` | Meta cache used by the grid and the coverflow | no |

Home calls those helpers and does not edit them. `open_my_stuff(bands=None)` still means every band, including the library. Home no longer opens that screen from Continue.

## Leave these alone on a UI pass

Playback, resume, next episode, the streaming server, subtitles, and the Stremio client:

- `lib/ui/player.py`, `lib/ui/binge.py`
- `lib/ui/streamswindow.py` (source list and stream resolution)
- `lib/service_runner.py`, `service.py`, `lib/serverbin.py`, `lib/libserver.py`
- `lib/stremio/` (protocol and HTTP)
- `lib/library.py`, `lib/store.py` (wire format and persistence; read them, do not change them for a skin pass)

## Library

The Home row labelled Library (`#30422`) is the Stremio `libraryItem` list: `library_metas()` keeps records whose `removed` flag is false. There is no separate watch-later collection.

Continue is the other row. It is local playback progress in the resume, next-up and recently-finished bands, plus library records whose own `state.timeOffset` is still inside the resume window (including the implicit `temp` and `removed` watch record). It does not include the library band. The old Continue card called `open_my_stuff()` with no band filter, and that screen's last band is the library, which is why the card showed saved titles.

RevRivulet reads login from its own `addon_data/plugin.video.revrivulet/auth.json`. Official Rivulet and the Stremio app do not share the file, so a fresh install says it is not logged in until the viewer signs in once on Home (string `#30427` / `#30428`) or under Settings > Account. That dialog is `views.sign_in()` (from Home and the hubs) or `views.login()` (the Settings action, which also ends its plugin handle).

Adding or removing a library title already exists on the detail screen's context menu. It uses `StremioAPI.get_library_item` / `put_library_item` (`datastoreGet` / `datastorePut` on `libraryItem`) and `lib/library.py`'s `library_add_payload` / `library_remove_payload` (`removed` false to add, `removed` true to tombstone). Home does not offer that menu.
