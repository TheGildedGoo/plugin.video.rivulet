# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""OMDb / MDBList scores. No Kodi, and no socket: `get` is injected.

The key is a request parameter. A failure's text is the exception
class, never `str(exc)`, because a `requests` error repeats the URL.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lib.stremio.ratings import (
    MDBLIST_URL,
    OMDB_URL,
    TTL_SECONDS,
    RatingsCache,
    RatingsError,
    _get_json,
    fetch_scores,
    imdb_id_of,
    merge_scores,
    panel_facts,
    parse_mdblist,
    parse_omdb,
)

_ROOT = Path(__file__).resolve().parent.parent
_SECRET = 'SECRETKEY'


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.closed = False

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def close(self):
        self.closed = True


def _get(responses):
    """`requests.get`-shaped callable. `responses` is consumed in order."""
    calls = []

    def get(url, params=None, timeout=None):
        response = responses.pop(0)
        calls.append((url, dict(params or {}), timeout, response))
        return response

    get.calls = calls
    return get


def test_imdb_id_keeps_the_series_id_and_ignores_other_schemes():
    assert imdb_id_of('tt0944947:1:3') == 'tt0944947'
    assert imdb_id_of({'id': 'tmdb:550', 'imdb_id': 'tt0137523'}) == 'tt0137523'
    assert imdb_id_of({'id': 'tmdb:550'}) == ''
    assert imdb_id_of('tt123456') == ''
    assert imdb_id_of('tt1234567') == 'tt1234567'


def test_omdb_scores_and_omitted_blanks():
    scores = parse_omdb({
        'Response': 'True',
        'imdbRating': '8.8',
        'Metascore': '82',
        'Ratings': [
            {'Source': 'Internet Movie Database', 'Value': '8.8/10'},
            {'Source': 'Rotten Tomatoes', 'Value': '96%'},
            {'Source': 'Metacritic', 'Value': '82/100'},
        ],
    })
    assert scores == {
        'imdbRating': '8.8',
        'metascore': '82',
        'rottenTomatoes': '96%',
    }
    assert parse_omdb({
        'Response': 'True',
        'imdbRating': 'N/A',
        'Metascore': 'N/A',
        'Ratings': [{'Source': 'Rotten Tomatoes', 'Value': 'N/A'}],
    }) == {}
    assert parse_omdb({'Response': 'False', 'Error': 'Movie not found!'}) == {}


def test_omdb_rejects_a_bad_key_without_repeating_it():
    with pytest.raises(RatingsError) as caught:
        parse_omdb({'Response': 'False', 'Error': 'Invalid API key!'})
    assert str(caught.value) == 'rejected'
    assert caught.value.empty is False
    assert _SECRET not in str(caught.value)


def test_mdblist_uses_the_critic_score_only():
    scores = parse_mdblist({
        'ratings': [
            {'source': 'imdb', 'value': 8.8},
            {'source': 'metacritic', 'value': 82},
            {'source': 'tomatoes', 'value': 91},
            {'source': 'tomatoesaudience', 'value': 95},
            {'source': 'trakt', 'value': 80},
        ],
    })
    assert scores == {
        'imdbRating': '8.8',
        'metascore': '82',
        'rottenTomatoes': '91%',
    }
    assert parse_mdblist([{'ratings': [{'source': 'imdb', 'value': 7.0}]}]) == {
        'imdbRating': '7.0',
    }


def test_cache_is_fresh_for_a_day_and_holds_scores_only(tmp_path):
    path = tmp_path / 'ratings.json'
    cache = RatingsCache(str(path))
    assert cache.lookup('tt0111161') is None
    cache.store('tt0111161', {'imdbRating': '8.8', 'apikey': _SECRET}, now=0)
    assert cache.lookup('tt0111161', now=TTL_SECONDS) == {'imdbRating': '8.8'}
    assert cache.lookup('tt0111161', now=TTL_SECONDS + 1) is None
    assert _SECRET not in path.read_text(encoding='utf-8')
    cache.store('tt0000001', {}, now=0)
    assert cache.lookup('tt0000001', now=0) == {}
    reloaded = RatingsCache(str(path))
    assert reloaded.lookup('tt0000001', now=0) == {}


