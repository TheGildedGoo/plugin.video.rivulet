# RevRivulet: technical details

This page holds the technical notes that used to live in the main
[README](../README.md): how the add-on works, the streaming server, the
repository setup and how to develop and test it.

[![Test](https://github.com/TheGildedGoo/plugin.video.rivulet/actions/workflows/test.yml/badge.svg)](https://github.com/TheGildedGoo/plugin.video.rivulet/actions/workflows/test.yml)
[![Build addon zip](https://github.com/TheGildedGoo/plugin.video.rivulet/actions/workflows/build.yml/badge.svg)](https://github.com/TheGildedGoo/plugin.video.rivulet/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/TheGildedGoo/plugin.video.rivulet?label=release)](https://github.com/TheGildedGoo/plugin.video.rivulet/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Python 3.8 | 3.11 | 3.13](https://img.shields.io/badge/python-3.8%20%7C%203.11%20%7C%203.13-3776AB.svg)](../.github/workflows/test.yml)
[![Coverage >= 90%](https://img.shields.io/badge/coverage-%E2%89%A590%25-brightgreen.svg)](../pyproject.toml)

## Contents

- [What Rivulet is](#what-rivulet-is)
- [Features](#features)
- [Repository and updates](#repository-and-updates)
- [Streaming server](#streaming-server)
- [Development](#development)
- [More docs](#more-docs)

## What Rivulet is

Rivulet reimplements the [Stremio](https://www.stremio.com/) client
experience inside Kodi: browse and search catalogs from the Stremio addon
protocol, addon management (install from manifest URL), meta/stream
resolution, and playback through a
[rivulet-engine](https://github.com/rivulet-kodi/rivulet-engine) streaming
server. Optional login syncs your addon collection with your Stremio
account.

> **Disclaimer.** This addon does not host, index or provide any media
> content — it is a client for third-party Stremio addons that you install
> yourself.

## Features

- **Custom Home/Browse/Search/Detail/Streams UI** — no dropping to the
  classic Kodi directory for the parts of the flow that matter most.
- **Addon manager** — install Stremio addons straight from a manifest URL,
  and remove them again, without leaving Kodi.
- **Parallel catalog/stream lookups** — a slow or unavailable addon no
  longer stalls the rest of your catalogs or sources.
- **Stremio account sync** — log in to keep your addon collection in sync
  both ways between Kodi and Stremio.
- **Resume and watch progress** — resume locally when logged out, or sync
  progress and watched state to your Stremio account.
- **Automatic next episode** — continue a series after a cancellable
  countdown, preferring the same release group.
- **Subtitles out of the box** — pulled from your installed Stremio
  subtitle addons at playback time, with OpenSubtitles v3 preinstalled and
  sorted by your preferred language.
- **One-click streaming server** — download the right
  `rivulet-engine` build for your platform and run it embedded, or
  point Rivulet at any server you already run.
- **Optional launch on startup** — turn on **Settings → Home screen →
  Open Rivulet automatically on Kodi startup** to have a dedicated media
  box boot straight into Rivulet instead of Kodi's home screen. Off by
  default.

## Repository and updates

Official Rivulet stays installed. Open **RevRivulet** for this fork.

The repository is served from GitHub Pages at
[thegildedgoo.github.io/plugin.video.rivulet](https://thegildedgoo.github.io/plugin.video.rivulet/),
published by `.github/workflows/repo.yml` on every push to `main`. If that
URL 404s, set Settings → Pages → Deploy from a branch → `gh-pages` → `/ (root)`.
Details and the shared streaming-server port are in [`docs/REVRIVULET.md`](REVRIVULET.md).

The one-off zip is `plugin.video.revrivulet-<version>.zip` inside `dist/` on
this branch, and the same zip is published at
[`plugin.video.revrivulet.zip`](https://thegildedgoo.github.io/plugin.video.rivulet/plugin.video.revrivulet.zip).

## Streaming server

All playback is resolved through a streaming server speaking the same
`enginefs` HTTP API as Stremio's own `server.js`
([rivulet-engine](https://github.com/rivulet-kodi/rivulet-engine) is a
pure-Go, drop-in implementation of it). Configure it under
**Settings → Streaming server**:

RevRivulet keeps the default URL `http://127.0.0.1:11470` and reuses a server that is already listening there (official Rivulet's, if it started first). Its own binary is installed under `addon_data/plugin.video.revrivulet/`, not official Rivulet's profile. See [`docs/REVRIVULET.md`](REVRIVULET.md).

| Setting | Purpose |
| --- | --- |
| **Server URL** | Where the streaming server is listening. Defaults to `http://127.0.0.1:11470`, the standard Stremio server port. Point this at any already-running `rivulet-engine` (or official Stremio server) instance, local or remote. |
| **Run embedded server** | When enabled, the addon's background service spawns and supervises a local `rivulet-engine` process for the lifetime of the Kodi session, and stops it on shutdown. |
| **Server binary path** | The `rivulet-engine` executable to run when the embedded server is enabled. Leave empty to auto-detect: the service first looks in `special://profile/addon_data/plugin.video.revrivulet/bin/`, then on `PATH`. |

`rivulet-engine` no longer needs to be installed by hand: use the
**Download rivulet-engine binary** button under
**Settings → Streaming server** to fetch the correct build for your platform
straight from the
[rivulet-engine releases](https://github.com/rivulet-kodi/rivulet-engine/releases)
into the addon's `bin/` folder — the download is integrity-checked before
install. Subtitles are pulled from your installed Stremio subtitle addons at
playback time — OpenSubtitles v3 is preinstalled — and sorted using the
**Preferred subtitle language** setting under **Settings → Subtitles**.

> **Android.** Kodi 19+ targets Android API 29 or newer, where Android 10+
> forbids *executing* a binary from an app's own writable data directory
> (SELinux W^X). Rivulet therefore installs the server in two forms from the
> same integrity-checked `rivulet-engine_Android_{arm64,armv7,x86_64,i386}` archive:
> the executable, and `librivulet-engine.so`, the same server built as a
> shared library. It tries the executable first; when Android denies it, the
> service falls back to **library mode**, loading the `.so` into Kodi's own
> process (the approach Elementum uses) — no root and no second app needed.
> **Settings → Streaming server → Force library mode (Android)** skips the
> executable attempt. In library mode a server upgrade takes effect at the
> next Kodi restart, and a server crash takes Kodi down with it, since both
> share one process. Features needing external tools (`yt-dlp` for YouTube
> streams) are unavailable on Android either way. If neither form can start,
> point **Server URL** at a `rivulet-engine` running elsewhere (PC, NAS,
> [Termux](https://termux.dev/)) and leave **Run embedded server** off.

## Development

### How this was built

RevRivulet was developed with AI coding assistants (such as Claude), with
the maintainer directing every change. Changes are tested on real hardware
(CoreELEC), and the test suite, ruff and mypy run in CI on every push and
pull request. The maintainer (TheGildedGoo) reviews and owns all changes.

`lib/stremio/` and `lib/store.py` are plain Python with no `xbmc*` imports,
so they run and test outside Kodi. Everything Kodi-specific lives in
`lib/ui/`, `lib/service_runner.py`, `default.py` and `service.py`. The
Kodi-facing layer is tested against the shared fake-Kodi modules in
`tests/kodistubs/` (a hermetic, per-test `sys.modules` install/restore of
`xbmc*` stubs), so the whole suite runs with no Kodi runtime and no network.

Set up the dev toolchain and run the tests:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

make test        # run the test suite
make cov         # tests + coverage report (gate: >=90%)
make lint        # ruff check
make typecheck   # mypy across all production Python modules
make check       # lint + typecheck + tests
make random      # tests in randomized order (order-independence)
make parallel    # tests across CPUs (pytest-xdist)
```

Tool config lives in `pyproject.toml`. CI (`.github/workflows/test.yml`)
runs ruff + the test suite with coverage across Python 3.8/3.11/3.13
(Kodi 19 "Matrix" through current), on every push and pull request.

Screenshots in the [Screenshots](../README.md#screenshots) section of the README are generated,
not hand-picked crops - `scripts/capture_screenshots.py` drives a running
`kodi-standalone` instance over its always-on TCP JSON-RPC socket
(`127.0.0.1:9090`, no webserver setup needed), walks every screen listed
there, and writes the curated result to `artwork/screenshots/`. Re-run it
after a UI change to refresh the gallery.

## More docs

- [REVRIVULET.md](REVRIVULET.md): how RevRivulet sits beside official Rivulet (add-on id, profile, shared server port).
- [UI_MAP.md](UI_MAP.md): map of the custom screens.
- [AUTOPLAY_ANALYSIS.md](AUTOPLAY_ANALYSIS.md), [BUGS_STREAMS_BACKNAV.md](BUGS_STREAMS_BACKNAV.md), [REV2RIVULET.md](REV2RIVULET.md): design and bug notes.
