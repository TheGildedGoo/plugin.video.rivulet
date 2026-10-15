# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Score a parsed stream for the Rev2 "best match" line.

This does not replace ``lib.stremio.streaminfo.sort_streams``. The
streams sheet still sorts with that function, because its order is what
the live-merge path uses to keep the focused row still. ``rank`` is the
spec's scorer, ready for a later switch and used by tests so the
weights do not rot.

Priorities, high to low: starts instantly, the box can play it,
resolution, HDR, audio, seeds. CAM/TS and a "4K" under 400 MB sink.
"""
import re
from dataclasses import dataclass, field

RES = (
    ('2160', 400, '4K'),
    ('4k', 400, '4K'),
    ('uhd', 400, '4K'),
    ('1080', 300, '1080p'),
    ('720', 150, '720p'),
    ('576', 60, 'SD'),
    ('480', 50, 'SD'),
)
_CACHED_RE = re.compile(r'\[(rd|ad|pm|tb|dl|ed)\+\]|\binstant\b|\bcached\b', re.I)
_CAM_RE = re.compile(r'\b(cam|hdcam|camrip|ts|hdts|telesync|tc|telecine)\b', re.I)
_SIZE_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*(gb|gib|mb|mib)\b', re.I)
_SEEDS_RE = re.compile(r'(?:seed(?:er)?s?[:\s]*)\s*(\d+)', re.I)
_HDR_DV_RE = re.compile(r'\b(dv|dovi|dolby.?vision)\b', re.I)
_HEVC_RE = re.compile(r'\b(hevc|x265|h\.?265)\b', re.I)
_AVC_RE = re.compile(r'\b(x264|h\.?264|avc)\b', re.I)


@dataclass
class Prefs:
    """What this box should be offered. Defaults allow 4K, DV and AV1."""

    max_res: int = 400
    dv_ok: bool = True
    av1_ok: bool = True
    max_gb: float = 1000.0
    last_good_addon: str = ''
    session_penalty: dict = field(default_factory=dict)


@dataclass
class Parsed:
    """One stream reduced to the fields the scorer reads."""

    raw: dict
    addon: str
    res: int = 100
    quality: str = '?'
    hdr: str = ''
    codec: str = ''
    audio: str = ''
    size_gb: float = 0.0
    seeds: int = 0
    cached: bool = False
    direct: bool = False
    cam: bool = False
    score: float = 0.0
    reasons: list = field(default_factory=list)


def parse(stream, addon):
    """Read resolution, HDR, size and cache state out of one stream dict."""
    stream = stream or {}
    hints = stream.get('behaviorHints') or {}
    parts = (
        stream.get('name'),
        stream.get('title'),
        stream.get('description'),
        hints.get('filename'),
    )
    text = ' '.join(part for part in parts if part)
    low = text.lower()
    parsed = Parsed(raw=stream, addon=addon or '')
    parsed.res, parsed.quality = _resolution(low)
    parsed.hdr = _hdr(low)
    parsed.codec = _codec(low)
    parsed.audio = _audio(low)
    parsed.size_gb = _size(text, hints)
    parsed.seeds = _seeds(text)
    parsed.direct = bool(stream.get('url')) and not stream.get('infoHash')
    parsed.cached = bool(_CACHED_RE.search(text)) or (parsed.direct and '+' in (stream.get('name') or ''))
    parsed.cam = bool(_CAM_RE.search(low))
    return parsed


def _resolution(low):
    for key, score, label in RES:
        if key in low:
            return score, label
    return 100, '?'


def _hdr(low):
    if _HDR_DV_RE.search(low):
        return 'DV'
    if 'hdr10+' in low:
        return 'HDR10+'
    if 'hdr' in low:
        return 'HDR'
    return ''


def _codec(low):
    if 'av1' in low:
        return 'av1'
    if _HEVC_RE.search(low):
        return 'hevc'
    if _AVC_RE.search(low):
        return 'avc'
    return ''


def _audio(low):
    for name in ('atmos', 'truehd', 'dts-hd', 'dts', 'ddp', 'dd5.1', 'aac'):
        if name in low:
            return name
    return ''


def _size(text, hints):
    if hints.get('videoSize'):
        return hints['videoSize'] / float(1024 ** 3)
    match = _SIZE_RE.search(text)
    if not match:
        return 0.0
    value = float(match.group(1).replace(',', '.'))
    if match.group(2).lower().startswith('m'):
        return value / 1024.0
    return value


def _seeds(text):
    match = _SEEDS_RE.search(text)
    if not match:
        return 0
    return int(match.group(1))


def score(parsed, prefs):
    """Write ``parsed.score`` and return ``parsed``. Higher is better."""
    prefs = prefs or Prefs()
    total = float(parsed.res)
    if parsed.res > prefs.max_res:
        total -= 250
    if parsed.cached or parsed.direct:
        total += 220
        parsed.reasons.append('Instant')
    else:
        total += min(parsed.seeds, 200) * 0.6 - 60
    total += _hdr_weight(parsed, prefs)
    if parsed.codec == 'av1' and not prefs.av1_ok:
        total -= 200
    total += _size_weight(parsed, prefs)
    if parsed.audio in ('atmos', 'truehd', 'dts-hd'):
        total += 15
    if parsed.cam:
        total -= 600
    if parsed.addon and parsed.addon == prefs.last_good_addon:
        total += 25
    total -= prefs.session_penalty.get(parsed.addon, 0)
    parsed.score = total
    return parsed


def _hdr_weight(parsed, prefs):
    if parsed.hdr == 'DV':
        return 40 if prefs.dv_ok else -120
    if parsed.hdr:
        return 30
    return 0


def _size_weight(parsed, prefs):
    if not parsed.size_gb:
        return 0
    if parsed.size_gb > prefs.max_gb:
        return -150
    # A few hundred megabytes labelled 4K is a mislabel, not a file.
    if parsed.size_gb < 0.4 and parsed.res >= 300:
        return -120
    return 0


def best_reason(parsed):
    """One glanceable line: ``4K · Dolby Vision · Instant · Torrentio``."""
    hdr = ''
    if parsed.hdr == 'DV':
        hdr = 'Dolby Vision'
    elif parsed.hdr:
        hdr = parsed.hdr
    if parsed.cached or parsed.direct:
        speed = 'Instant'
    elif parsed.seeds:
        speed = '%d seeds' % parsed.seeds
    else:
        speed = ''
    quality = '' if parsed.quality == '?' else parsed.quality
    bits = [quality, hdr, speed, parsed.addon]
    return ' · '.join(bit for bit in bits if bit)


def merge(shown, incoming, user_moved):
    """Re-sort until the user touches a key, then append below.

    After the first key press the focused row is whatever ``shown``
    already is. New results are ranked among themselves and added under
    it, so the row under the cursor never moves.
    """
    shown = list(shown or [])
    incoming = list(incoming or [])
    if not user_moved:
        return sorted(shown + incoming, key=lambda item: -item.score)
    return shown + sorted(incoming, key=lambda item: -item.score)