def test_a_corrupt_cache_is_ignored(tmp_path):
    path = tmp_path / 'ratings.json'
    path.write_text('not json', encoding='utf-8')
    assert RatingsCache(str(path)).lookup('tt0111161') is None


def test_fetch_fills_gaps_from_mdblist_and_stops_when_omdb_is_complete():
    omdb = _Response(200, {
        'Response': 'True',
        'imdbRating': '8.1',
        'Metascore': 'N/A',
        'Ratings': [],
    })
    mdblist = _Response(200, {
        'ratings': [
            {'source': 'tomatoes', 'value': 91},
            {'source': 'imdb', 'value': 1.0},
        ],
    })
    get = _get([omdb, mdblist])
    scores = fetch_scores('tt0111161', omdb_key=_SECRET, mdblist_key='MDBSECRET', get=get)
    assert scores == {'imdbRating': '8.1', 'rottenTomatoes': '91%'}
    assert get.calls[0][0] == OMDB_URL
    assert get.calls[0][1]['apikey'] == _SECRET
    assert get.calls[0][1]['i'] == 'tt0111161'
    # No type given: looked up as a movie.
    assert get.calls[1][0] == MDBLIST_URL + 'imdb/movie/tt0111161'
    assert get.calls[1][1]['apikey'] == 'MDBSECRET'
    assert omdb.closed and mdblist.closed

    full = _Response(200, {
        'Response': 'True',
        'imdbRating': '8.8',
        'Metascore': '82',
        'Ratings': [{'Source': 'Rotten Tomatoes', 'Value': '96%'}],
    })
    get = _get([full])
    fetch_scores('tt0111161', omdb_key=_SECRET, mdblist_key='MDBSECRET', get=get)
    assert len(get.calls) == 1


def test_no_key_and_a_non_imdb_id_do_not_call_out():
    def get(*_args, **_kwargs):
        raise AssertionError('get was called')

    assert fetch_scores('tt0111161', get=get) == {}
    assert fetch_scores('tmdb:550', omdb_key=_SECRET, get=get) == {}


def test_a_missing_title_is_an_empty_cacheable_result():
    missing = _Response(404, None)
    get = _get([missing])
    assert fetch_scores('tt0111161', omdb_key=_SECRET, get=get) == {}
    assert missing.closed


def test_a_transport_error_does_not_repeat_the_key():
    def get(url, params=None, timeout=None):
        raise TimeoutError('GET %s?apikey=%s' % (url, (params or {}).get('apikey')))

    with pytest.raises(RatingsError) as caught:
        _get_json(get, OMDB_URL, {'apikey': _SECRET, 'i': 'tt0111161'}, 8)
    assert str(caught.value) == 'TimeoutError'
    assert _SECRET not in str(caught.value)
    assert 'apikey' not in str(caught.value)

    with pytest.raises(RatingsError) as caught:
        fetch_scores('tt0111161', omdb_key=_SECRET, get=get)
    assert str(caught.value) == 'unavailable'
    assert _SECRET not in str(caught.value)


def test_a_rejected_key_is_not_cached_as_a_miss():
    rejected = _Response(200, {'Response': 'False', 'Error': 'Invalid API key!'})
    get = _get([rejected])
    with pytest.raises(RatingsError) as caught:
        fetch_scores('tt0111161', omdb_key=_SECRET, get=get)
    assert str(caught.value) == 'unavailable'
    assert _SECRET not in str(caught.value)
    assert rejected.closed


