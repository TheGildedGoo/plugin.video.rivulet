# Contributing RevRivulet's work to Rivulet: the plan

Agreed with M0Rf30 on issue #67: RevRivulet's changes go to
`rivulet-kodi/plugin.video.rivulet` as a series of small PRs. This file
lives on a branch of TheGildedGoo's fork only. It is not meant to be
merged into Rivulet.

## Ground rules (every PR)

- Python 3.8 floor.
- No `xbmc*` imports in `lib/stremio/*` or `lib/store.py`.
- Every user-facing string goes through `L()` and exists in all 14 locales.
- `ruff check lib tests`, `mypy` and `pytest tests/` pass. `ruff format` is
  never run.
- Visual changes sit behind a setting that is OFF by default. With it off,
  Rivulet looks exactly as it does today.
- No RevRivulet branding, add-on id, repository or install changes.
- Each PR is built fresh on Rivulet's current `main`. RevRivulet is a
  reference to read, never a branch to merge.
- Each PR is small enough to review in one sitting.
- Each PR description ends with: "Built with help from AI coding tools;
  I've tested it on CoreELEC and will maintain and answer for these
  changes."

One setting gates the whole new look from PR 2 on: Settings > Home
screen > **New look** (`ui_new_look`, boolean, default `false`). Each
later PR adds its screen behind that same switch, so a user turns it on
once.

## PR 1: standalone fixes and dark dialogs

Branch: `upstream-pr/fixes-and-dark-dialogs` (three commits).

- **Files touched:**
  - Provider-list fixes: `lib/stremio/addons.py`, `lib/ui/streamswindow.py`,
    `lib/ui/detailwindow.py`, `lib/ui/infowindow.py`, new `lib/ui/previews.py`.
  - Search fix: `lib/ui/searchwindow.py`.
  - Dark dialogs: `lib/ui/uicommon.py`, `lib/ui/dialogs.py`,
    `resources/settings.xml`, 14 `strings.po`, five new `Dark*.xml`, four
    `dlg_*.png` textures, `tools/build_dark_dialogs.py`,
    `tools/make_dialog_textures.py`, `pyproject.toml` (E501 for the builder).
  - Tests: `tests/test_provider_ids.py`, `tests/test_dark_dialogs.py`,
    additions to `test_addons.py`, `test_searchwindow.py`, `test_skin_xml.py`,
    `conftest.py` and the kodistubs fake control.
- **Setting:** `ui_dark_dialogs`, off by default. The two fixes change
  behaviour only, never the look, so they are not gated.
- **Depends on:** nothing.
- **Tests:** IMDb alias per addon, episode mapping, the fallback chain in
  `open_detail`, typed previews, the search grace and deadline, classic
  dialogs while off, dark variants while on, every classic control kept in
  its dark variant, and the menu fit happening only in the dark variant.
- **Risk:** low. The dialog swap is one function (`uicommon.skin_name`).
  The id fallback only runs when a title's own id fails today, and it is
  logged.

## PR 1b (parked): country and language filter

Branch: `upstream-pr/region-filter-wip`, not pushed for review yet. It was
taken out of PR 1 because its checklist shows 84 country and language
names as hard-coded English. Before it can go up, those names need `L()`
strings in all 14 locales: about 1,200 translations, which deserve their
own review. Default stays empty (nothing hidden).

## PR 2: Home hero behind "New look"

Their Home is a vertical menu. The new look needs something to focus, so
this PR adds a second Home window and opens it in place of `HomeWindow`
while the setting is on.

- **Files touched:** new `lib/ui/newhome.py` (window, rows, hero
  painting), new `NewHomeWindow.xml`, new `lib/ui/hero.py` (stacking the
  logo, info bar and plot; the logic RevRivulet keeps in `fuse.py`), new
  `lib/ui/logocheck.py` (shows a clearlogo only once it is known to load),
  the textures for the fades and focus ring with their generator in
  `tools/`, `lib/ui/homewindow.py` (`open_home` picks the window from the
  setting), `resources/settings.xml`, 14 `strings.po`.
