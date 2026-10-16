# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Optional Rotten Tomatoes / Metacritic / IMDb scores for the hero panel.

Cinemeta's catalog meta usually carries `imdbRating` and nothing else.
When the user has put an OMDb key, an MDBList key, or both in settings,
the hero asks that service for the focused title's IMDb id and fills
whatever comes back. An empty key means this module is not called.

The key travels only as a request parameter. Nothing in this module
logs, and `RatingsError` carries a short category (`timeout`,
`rejected`, `not found`) rather than `str(exc)`, because a `requests`
error repeats the full URL, query string included.

No xbmc import. The 24-hour cache is a JSON file the caller points at.
"""

import json
import os
import re
import tempfile
import threading
import time

TTL_SECONDS = 24 * 60 * 60

OMDB_URL = 'https://www.omdbapi.com/'
MDBLIST_URL = 'https://api.mdblist.com/'

_TIMEOUT = 8

_IMDB_RE = re.compile(r'tt\d{7,8}')

_EMPTY = frozenset(('n/a', 'na', 'none', 'null'))

_OMDB_RT = frozenset(('rotten tomatoes',))
_OMDB_META = frozenset(('metacritic',))
_OMDB_IMDB = frozenset(('internet movie database',))

#: Exact source names. `tomatoesaudience` is the audience score, not
#: the critic Tomatometer the panel is asking for, so a substring match
#: would file it under Rotten Tomatoes.
_MDB_RT = frozenset(('tomatoes', 'rotten tomatoes', 'rottentomatoes'))
_MDB_META = frozenset(('metacritic', 'metascore'))
_MDB_IMDB = frozenset(('imdb', 'internet movie database'))

_SCORE_KEYS = ('rottenTomatoes', 'metascore', 'imdbRating')

_FACT_KEYS = (
    'id', 'imdb_id', 'imdbId', 'imdbID',
    'imdbRating', 'year', 'releaseInfo', 'released', 'runtime',
    'rottenTomatoes', 'rtRating', 'tomatoMeter', 'tomatoes',
    'metascore', 'metacritic', 'metaScore',
)


class RatingsError(Exception):
    """A fetch that produced no scores. `empty` is a definitive miss
    (unknown id, 404) and is safe to cache. Anything else should be
    retried later, and the message is a category, never a URL."""

    def __init__(self, category, empty=False):
        super().__init__(category)
        self.empty = empty


def imdb_id_of(value):
    """`tt` plus 7 or 8 digits, or '' when `value` has no IMDb id.

    Episode ids (`tt0944947:1:3`) keep the series id. A dict is checked
    at `imdb_id` / `imdbId` / `imdbID` before `id`, because a Stremio
    id is sometimes `tmdb:…` while the IMDb id sits beside it.
    """
    if isinstance(value, dict):
        for key in ('imdb_id', 'imdbId', 'imdbID', 'id'):
            found = imdb_id_of(value.get(key))
            if found:
                return found
        return ''
    text = str(value or '').strip()
    if not text:
        return ''
    head = text.split(':', 1)[0]
    match = _IMDB_RE.search(head) or _IMDB_RE.search(text)
    return match.group(0) if match else ''


def panel_facts(meta):
    """The slice of a catalog meta the hero panel can draw, and no more.

    Cast, description and the API keys are not in here. Stored on the
    list item so a later cache hit can rebuild the panel without the
    original meta object.
    """
    if not isinstance(meta, dict):
        return {}
    facts = {}
    for key in _FACT_KEYS:
        value = meta.get(key)
        if isinstance(value, bool) or value in (None, ''):
            continue
        if isinstance(value, (int, float)) and value <= 0:
            continue
        facts[key] = value
    genres = meta.get('genres')
    names = []
    if isinstance(genres, list):
        for genre in genres:
            if isinstance(genre, str) and genre.strip():
                names.append(genre.strip())
            if len(names) == 3:
                break
    if names:
        facts['genres'] = names
    return facts


def merge_scores(meta, scores):
    """Copy `meta` with non-empty fetched scores written over the top.

    A score the service did not send is left as the catalog had it, so
    a Cinemeta IMDb rating survives an OMDb reply that only has
    Rotten Tomatoes.
    """
    if not isinstance(meta, dict):
        meta = {}
    merged = dict(meta)
    if not isinstance(scores, dict):
        return merged
    for key in _SCORE_KEYS:
        value = scores.get(key)
        if value:
            merged[key] = value
    return merged


def _complete(scores):
    return all(scores.get(key) for key in _SCORE_KEYS)


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _score_text(value, percent=False):
    """A display score, or '' for N/A and blanks.

    Rotten Tomatoes is a percent (`91%`). IMDb keeps one decimal
    (`8.8`). Metacritic is a whole number (`82`). A `8.8/10` or
    `82/100` value keeps the part before the slash.
    """
    text = str(value or '').strip()
    if not text or text.lower() in _EMPTY:
        return ''
    if '/' in text:
        text = text.split('/', 1)[0].strip()
    if not text or text.lower() in _EMPTY:
        return ''
    if percent and text.endswith('%'):
        return text
    number = _number(text)
    if number is None:
        return text
    if percent:
        return '%d%%' % int(round(number))
    if number > 10:
        return '%d' % int(round(number))
    return '%.1f' % number


def _take(scores, key, value, percent=False):
    if scores.get(key):
        return
    text = _score_text(value, percent=percent)
    if text:
        scores[key] = text


def parse_omdb(payload):
    """Scores from one OMDb title object. `Response: False` with a
    key or limit error raises. A missing title is an empty dict."""
    if not isinstance(payload, dict):
        return {}
    if str(payload.get('Response') or '').lower() == 'false':
        error = str(payload.get('Error') or '').lower()
        if 'key' in error or 'limit' in error:
            raise RatingsError('rejected')
        return {}
    scores = {}
    _take(scores, 'imdbRating', payload.get('imdbRating'))
    _take(scores, 'metascore', payload.get('Metascore'))
    for entry in payload.get('Ratings') or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get('Source') or '').strip().lower()
        value = entry.get('Value')
        if source in _OMDB_RT:
            _take(scores, 'rottenTomatoes', value, percent=True)
        elif source in _OMDB_META:
            _take(scores, 'metascore', value)
        elif source in _OMDB_IMDB:
            _take(scores, 'imdbRating', value)
    return scores


def parse_mdblist(payload):
    """Scores from one MDBList title object or a one-element list."""
    if isinstance(payload, list):
        payload = payload[0] if payload and isinstance(payload[0], dict) else None
    if not isinstance(payload, dict):
        return {}
    scores = {}
    for entry in payload.get('ratings') or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get('source') or '').strip().lower()
        value = entry.get('value')
        if source in _MDB_RT:
            _take(scores, 'rottenTomatoes', value, percent=True)
        elif source in _MDB_META:
            _take(scores, 'metascore', value)
        elif source in _MDB_IMDB:
            _take(scores, 'imdbRating', value)
    return scores


def _get_json(get, url, params, timeout):
    try:
        response = get(url, params=params, timeout=timeout)
    except Exception as exc:
        raise RatingsError(type(exc).__name__)
    try:
        status = getattr(response, 'status_code', 0)
        if status == 404:
            raise RatingsError('not found', empty=True)
        if status in (401, 403):
            raise RatingsError('rejected')
        if status != 200:
            raise RatingsError('http %s' % status)
        try:
            payload = response.json()
        except Exception:
            raise RatingsError('json')
    finally:
        close = getattr(response, 'close', None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    return payload


def _ask(get, url, params, timeout, parse):
    """One service. Returns scores, a definitive miss, and a failure.

    A rejected key or a transport error is a failure. An unknown title
    is a miss. `parse` raising `RatingsError` counts the same way.
    """
    try:
        found = parse(_get_json(get, url, params, timeout))
    except RatingsError as exc:
        return {}, exc.empty, not exc.empty
    if found:
        return found, False, False
    return {}, True, False


def fetch_scores(imdb_id, omdb_key='', mdblist_key='', get=None, timeout=_TIMEOUT):
    """Scores for one IMDb id, or {} when the title is unknown.

    OMDb is asked first. MDBList is asked only when a key is set and
    OMDb left a score out. A transport failure raises `RatingsError`
    so the caller does not cache it for a day. A definitive miss
    returns {} and the caller may cache that.

    `get` is `requests.get`-shaped (`url`, `params`, `timeout`) so
    tests never open a socket.
    """
    imdb_id = imdb_id_of(imdb_id)
    omdb_key = (omdb_key or '').strip()
    mdblist_key = (mdblist_key or '').strip()
    if not imdb_id or not (omdb_key or mdblist_key):
        return {}
    if get is None:
        import requests
        get = requests.get
    scores = {}
    saw_empty = False
    saw_error = False
    if omdb_key:
        found, empty, error = _ask(get, OMDB_URL, {
            'i': imdb_id, 'apikey': omdb_key, 'tomatoes': 'true',
        }, timeout, parse_omdb)
        scores.update(found)
        saw_empty = empty
        saw_error = error
    if mdblist_key and not _complete(scores):
        found, empty, error = _ask(get, MDBLIST_URL + imdb_id, {
            'apikey': mdblist_key,
        }, timeout, parse_mdblist)
        for key, value in found.items():
            if value and not scores.get(key):
                scores[key] = value
        if empty and not scores:
            saw_empty = True
        saw_error = saw_error or error
    if scores:
        return scores
    if saw_error and not saw_empty:
        raise RatingsError('unavailable')
    return {}


def _atomic_write(path, payload):
    directory = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp-ratings-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps(payload, separators=(',', ':')))
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


class RatingsCache:
    """IMDb id to scores, fresh for `TTL_SECONDS`. `clock` is injectable.

    The file holds scores only. A failed lookup is not written: the
    caller decides that, and a bad key must not stick for a day.
    """

    def __init__(self, path, clock=None):
        self.path = path
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._entries = {}
        self._load()

    def _now(self):
        return self._clock()

    def _load(self):
        try:
            with open(self.path) as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        self._entries = payload

    def lookup(self, imdb_id, now=None):
        """The cached scores, {} for a cached miss, or None when stale."""
        imdb_id = imdb_id_of(imdb_id)
        if not imdb_id:
            return None
        now = self._now() if now is None else now
        with self._lock:
            entry = self._entries.get(imdb_id)
            if not isinstance(entry, dict):
                return None
            at = entry.get('at')
            scores = entry.get('scores')
            if isinstance(at, bool) or not isinstance(at, (int, float)):
                return None
            if not isinstance(scores, dict):
                return None
            if now - at > TTL_SECONDS:
                return None
            return dict(scores)

    def store(self, imdb_id, scores, now=None):
        imdb_id = imdb_id_of(imdb_id)
        if not imdb_id:
            return
        if not isinstance(scores, dict):
            scores = {}
        kept = {}
        for key in _SCORE_KEYS:
            value = scores.get(key)
            if value:
                kept[key] = value
        now = self._now() if now is None else now
        with self._lock:
            self._entries[imdb_id] = {'at': now, 'scores': kept}
            self._trim()
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            _atomic_write(self.path, self._entries)

    def _trim(self):
        """Bound the file. Oldest stamps go first. Called with the lock."""
        if len(self._entries) <= 400:
            return
        ordered = sorted(
            self._entries.items(),
            key=lambda item: item[1].get('at', 0) if isinstance(item[1], dict) else 0,
        )
        for key, _entry in ordered[:len(self._entries) - 400]:
            self._entries.pop(key, None)
