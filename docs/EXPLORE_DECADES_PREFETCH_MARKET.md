# Decades, art prefetch, and the addon marketplace

Exploration only. Nothing in this note is implemented. Playback, `lib/ui/player.py`, `lib/ui/streamswindow.py`, and `lib/service_runner.py` should stay untouched: another change is in flight there, and none of these three features needs them.

Measurements below were taken on 2026-10-15 against live Cinemeta (`https://v3-cinemeta.strem.io`) and `https://stremio-addons.net`, from a cloud VM. They are a lower bound for a CoreELEC box on Wi-Fi. The GUI-thread and texture-cache split is from the code path plus those wire sizes, not from a device profile.

## Summary

| Feature | What to build | Size | Main risk |
|---|---|---|---|
| Decade tiles on the Movies hub | Replace the "New" row's 2026 posters with 2020s–1920s tiles. On select, merge several pages of each year and sort by `popularities.moviedb`. | Medium | One page per year misses the films people mean. Four pages × 10 years is ~40 requests. |
| Art prefetch | Move hub row fetches off the GUI thread, cache slim catalog pages stale-while-revalidate, and warm Kodi's texture cache for poster URLs only. | Medium, in three slices | A second copy of image bytes, or prefetching fanart, will hurt 1 GB boxes. `metacache.py` must not grow to hold catalogs. |
| Marketplace | Browse-and-install already exists (`AddonCatalogWindow`, including stremio-addons.net). The bug is account sync: `addonCollectionGet` runs only inside `login()`. | Small for the pull. The browser is already shipped. | A push that does not pull first still deletes addons added on the web. |

Relative size, for this tree: **small** is a helper plus call sites and tests. **Medium** is that, plus a skin change in both hub XMLs, 14 locales, and a cache file with a byte budget.

## 1. Decade tiles

### What the Movies hub shows today

The row people mean is Cinemeta's movie catalog `id=year`, display name **New**. There is no catalog named Year. The seeded manifest in `lib/store.py` (`DEFAULT_ADDONS`) matches the live manifest fetched for this note.

Live movie catalogs on Cinemeta 3.0.14:

| id | name | Required extra | Options |
|---|---|---|---|
| `top` | Popular | none | optional `genre` (Action … Western), `search`, `skip` |
| `year` | New | `genre` | 107 four-digit years, newest first (`2026` … `1920`), plus `skip` |
| `imdbRating` | Featured | none | optional `genre`, `skip` |

The protocol extra is named `genre` even when every option is a year. `catalog_extra_options()` in `lib/stremio/addons.py` documents that, including the legacy top-level `genres` list Cinemeta also ships. There is no `year` extra and no sort extra. The v3 addon protocol cannot ask Cinemeta "this decade, by popularity".

`_classify_catalog()` in `lib/ui/catalogpicker.py` marks a required-`genre` catalog as `genre`. The catalog picker (still in the tree, not opened from Home) then shows the year list and refuses an unfiltered request. The hub does not. `hubwindow._descriptors()` fills a required genre with **the first option** so the row is not empty:

```114:118:lib/ui/hubwindow.py
        if kind == 'genre':
            options = catalog_extra_options(catalog, 'genre')
            if not options:
                continue
            extra = [('genre', options[0])]
```

For this catalog that option is `2026`. The row heading is `NEW`. The cells are 2026 movie posters from `catalog/movie/year/genre=2026.json`, painted like every other row. Selecting one opens that title, not a year.

Cinemeta's own description of this catalog (the "New" feed) is newest-released and unfiltered. It is not a popularity ranking. Confirmed live: the first titles of `genre=1994` are *The Madness of King George*, *Tammy and the T-Rex*, and *House of Angels: The Second Summer*. *The Shawshank Redemption* is on the third page (`skip=100`), *Pulp Fiction* beside it, *Forrest Gump* and *The Lion King* on the fourth (`skip=150`). That year is 319 metas (`hasMore` false after `skip=300`, 19 left). Sorting the **first page only** by `popularity` surfaces *Legends of the Fall* and *Dumb and Dumber*, not those four.