- **Content:** a menu bar as pills (the same entries as their Home), and
  one catalog row each for Movies and Series, taken from the first
  catalog their pickers would show. The hero shows the focused title's
  backdrop, its logo or name, an info bar (year, runtime, genres, the
  rating the meta already carries) and three lines of plot.
- **Setting:** `ui_new_look` (default off).
- **Depends on:** PR 1 for the dark dialogs only, and only if the new look
  should switch them on with it. Otherwise nothing.
- **Tests:** off opens `HomeWindow` and on opens `NewHomeWindow`, the
  hero's text for full and sparse metas, the logo gate, the row fetch with
  a catalog that fails, and skin control ids against the window class.
- **Risk:** medium. It is a new screen, but a separate one: with the
  setting off no line of their Home runs differently. Rating scores
  (RT/MC) are left out, since they need RevRivulet's ratings fetcher;
  that could be a later PR.

## PR 3: Home rows and carousel reflection

- **Files touched:** `lib/ui/newhome.py` (Continue, Library and New
  Episodes rows; on-focus meta fetch for sparse library records),
  `NewHomeWindow.xml` (the extra rows, the reflection under each poster),
  the reflection and mask textures, small helpers in `lib/ui/mystuff.py`
  and `lib/newepisodes.py` if their current functions do not already
  return what the rows need.
- **Setting:** `ui_new_look`.
- **Depends on:** PR 2.
- **Tests:** each row is built from fake progress, library and series
  data. Empty rows are hidden. Continue resumes. A New Episodes card shows
  the show's backdrop, not the episode still, in the hero. The meta fetch
  retries after a failure.
- **Risk:** medium. Continue in RevRivulet also merges account progress
  (two-way sync); this PR uses only what their `mystuff` already merges,
  so behaviour matches their Library screen. Two-way sync stays out.

## PR 4: one-page search

- **Files touched:** new `lib/ui/searchpage.py`, new `SearchPage.xml`,
  `lib/ui/homewindow.py` and `lib/ui/newhome.py` (open it from Search
  while the setting is on), 14 `strings.po` (Search, Discover, Results,
  the status line).
- **Content:** search bar, A–Z letters with space and delete, a Search
  button, the focused title's hero and one row of results, with Discover
  shown until a search runs. It runs their own `run_query` on the
  screen's thread under the normal spinner, the same path as their search
  screen.
- **Setting:** `ui_new_look`.
- **Depends on:** PR 2 (hero) and PR 1 (search wait fix).
- **Tests:** letters fill the bar without searching, Search runs one query
  and moves to the results, the empty and failed answers show the status
  line, Back on the spinner leaves the row alone, and the skin's ids.
- **Risk:** low to medium. The phone-typing button is left out: it needs
  RevRivulet's pairing feature, which their main does not have.

## PR 5: episode page

- **Files touched:** new `NewDetailWindow.xml`, with the same control ids
  as their `DetailWindow.xml`. Plus `lib/ui/detailwindow.py`: per-episode
  properties (still, air date, runtime, watched tick), and the skin chosen
  from the setting, the same way PR 1 swaps dialogs.
- **Content:** one row per episode with its still, title, air date,
  runtime, a tick once watched and the start of the plot. The selected
  episode sits on a white panel, and its plot scrolls. The show's poster
  is on the right.
- **Setting:** `ui_new_look`.
- **Depends on:** PR 2 for the shared textures and hero helpers.
- **Tests:** episode properties for full and missing data, off loads
  `DetailWindow.xml` and on loads `NewDetailWindow.xml`, every control of
  the classic skin is present in the new one, and season switching is
  unchanged.
- **Risk:** low. Their window class keeps driving it; only the skin and a
  few list-item properties change.

## Later, if wanted

- Trailers, once there is a menu on the movie screens to put them in.
- Rating scores (Rotten Tomatoes, Metacritic) in the hero.
- Hubs (Movies, Series, Other in the new look).
- The greyscale accent, as a theme choice.