def test_panel_facts_keep_the_scores_and_drop_the_description():
    facts = panel_facts({
        'id': 'tt0111161',
        'imdbRating': '9.3',
        'year': 1994,
        'runtime': 0,
        'genres': ['Drama', 'Crime', '', 'Extra', 'Fourth'],
        'description': 'A long plot.',
        'apikey': _SECRET,
    })
    assert facts['id'] == 'tt0111161'
    assert facts['genres'] == ['Drama', 'Crime', 'Extra']
    assert 'runtime' not in facts
    assert 'description' not in facts
    assert 'apikey' not in facts
    merged = merge_scores(facts, {'rottenTomatoes': '91%', 'imdbRating': ''})
    assert merged['rottenTomatoes'] == '91%'
    assert merged['imdbRating'] == '9.3'


def test_rating_keys_sit_after_a_toggle_and_stay_out_of_the_server_env():
    root = ET.parse(_ROOT / 'resources' / 'settings.xml')
    home = root.find(".//category[@id='home']")
    settings = list(home.iter('setting'))
    assert settings[0].find('control').get('type') != 'edit'
    by_id = {setting.get('id'): setting for setting in settings}
    headings = {'ratings_omdb_key': '30455', 'ratings_mdblist_key': '30456'}
    labels = {'ratings_omdb_key': '30453', 'ratings_mdblist_key': '30454'}
    for setting_id, label in labels.items():
        setting = by_id[setting_id]
        assert setting.get('type') == 'string'
        assert setting.get('label') == label
        assert (setting.findtext('default') or '') == ''
        assert setting.findtext('constraints/allowempty') == 'true'
        assert setting.find('control').get('type') == 'edit'
        assert setting.findtext('control/heading') == headings[setting_id]
    server = (_ROOT / 'lib' / 'service_runner.py').read_text(encoding='utf-8')
    assert 'ratings_omdb_key' not in server
    assert 'ratings_mdblist_key' not in server


def test_worker_caches_a_miss_and_logs_only_the_exception_class(kodi_stubs, tmp_path, monkeypatch):
    ctx = kodi_stubs(reload=('lib.ui.compat', 'lib.ui.ratingsched'))
    sched = ctx.ratingsched

    def fail(imdb_id, omdb_key='', mdblist_key='', get=None, timeout=8, stype=''):
        assert omdb_key == _SECRET
        raise TimeoutError('GET https://www.omdbapi.com/?apikey=%s' % _SECRET)

    monkeypatch.setattr('lib.stremio.ratings.fetch_scores', fail)
    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    sched._worker('tt0111161', _SECRET, '', cache, 'fail-id')
    assert cache.lookup('tt0111161') is None
    logged = ' '.join(msg for msg, _level in ctx.env.log_calls)
    assert 'TimeoutError' in logged
    assert _SECRET not in logged
    assert 'apikey' not in logged
    assert 'Action(noop)' in ctx.env.executed_builtins
    assert sched._failed_until['fail-id'] > 0


def test_worker_caches_an_empty_title(kodi_stubs, tmp_path, monkeypatch):
    ctx = kodi_stubs(reload=('lib.ui.compat', 'lib.ui.ratingsched'))

    def empty(*_args, **_kwargs):
        return {}

    monkeypatch.setattr('lib.stremio.ratings.fetch_scores', empty)
    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    ctx.ratingsched._worker('tt0111161', _SECRET, '', cache, 'ok')
    assert cache.lookup('tt0111161') == {}
    logged = ' '.join(msg for msg, _level in ctx.env.log_calls)
    assert _SECRET not in logged


def test_a_skimmed_title_is_never_requested(kodi_stubs, tmp_path, monkeypatch):
    """Latest wins. Holding Right across a row used to fetch every title
    it passed; only the one the focus rests on goes out."""
    ctx = kodi_stubs(reload=('lib.ui.compat', 'lib.ui.ratingsched'))
    sched = ctx.ratingsched
    fetched = []

    def fetch(imdb_id, *_args, **_kwargs):
        fetched.append(imdb_id)
        return {'imdbRating': '7.0'}

    monkeypatch.setattr('lib.stremio.ratings.fetch_scores', fetch)
    monkeypatch.setattr(sched, '_DWELL_SECONDS', 0.2)
    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    for passing in ('tt0000001', 'tt0000002', 'tt0000003'):
        sched._schedule(passing, _SECRET, '', cache)
    import time

    deadline = time.monotonic() + 3
    while sched._plan['running'] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert fetched == ['tt0000003']


