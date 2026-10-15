# Rev2Rivulet

Rev2Rivulet (`plugin.video.rev2rivulet`) is a test build of this addon. It installs beside RevRivulet (`plugin.video.revrivulet`) and official Rivulet. Kodi treats a different addon id as a different addon, so each one has its own `addon_data` profile and its own settings.

The source tree stays RevRivulet. gh-pages publishes that addon only: `addons.xml` lists `plugin.video.revrivulet` and `repository.revrivulet`, and the root index is those two zips as plain links. Rev2Rivulet is not built or published. `rev2.version` is unused by the publish workflow.

## Which UI loads

`lib.addonid.ADDON_ID` is `plugin.video.revrivulet` in this tree and `plugin.video.rev2rivulet` inside the variant zip. `lib.ui.rev2.is_rev2()` is that comparison. When it is true:

- `open_window` loads `Rev2` plus the existing XML name. The window class is the same one, so stream fetch retry, stop-return, and library sync are untouched.
- Search opens an on-screen keyboard. The query still goes through `searchwindow.run_query`.
- Settings opens a two-pane list of the boolean options. All settings opens Kodi's addon settings dialog for the rest, including the server URL.

## Poster mask

RevRivulet's `round_mask.png` is a 48px square used with `border="16"` and a grey `round_fill.png` plate behind the art. On a CoreELEC box that square stretches into a jagged grey oval.

Rev2 masks are a different file:

- drawn at the control's pixel size (`rv_mask_200x300.png` for a 2:3 poster, `rv_mask_392x220.png` for the Continue card, and one file per other art size)
- a rounded rectangle with a 12px corner, so the sides stay straight
- full opacity inside (white RGB, alpha 255). Nothing grey sits behind the art
- no `border` on the diffuse. A 9-slice border is what collapsed the old mask's straight edges

`python3 tools/build_rev2_skin.py` regenerates the Rev2 XML, the masks, and strings `#30432`–`#30437`. `python3 tools/make_textures.py` redraws the masks on their own.

## What the spec asked for that this build does not do

- Real-time blur, shimmer skeletons, trailer autoplay, parallax, and shadows on unfocused cards. The spec already cuts these for a low-power box.
- A one-row grouplist that keeps the focused row pinned while the next row peeks out. The existing shelves stay. `lib/ui/rev2/rows.py` has the peek helper for a later switch, behind the same concern: it is the first thing the spec says to drop if row changes stutter.
- Searching on a 400ms timer while letters are typed. The Search key runs the query. A fan-out on every letter is the load that debounce was meant to limit.
- Replacing `streaminfo.sort_streams` with `lib/ui/rev2/rank.py`. The streams sheet still sorts the way the live-merge path expects, so a row does not jump while addons are still answering. `rank` is covered by tests and is not on the playback path.
- Hero text crossfades, extra logo fetches, and a long-press keymap. Text still swaps when the focused title changes. The menu button still opens the library action, drawn with the Rev2 option sheet.