`popularity` on a meta is a small Stremio blend. The useful key is `popularities.moviedb` (Shawshank 56.3, versus ~1.5 for the page-0 titles). Both fields are already on the catalog preview, so a full `meta` fetch is not required. `top` and `imdbRating` are the wrong source: their first pages are current releases (2025–2026 in this sample), and paging them walks global trending, not a decade.

The series `year` catalog uses the same trick and stops at 1960. This design is Movies only. A series row can follow later with its own floor.

### Design

Detect a year catalog in pure code (no Kodi import): required extra `genre`, and every `catalog_extra_options(catalog, 'genre')` value matches `^\d{4}$`. Do not special-case the transport host. A catalog that merely offers years as one optional genre among words is not this row; only the required-year shape is.

On the Movies hub, that descriptor becomes `kind=decade` instead of a poster fetch:

- Tiles, newest first: **2020s, 2010s, 2000s, 1990s, 1980s, 1970s, 1960s, 1950s, 1940s, 1930s, 1920s**. Eleven tiles. The floor is the oldest year the manifest actually lists (1920 today). Do not invent a 1910s tile.
- The current decade contains only the years present (2020–2026 today). Label it `2020s` anyway.
- No network to draw the row. The options are already in the cached manifest.
- Heading stays the catalog name (`NEW`) unless a new string is worth it. A label such as "Decades" needs a new id above `#30441`, in all 14 locales, count-neutral (`Label: %d` if a count appears). Do not renumber.

The hub skin can show a different shape per row. New Episodes already sets `layout=land` and `HubWindow.xml` / `Rev2HubWindow.xml` gate `mask_land.png` against `mask_poster.png` with `<visible>`. Decade tiles are a third value, `layout=decade`: the grey poster plate, no remote image, and a centered `font13` label bound to the existing `n0`–`n7` properties. Those properties are written by `_apply_posters()` and drawn by neither skin today, so poster rows stay image-only. Eleven tiles use the existing horizontal slide (`VISIBLE_SLOTS` is 8). Click reads a `decade` property in `_activate()` and does not call `open_detail`.

On select, under the existing cancellable spinner (`run_cancellable`, so Back returns in ~0.2 s):

