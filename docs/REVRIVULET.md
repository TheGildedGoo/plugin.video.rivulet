# RevRivulet

RevRivulet (`plugin.video.revrivulet`) is this fork, installed **beside** official Rivulet (`plugin.video.rivulet`). Kodi treats a different addon id as a different addon, so installing RevRivulet does not replace, disable, or upgrade official Rivulet. Each addon has its own profile under `addon_data/`.

Version `0.30.1.rev1` is newer than both `0.30.1` and `0.30.1-ui.1` under Kodi's version compare (the part before the first `-` is compared first, and `0.30.1.rev1` has an extra component). Later publishes use `0.30.1.rev2`, `rev3`, … and `.rev10` sorts after `.rev9`. The publisher in `.github/workflows/repo.yml` bumps with that comparator when a push would not otherwise be an update.

## One-time install

1. Settings → File manager → Add source.
   Path: `https://thegildedgoo.github.io/plugin.video.rivulet/`
   Name: `RevRivulet`.
2. Settings → Add-ons → Install from zip file → RevRivulet → `repository.revrivulet.zip`.
   Unknown sources has to be allowed for a zip install.
3. Settings → Add-ons → Install from repository → RevRivulet Repository → Video add-ons → RevRivulet.
4. Settings → Add-ons → turn on auto-update (Settings → System → Add-ons → Updates, or the Add-ons gear, depending on the Kodi version: "Update official add-ons from" Any repositories, and install updates automatically).

Official Rivulet stays in Video add-ons. Open **RevRivulet** for this fork.

GitHub Pages has to serve the `gh-pages` branch from `/` before step 1 works. If the URL 404s: repository Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `gh-pages` → Folder: `/ (root)` → Save. The workflow that fills that branch is `.github/workflows/repo.yml`, and it needs Actions → General → Workflow permissions → Read and write.

## Streaming server (shared port, separate binary)

No server code was changed. Both addons default to `http://127.0.0.1:11470` with **Run embedded server** on.

`lib/service_runner.py` probes that URL before it spawns. If something is already listening, RevRivulet logs that it is using the server already there and does not start a second one. That is the safe default:

- RevRivulet alone downloads `stremio-server-go` into **its own** profile (`addon_data/plugin.video.revrivulet/bin`) and uses `addon_data/plugin.video.revrivulet/server` as `APP_PATH`. Official Rivulet's `addon_data/plugin.video.rivulet/` is not written.
- Official Rivulet already running: RevRivulet reuses `127.0.0.1:11470`. Playback goes through that process. Cache and torrent state live in whichever addon started it.
- Both starting together, neither listening yet: each can pass the probe and try to bind `11470`. One bind wins; the other exits and the next probe attaches to the winner. The supervision loop already restarts a dead child and re-probes. This race is not removed, because fixing it would mean changing server code.

The addon id had to change. The service installs the binary and runs `RunAddon(<id>)` with that id. Leaving it as `plugin.video.rivulet` would write into official Rivulet's data directory and autoload the official addon.

The Stream4Me bridge, when it is on, listens on `11480` in both addons. It is off unless the interface language is Italian and `plugin.video.s4me` is installed (same gating as before). Two bridges enabled at once can race on `11480` the same way. That default was not changed.

## What is not the official addon

`repository.rivulet/` in this tree is still the upstream repository definition and still points at `rivulet-kodi.github.io`. This fork publishes `repository.revrivulet` only.