def test_the_next_titles_ride_along_after_the_focused_one(kodi_stubs, tmp_path, monkeypatch):
    ctx = kodi_stubs(reload=('lib.ui.compat', 'lib.ui.ratingsched'))
    sched = ctx.ratingsched
    fetched = []
    monkeypatch.setattr(
        'lib.stremio.ratings.fetch_scores',
        lambda imdb_id, *_a, **_k: fetched.append(imdb_id) or {'imdbRating': '7.0'},
    )
    monkeypatch.setattr(sched, '_DWELL_SECONDS', 0.05)
    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    cache.store('tt0000006', {'imdbRating': '6.0'})
    monkeypatch.setattr(sched, '_keys', lambda: (_SECRET, ''))
    monkeypatch.setattr(sched, '_get_cache', lambda: cache)

    sched.overlay_text(
        {'id': 'tt0000005'}, 'fallback',
        [{'id': 'tt0000006'}, {'id': 'tt0000007'}, {'id': 'tt0000008'}],
    )
    import time

    deadline = time.monotonic() + 3
    while sched._plan['running'] and time.monotonic() < deadline:
        time.sleep(0.02)
    # 6 is cached already; the two after the focused title are 7 and 8,
    # capped at PREFETCH.
    assert fetched == ['tt0000005', 'tt0000007', 'tt0000008'][:1 + sched.PREFETCH]


def _mdblist_only():
    reply = _Response(200, {'ratings': [{'source': 'tomatoes', 'value': 91}]})
    return _get([reply])


@pytest.mark.parametrize('stype, path', [
    ('movie', 'imdb/movie/'),
    ('series', 'imdb/show/'),
    ('anime', 'imdb/show/'),
    ('tv', 'imdb/show/'),
    ('anime.movie', 'imdb/movie/'),
    ('anime.series', 'imdb/show/'),
    ('', 'imdb/movie/'),
])
def test_mdblist_is_asked_on_the_path_for_the_titles_type(stype, path):
    get = _mdblist_only()
    scores = fetch_scores('tt0944947', mdblist_key='MDBSECRET', get=get, stype=stype)
    assert scores == {'rottenTomatoes': '91%'}
    assert get.calls[0][0] == MDBLIST_URL + path + 'tt0944947'


def test_a_series_on_home_is_fetched_on_the_show_path(kodi_stubs, tmp_path, monkeypatch):
    """The type rides from the poster's panel facts through overlay_text,
    the plan and the worker to the MDBList request."""
    ctx = kodi_stubs(reload=('lib.ui.compat', 'lib.ui.ratingsched'))
    sched = ctx.ratingsched
    urls = []

    def get(url, params=None, timeout=None, **_kwargs):
        urls.append(url)
        return _Response(200, {'ratings': [{'source': 'tomatoes', 'value': 80}]})

    monkeypatch.setattr('requests.get', get)
    monkeypatch.setattr(sched, '_DWELL_SECONDS', 0.05)
    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    monkeypatch.setattr(sched, '_keys', lambda: ('', 'MDBSECRET'))
    monkeypatch.setattr(sched, '_get_cache', lambda: cache)

    facts = panel_facts({'id': 'tt0944947', 'type': 'series', 'name': 'Show'})
    assert facts['type'] == 'series'
    sched.overlay_text(facts, 'fallback', [panel_facts({'id': 'tt0111161', 'type': 'movie'})])
    import time

    deadline = time.monotonic() + 3
    while sched._plan['running'] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert urls[:2] == [MDBLIST_URL + 'imdb/show/tt0944947', MDBLIST_URL + 'imdb/movie/tt0111161']
