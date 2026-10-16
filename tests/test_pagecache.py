# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Slim catalog-page cache. No Kodi, and not metacache."""
import json
import os

from lib.stremio.pagecache import (
    BUDGET_BYTES,
    DEFAULT_MAX_AGE,
    PageCache,
    cache_key,
    hints_from_envelope,
    slim_meta,
)


def _meta(index):
    return {
        'id': 'tt%d' % index,
        'type': 'movie',
        'name': 'Title %d' % index,
        'poster': 'https://img.example/%d.jpg' % index,
        'background': 'https://img.example/bg%d.jpg' % index,
        'logo': 'https://img.example/logo%d.png' % index,
        'description': 'x' * 500,
        'cast': [{'name': 'Someone'}],
        'trailers': [{'source': 'yt'}],
        'links': [{'url': 'https://example'}],
        'awards': 'Oscar',
        'popularities': {'moviedb': 12.5, 'trakt': 99},
        'imdbRating': '8.0',
    }


def test_slim_meta_keeps_the_poster_fields_and_drops_the_rest():
    meta = _meta(1)
    meta['genres'] = ['Drama', 'Thriller']
    meta['rottenTomatoes'] = '91%'
    meta['ratings'] = [
        {'source': 'Metacritic', 'value': '80'},
        {'source': 'Trakt', 'value': '90'},
    ]
    slim = slim_meta(meta)
    assert slim['poster'].endswith('/1.jpg')
    assert slim['description'] == 'x' * 280
    assert slim['popularities'] == {'moviedb': 12.5}
    assert slim['genres'] == ['Drama', 'Thriller']
    assert slim['rottenTomatoes'] == '91%'
    assert slim['ratings'] == [{'source': 'Metacritic', 'value': '80'}]
    assert 'cast' not in slim
    assert 'trailers' not in slim
    assert 'links' not in slim
    assert 'awards' not in slim
    assert 'trakt' not in json.dumps(slim).lower()
    assert slim_meta('nope') is None


def test_slim_meta_keeps_country_and_language():
    """The region checklist reads these off a cached row. Dropping them
    made a hidden country look unlabeled on the next launch."""
    slim = slim_meta({
        'id': 'tt1', 'country': 'India', 'language': 'Hindi',
        'original_language': 'hi', 'cast': ['A'],
    })
    assert slim['country'] == 'India'
    assert slim['language'] == 'Hindi'
    assert slim['original_language'] == 'hi'
    assert 'cast' not in slim


def test_hints_come_from_the_envelope():
    hints = hints_from_envelope({
        'metas': [], 'cacheMaxAge': 14400, 'staleRevalidate': 3600,
        'staleError': 3600, 'hasMore': False, 'cacheMaxAgeIgnored': 'soon',
    })
    assert hints == {
        'cacheMaxAge': 14400, 'staleRevalidate': 3600,
        'staleError': 3600, 'hasMore': False,
    }


def test_fresh_then_stale_then_miss(tmp_path):
    clock = {'now': 1000.0}
    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])
    key = cache_key('https://a/manifest.json', 'movie', 'top', [('genre', 'Action')])
    cache.store(key, [_meta(1)], {'cacheMaxAge': 100, 'staleRevalidate': 50, 'staleError': 25})
    assert cache.lookup(key)[0] == 'fresh'
    clock['now'] = 1000 + 100
    state, metas = cache.lookup(key)
    assert state == 'stale'
    assert metas[0]['id'] == 'tt1'
    clock['now'] = 1000 + 100 + 50 + 25
    assert cache.lookup(key)[0] == 'miss'


def test_default_fresh_window_is_fifteen_minutes(tmp_path):
    clock = {'now': 0.0}
    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])
    key = cache_key('t', 'movie', 'top', None)
    cache.store(key, [_meta(1)], {})
    clock['now'] = DEFAULT_MAX_AGE - 1
    assert cache.lookup(key)[0] == 'fresh'
    clock['now'] = DEFAULT_MAX_AGE
    assert cache.lookup(key)[0] == 'stale'


def test_save_is_one_file_and_reloads(tmp_path):
    path = str(tmp_path / 'catalog_pages.json')
    cache = PageCache(path, clock=lambda: 10)
    cache.store(cache_key('t', 'movie', 'top'), [_meta(3)], {'cacheMaxAge': 14400})
    cache.save()
    assert os.path.isfile(path)
    again = PageCache(path, clock=lambda: 10)
    state, metas = again.lookup(cache_key('t', 'movie', 'top'))
    assert state == 'fresh'
    assert metas[0]['name'] == 'Title 3'
    assert 'cast' not in json.dumps(metas)


def test_budget_drops_the_oldest_pages(tmp_path):
    clock = {'now': 0.0}
    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])
    for index in range(80):
        clock['now'] = index
        metas = [_meta(index * 100 + item) for item in range(40)]
        cache.store(cache_key('t', 'movie', 'c%d' % index), metas, {})
    assert len(cache._entries) < 80
    assert cache._encoded_size() <= BUDGET_BYTES
    newest = cache_key('t', 'movie', 'c79')
    assert newest in cache._entries
