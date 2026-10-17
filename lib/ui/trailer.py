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
    """``<server>/yt/<id>`` when the streaming server answers, else ``''``."""
    from lib.ui.player import _server_client

    try:
        server = _server_client()
        if not server.is_available():
            return ''
        return server.resolve_stream({'ytId': yt}) or ''
    except Exception:
        return ''


def _youtube_addon_url(yt):
    import xbmc

    if not xbmc.getCondVisibility('System.HasAddon(%s)' % _YOUTUBE_ADDON):
        return ''
    return 'plugin://%s/play/?video_id=%s' % (_YOUTUBE_ADDON, yt)


def trailer_url(yt):
    """Where to play `yt` from: the streaming server first, then Kodi's
    YouTube add-on, else ``''``."""
    return _server_url(yt) or _youtube_addon_url(yt)


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
        notify(L(30498))
        return False
    name = (full or {}).get('name') or ''
    item = xbmcgui.ListItem(label=('%s – %s' % (name, L(30499))) if name else L(30499))
    item.setPath(url)
    log('trailer: playing %s' % yt, xbmc.LOGINFO)
    close_windows_for_playback()
    try:
        xbmc.Player().play(url, item)
        from lib.ui.streamswindow import _wait_for_playback_end

        _wait_for_playback_end()
    finally:
        end_player_phase()
    return True