1. For each year in the decade, fetch up to **4 pages** (`skip` steps of whatever the first page returned; Cinemeta's page is ~50, so 4 pages is ~200 metas). Stop a year early when `hasMore` is false or a page is short. 1927 returned 19 metas in one page, so that year is one request.
2. Fan out with a **local** worker cap. Do not reuse another module's pool constant; each fan-out site keeps its own, same reason as `_MAX_ADDON_WORKERS`. Eight is enough. Forty requests at the measured 0.1–1.3 s, eight at a time, is a few seconds when the CDN is warm and closer to ten when it is not. The spinner already exists for this wait.
3. Dedupe on `id`. Sort by `popularities.moviedb`, then `popularity`, then `imdbRating`. Missing numbers sort last. Take a bounded list (the coverflow can page within what was fetched; do not keep walking).
4. Open the existing coverflow (`open_showcase`) with that list. A picked title still goes to `open_detail`. No new player path.
5. Cache the merged list with the catalog cache in section 2, keyed by transport + catalog id + decade. Cinemeta sends `cacheMaxAge=14400`, `staleRevalidate=3600`, `staleError=3600` on the envelope. `AddonClient.catalog()` drops those hints and returns only `metas`, so the cache wrapper has to read the envelope itself. Second open of the same decade should not repeat the 40 requests inside four hours.

The merge function takes a fetch callback and returns metas. It lives next to the other Kodi-free helpers so the 1994 case is a unit test: page 0 is obscure, the high `moviedb` title is on page 3, a 1-page cap must not be treated as success.

### Why not one query per year

Ten first-pages is the wrong aggregate. The year feed is newest-first, so the popular film of a year is often past `skip=100`. A test fixture should lock that in. Four pages caught Shawshank, Pulp Fiction, Forrest Gump, and The Lion King in the 1994 sample and still missed whatever sits in the last ~120 of that year's 319. That miss is acceptable. Fetching every page (about 70 requests for a dense decade, several megabytes of JSON that still includes cast and trailers) is not, on the boxes this addon targets.

Do not sort the raw feed and call it popularity. Do not filter the `top` catalog by `year` and call that a decade.

### Effort

Medium. `lib/ui/hubwindow.py` (descriptor, activate), both hub skins, one pure merge helper, a thin call through `iter_catalog_pages` / `AddonClient`, strings if the heading or the empty-state notify changes, and tests. The catalog picker can keep its year list; it is not on the Home path. No change to `lib/stremio/addons.py` HTTP, and no playback change.

### Risks

- **Quietly wrong list** if the page cap drops. The 1994 sample is the regression test.
- **Slow click** the first time a decade is opened. The spinner must stay cancellable. A hung addon is `AddonError` for that year only; the other nine still merge.
- **Current-popularity bias.** `popularities.moviedb` is "popular now among films released that year", which is what a living-room row wants, and it is not lifetime box office.
- **Skin bulk.** Both hub XMLs are already one control per slot, duplicated for item and focused layouts. A decade label has to repeat that way. `tests/test_skin_xml.py` rejects a `$`-bound `<textcolor>` and requires `aligny=center` when two labels share a box. The decade label is `font13`, not `Mono26`.
- **Rev2.** `skin_for()` loads `Rev2HubWindow.xml` for the same window class. A tile that exists only in one XML fails on that zip.
- **Manifest drift.** If Cinemeta inserts a non-year option into the required list, detection fails closed and the row goes back to "first option as posters". That is the safe failure.

## 2. Art prefetch

### Where the time goes

Opening the Movies hub runs `_build()` → `_fill_prefix(descs, _INITIAL_ROWS)` with `_INITIAL_ROWS = 3`, inside `run_cancellable`. Each of those rows calls `_load_posters()` → `_one_catalog_page()` → one catalog GET. Cinemeta's first page is about **120 KB and 48–50 metas**. Measured from this VM: `movie/top` 0.06–0.11 s, `movie/year/genre=2020` 0.12–1.14 s, `genre=1994` 1.29 s. A community addon is allowed the `AddonClient` timeout of 15 s, and a failure becomes an empty row rather than an error dialog.

`_ROW_INITIAL` is 24. Those 24 become `ListItem`s in memory. The skin does not have 24 image controls. `HubWindow.xml` list `31000` is 680 px tall with 340 px rows, so **two rows** are on screen, and each row has **eight** poster textures (`p0`–`p7`) plus the grey plate. Textures use `background="true"`, so the plate paints immediately and the JPEG arrives later. Kodi creates image controls for realized rows only. This list sets no `<preloaditems>`. Posters 9–24, and every row below the second, do not start a download until `_apply_posters()` writes their URL into a control that exists.

Scrolling down calls `_on_vertical()` → `_ensure_loaded()` **on the GUI thread**, inside `onAction`. That fetches the focused row and the next one before the remote moves again. A 1 s catalog GET is a frozen Down key, and only then does the texture loader start. That is the "lower rows take seconds to show art" report, in two stages:

| Stage | When it runs | Measured / bounded |
|---|---|---|
| Catalog JSON | Before first paint for rows 1–3. On the GUI thread for every row after that, and again when a horizontal slide exhausts `pending` (`_extend_row` → `_pull_more`). | ~120 KB. 0.1–1.3 s for Cinemeta, up to 15 s for a slow addon. |
| Image bytes | Only after a URL is in a realized control. | Poster `small`: 8–42 KB, 0.07–0.20 s from this VM. Background `medium`: 29–319 KB for the hero only. |
| Texture cache | Kodi decodes, resizes, writes `special://database/Textures13.db` and `special://thumbnails/`. A URL already in that DB is a lookup, not a download. | Not timed on CoreELEC here. The addon never warms it. |

`lib/ui/metacache.py` is the wrong bucket. Its docstring refuses catalog bodies (50–500 KB) because the file is rewritten wholesale and a series meta is already 25–30 KB. Budget is 256 KB / 64 entries / 30 minutes, for `(type, id)` detail fetches. Home's `window._catalog_pages` and the hub's `desc['posters']` live for one `HomeWindow` process (hubs are nested `doModal()` calls). They do not survive a new Kodi start, and they do not exist for a hub row until that row is fetched.

`AddonClient.catalog()` returns `metas` only. The live envelope also carries `cacheMaxAge=14400`, `staleRevalidate=3600`, `staleError=3600`, and `Cache-Control: public, max-age=14400`. Those hints are unused.

Home itself only fetches the **first** catalog of each type (`_open_shelf`). The Movies shelf on Home is Popular, not New, and not the rest of the hub.

### Design

Three slices. Ship them in this order. The first one removes the frozen Down key. The third one is what makes art already be there.

**Slice A — row fetch off the GUI thread.** `_ensure_loaded` / `_extend_row` run on a worker, the same way the first paint already uses `run_cancellable` for `_build`. The row stays on the grey plates until `_refresh_row` writes URLs. Back and Up/Down are not blocked on a 15 s timeout. Keep the "focused row plus the next one" cap; do not fan out every installed catalog when the user taps Down once. This slice does not add a disk file.

**Slice B — slim page cache, stale-while-revalidate.** A new file beside the store's other JSON, not a new use of `meta_cache.json`. One rewrite of a bounded file, not a write per scroll.

- Key: normalized transport URL, catalog type, catalog id, extra pairs.
- Value: slim metas only — `id`, `type`, `name`, `poster`, `background`, `logo`, `year` or `releaseInfo`, `description` cut to the hero's 280 characters, `imdbRating`, `popularity`, `popularities`. Drop `cast`, `trailers`, `links`, `awards`. A 120 KB Cinemeta page becomes a small record. Thirty titles is one page (the page holds ~50); do not fetch page 2 just to reach 30.
- Fresh for `cacheMaxAge` seconds when the envelope sent it, otherwise 15 minutes. Serve stale and revalidate in the background for a further `staleRevalidate` (default one hour). On fetch failure, keep serving stale for `staleError` (default one hour). Past that, miss.
- Byte budget on the order of 512 KB, evict oldest. The metacache comment is the constraint: a multi-megabyte rewrite on eMMC/SD is the bug that file was built to avoid. Infrequent writes of a few hundred KB are the point of slimming.
- Read it from Home's background warm and from the hub. The in-memory window cache still wins for the current session.

**Slice C — warm Textures13.db.** Kodi has no Python API to insert a row into `Textures13.db`. Writing `special://thumbnails/` by hand is the wrong fix: the hash and the DB schema are Kodi's, a file without a row is ignored, and a bad row is a corrupt cache. The loader that does write the DB is the one the skin already uses: an image control with `background="true"` whose texture path changes.

Warm with a tiny offscreen window, owned by the addon, not by the hub list:

- Four image controls, 1×1, **visible**. `visible=false` often skips the load. `background="true"` so the GUI thread does not decode inline.
- Feed poster URLs only, about the first **30** of each of the first **3** hub rows (`_INITIAL_ROWS`). At open, Home starts this after the first paint, on a daemon that waits on `xbmc.Monitor.waitForAbort`. The hub starts the same warm if Home's has not finished. "A few extra seconds" is network and disk, with the remote still live.
- Four at a time, not 90 at once. Kodi's own loader no-ops a URL that is already cached, so a later open is lookups.
- Do not warm `background` or `logo`. The hero asks for one fanart when focus moves. Prefetching fanart for 30 titles is the memory problem below.

What not to do: download the JPEGs with `requests` into `addon_data`. That stores a second copy Kodi will not paint, and it spends the SD writes the texture cache was going to spend anyway.

### CoreELEC memory and disk

`resources/advancedsettings.xml` sets the **video** cache `<memorysize>` to 209715200 (200 MB). It does not set `<imageres>` or `<fanartres>`, so Kodi's own defaults apply (720 / 1080). Texture files live under `special://thumbnails` on `/storage`, which on CoreELEC is often the SD card. `Textures13.db` has no cap in this addon and no cap in stock Kodi; it grows until something cleans it. Do not add one by writing the DB from Python.

A small poster is ~25 KB on the wire. Thirty posters × 3 rows is on the order of **2–4 MB** of JPEGs. Decoded into the 200×300 box at 4 bytes a pixel, one poster is ~0.23 MB; four in flight is about 1 MB. That fits next to the 200 MB video cache.

The fanart path does not. A medium background in the sample was up to 319 KB on the wire and decodes toward `fanartres`. Ninety of those, plus the video cache, is how a 1 GB box gets tight. 2 GB and 4 GB boxes have room for the poster warm and still should not prefetch fanart.

Disk risk is repetition, not one warm. A few MB once is fine. Re-saving the same catalogs as fat JSON, or mirroring thumbnails into `addon_data`, is the wear `metacache.py` already refused.

### Effort

| Slice | Size | Pays for |
|---|---|---|
| A. Async row fetch | Small | Down stops freezing. Art still pops in on first sight. |
| B. Slim SWR cache | Medium | Next launch, and the hub open after Home's warm, skips the catalog GET. |
| C. Poster texture warm | Medium | The grey plates already have art when the row appears. |

A alone is worth doing even if B and C slip. C without B still helps the second scroll in one session. B without C still leaves a cold texture cache, which is the pop-in the user sees on rows whose JSON was already fetched (row 3 of a Cinemeta-only hub: fetched in the opening spinner, images start only when the row scrolls into the 680 px list).

### Risks

- Warming from Home competes with Home's own catalog spinner if it is not deferred until after the first paint.
- A texture window that outlives the addon, or that is not tied to `waitForAbort`, leaks a thread across Kodi shutdown.
- Caching fat metas recreates the eMMC problem on purpose.
- Stale-while-revalidate can show a title that has left the feed for up to `cacheMaxAge`. Four hours matches the hint Cinemeta already publishes.
- Slice A must not call into the player or the service. The worker is hub/home only.

## 3. Marketplace and account sync

### What already browses and installs

An in-addon catalog browser is `lib/ui/addoncatalogwindow.py`, opened from Add-ons → the first action ("Browse addon catalogs"). It is not a typed URL. It aggregates:

- Every installed addon's `manifest.addonCatalogs`, collapsed by `iter_unique_addon_catalogs()` so Cinemeta's eleven `(type, id)` pairs become two GETs (`official` and `community`). Live community catalog: **96** addons, each entry already carrying a full manifest.
- `BUILTIN_ADDON_CATALOG_SOURCES` in `lib/stremio/addoncatalogs.py`: `https://stremio-addons.net/api/addon_catalog/all/stremio-addons.net.json`. Live: **693** addons, about 1.2 MB, 0.13 s from this VM. The transport URL in code is a synthetic `manifest.json` path so `build_resource_url()` lands on that real endpoint.

Results are deduped by `transportUrl`, adult manifests dropped when `home_hide_adult` is on, and paged into the list 20 rows at a time so `setArt()` does not queue every logo at once (that stall is the comment at the top of `addoncatalogwindow.py`). Search filters the list in memory. Install goes through `validate_transport_url()` and the manifest shape checks. `behaviorHints.configurationRequired` opens a paste-the-URL flow instead of installing an addon that will 404; Kodi cannot render the addon's `/configure` page. "Install from URL" is still the second Add-ons action, for a manifest that is on neither catalog.

So "browse stremio-addons.net or the community collection and install by manifest" is the current Add-ons screen. A new marketplace window would duplicate it. Worth adding later, and only if the product wants it: Official vs Community sections (the data is already two catalogs), and a shorter first page than 693 rows. Not required to fix the bug below.

There is no separate official "addon collection API" beyond `POST https://api.strem.io/api/addonCollectionGet`. That call returns **this account's** addons, not a public directory. The public directories are the `addon_catalog` resources above. stremio-core treats the account pull as one action, `PullAddonsFromAPI` (`src/unit_tests/ctx/pull_addons_from_api.rs`), not as a timer inside core.

### Why a web install never shows up

`StremioAPI.addon_collection_get()` is called from exactly one place: `views.login()`, after a successful password login. It is not called from Home, from Add-ons, from `sync_addons_now()`, or from `service.py`. There is no interval.

`login()` unions remote descriptors into the local list (a remote URL that fails `validate_transport_url()` is dropped), then `_sync_addons_if_logged_in()` pushes the union with `addonCollectionSet`. After that, every sync is a push:

- install, remove, and reorder call `_sync_addons_if_logged_in()`
- Settings → Sync addons now refreshes manifests, then pushes, with a success notification

`addonCollectionSet` **replaces** the account collection. `addon_collection_get()` keeps only `result["addons"]` and throws away `lastModified`, which stremio-core's `CollectionResponse` carries.

So an addon added on the web after this device logged in is invisible here. The next local sync, including "Sync addons now" and the push that follows any install, writes the local list back and **removes the web addon from the account**. Logging out and in again pulls once, which is why a re-login looks like a fix. Adding the manifest by hand also works, because the local store is the only list the hubs read (`store.get_enabled_addons()`).

`flags.disabled` is stripped on the way up, on purpose, so a local hide does not hide the addon on every other Stremio client. `flags.protected` / `official` / `builtin` / `offline` are local too.

### Design

**Phase 1 — pull on open, without uninstalling.** A pure merge: local list plus any remote descriptor whose transport URL validates and is not already present. Keep local `flags` when the URL matches, including `disabled`. Do not drop a local addon that the remote response omitted. That is the reported bug (web adds missing), and it cannot wipe the device if a GET comes back short.

Call it:

- from Home's first build after launch (that is addon open: `default.py` opens `HomeWindow`)
- from a later Home build only if the last successful pull is older than **15 minutes** of monotonic time, held in the process

`onInit` runs again every time a nested modal closes. A pull there without a TTL fires on every Back from the hub. Run the pull on a daemon **after** the shelf spinner, not inside it. When it adds descriptors, drop `window._catalog_pages` so the next paint sees them. Opening Add-ons uses the same helper and the same TTL, so the list matches the account while the user is looking at it.

Do not put the pull in `service_runner.py`.

`addon_collection_get` should return `(addons, last_modified)` and the store should remember the timestamp. An unchanged timestamp skips the disk write. Keep `update: true` so the account response includes refreshed official manifests.

**Phase 1b — stop the clobber.** Every `addonCollectionSet` goes through one function that has pulled first in this process (or pulls now, cancellable, with the existing "Syncing addons…" string). The payload is the merged list, still with `disabled` stripped. "Sync addons now" then means pull, merge, refresh manifests, push, and the success toast is honest. A pull failure leaves the local list alone, does not push, and does not clear auth unless the HTTP status is 401/403 (the existing `ApiError.is_auth_error` rule).

**Phase 2 — mirror removals, only if we want web deletes to uninstall.** Not part of the bugfix. It needs a local "dirty since last successful push" bit and a remote `lastModified` newer than what we stored. If both changed, union again rather than picking a side. A mirror that treats "missing from this response" as uninstall will delete the user's addons the first time the API returns a partial body. Phase 1 refuses that.

Account sync is not the adult filter. An addon the user added on the web is installed even when `home_hide_adult` would hide it in the marketplace. The marketplace filter stays where it is.

### Effort

Phase 1 and 1b together are **small**: `lib/stremio/api.py` (surface `lastModified`), a pure merge with tests beside the login-merge tests in `tests/test_views.py`, and two call sites (Home, and the push path). No new window, no new skin, no locale strings if the existing sync notification is reused.

Marketplace sections (Official / Community / stremio-addons.net as labelled groups) are a separate small UI pass on `AddonCatalogWindow` and can wait.

### Risks

- Pulling inside Home's existing spinner stacks another 15 s timeout on an already slow catalog open. Background plus TTL avoids that.
- Push-without-pull is the data-loss bug. Shipping the pull on Home but leaving `sync_addons_now` as a blind SET makes "Sync addons now" the button that deletes the web install.
- `update: true` can return large manifests (configured addons embed config in the transport URL and a full manifest). The CAS path is `Store.update_addons`, which is the only safe writer while `default.py` can run as another process.
- A 401 during the background pull must clear auth the same way a failed push does, or a dead session looks logged-in forever. A timeout must not.
- Phase 2, if it is built later, needs an explicit partial-response guard (empty `addons` with a 200 is not "user removed everything" unless `lastModified` moved and the list is well-formed).

## What to leave alone

- Playback, the streaming server, subtitles, `service_runner.py`.
- `metacache.py`'s budget and its refusal to store catalog bodies. The shelf cache is a different file.
- The per-site worker caps. The decade fan-out gets its own constant.
- `flags.disabled` staying off the wire.
- Counted strings. Decade labels are the digit form `2020s`, not a translated plural.
