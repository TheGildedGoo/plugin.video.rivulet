# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Play a title's trailer.

Stremio metas carry trailers as YouTube ids: Cinemeta's
``trailerStreams`` (``[{"title", "ytId"}]``) and the older ``trailers``
(``[{"source": <id>, "type": "Trailer"}]``). The streaming server turns
a ``ytId`` into a playable stream at ``/yt/<id>`` (`ServerClient.
resolve_stream`), which is how Stremio itself plays them: no YouTube API
key. When the server is not answering, Kodi's YouTube add-on is the
fallback, if it is installed.

A trailer is not a title being watched: it records no progress, makes
no Continue entry and starts no Up next. The screens close for it the
way they do for any playback (a dialog left on top would take the
remote from the player) and reopen where they were when it stops.
"""

import re

#: A YouTube video id. Anything else in a trailer field is ignored.
_YT_ID = re.compile(r'^[A-Za-z0-9_-]{6,20}$')
_YOUTUBE_ADDON = 'plugin.video.youtube'
#: Seconds to wait for the streaming server's first bytes of a trailer.
PROBE_SECONDS = 6.0
#: A trailer that has not started by then is given up on, so the screens
#: come back quickly instead of after a feature's 45 seconds.
START_TIMEOUT_SECONDS = 15.0


def trailer_id(meta):
    """The first trailer's YouTube id in `meta`, or ``''``. Kodi-free."""
    if not isinstance(meta, dict):
        return ''
    for entry in meta.get('trailerStreams') or []:
        if isinstance(entry, dict):
            yt = str(entry.get('ytId') or '').strip()
            if _YT_ID.match(yt):
                return yt
    candidates = []
    for entry in meta.get('trailers') or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get('source') or '').strip()
        if not _YT_ID.match(source):
            continue
        kind = str(entry.get('type') or '').lower()
        candidates.append((0 if kind == 'trailer' else 1, source))
    if candidates:
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]
    return ''


def _server_url(yt):
    """``<server>/yt/<id>`` when the streaming server answers it with
    video, else ``''``. Probed first: not every server build has the
    ``/yt`` route, and handing Kodi a URL that fails closed the screens
    and showed "One or more items failed to play"."""
    from lib.ui.player import _server_client

    try:
        server = _server_client()
        if not server.is_available():
            return ''
        url = server.resolve_stream({'ytId': yt}) or ''
    except Exception:
        return ''
    return url if url and _plays(url) else ''


def _plays(url):
    """True when `url` starts answering with something that is not a page."""
    try:
        import requests
    except Exception:
        return False
    try:
        response = requests.get(url, stream=True, timeout=PROBE_SECONDS, headers={'Range': 'bytes=0-1023'})
    except Exception:
        return False
    try:
        if response.status_code not in (200, 206):
            return False
        kind = str(response.headers.get('Content-Type') or '').lower()
        return not kind.startswith(('text/', 'application/json'))
    finally:
        try:
            response.close()
        except Exception:
            pass


def _youtube_addon_url(yt):
    import xbmc

    if not xbmc.getCondVisibility('System.HasAddon(%s)' % _YOUTUBE_ADDON):
        return ''
    return 'plugin://%s/play/?video_id=%s' % (_YOUTUBE_ADDON, yt)


def trailer_url(yt):
    """Where to play `yt` from: Kodi's YouTube add-on when it is
    installed (it plays YouTube reliably), else the streaming server's
    ``/yt`` route when that answers with video, else ``''``."""
    return _youtube_addon_url(yt) or _server_url(yt)


def _full_meta(meta, stype, sid):
    """`meta`, or the full meta when `meta` has no trailer field (a
    catalog preview drops them)."""
    if trailer_id(meta) or not stype or not sid:
        return meta
    from lib.ui.compat import L
    from lib.ui.uicommon import CANCELLED, run_cancellable
    from lib.ui.views import _fetch_meta

    fetched = run_cancellable(lambda: _fetch_meta(stype, sid), L(30033))
    if fetched is CANCELLED or not isinstance(fetched, dict):
        return meta
    return fetched


def play_trailer(meta, stype='', sid=''):
    """Play the trailer of `meta`, blocking until it stops. True when one played."""
    import xbmc
    import xbmcgui

    from lib.ui.compat import L, log, notify
    from lib.ui.uicommon import close_windows_for_playback, end_player_phase

    full = _full_meta(meta if isinstance(meta, dict) else {}, stype, sid)
    yt = trailer_id(full)
    if not yt:
        notify(L(30497))
        return False
    url = trailer_url(yt)
    if not url:
        _offer_youtube_addon(L, notify)
        return False
    name = (full or {}).get('name') or ''
    item = xbmcgui.ListItem(label=('%s – %s' % (name, L(30499))) if name else L(30499))
    item.setPath(url)
    log('trailer: playing %s' % yt, xbmc.LOGINFO)
    close_windows_for_playback()
    try:
        xbmc.Player().play(url, item)
        from lib.ui.streamswindow import _wait_for_playback_end

        _wait_for_playback_end(start_timeout=START_TIMEOUT_SECONDS)
    finally:
        end_player_phase()
    return True


def _offer_youtube_addon(L, notify):
    """Nothing can play it: offer Kodi's YouTube add-on, which Kodi then
    installs from its own repository (it asks once more itself)."""
    import xbmc

    from lib.ui import dialogs

    if xbmc.getCondVisibility('System.HasAddon(%s)' % _YOUTUBE_ADDON):
        notify(L(30498))
        return
    try:
        yes = dialogs.confirm(L(30499), L(30504), xbmc.getLocalizedString(107), xbmc.getLocalizedString(106))
    except Exception:
        yes = False
    if yes:
        xbmc.executebuiltin('InstallAddon(%s)' % _YOUTUBE_ADDON)
