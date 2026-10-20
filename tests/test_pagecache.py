# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Slim catalog-page cache. No Kodi, and not metacache."""
import json
import os

from lib.stremio.pagecache import (
    BUDGET_BYTES,
    DEFAULT_MAX_AGE,
    DEFAULT_STALE_ERROR,
    DEFAULT_STALE_REVALIDATE,
    PageCache,
    cache_key,
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




def test_fresh_then_stale_then_miss(tmp_path):
    clock = {'now': 1000.0}
    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])
    key = cache_key('https://a/manifest.json', 'movie', 'top', [('genre', 'Action')])
    cache.store(key, [_meta(1)])
    assert cache.lookup(key)[0] == 'fresh'
    clock['now'] = 1000 + DEFAULT_MAX_AGE
    state, metas = cache.lookup(key)
    assert state == 'stale'
    assert metas[0]['id'] == 'tt1'
    clock['now'] = 1000 + DEFAULT_MAX_AGE + DEFAULT_STALE_REVALIDATE + DEFAULT_STALE_ERROR
    assert cache.lookup(key)[0] == 'miss'


def test_default_fresh_window_is_fifteen_minutes(tmp_path):
    clock = {'now': 0.0}
    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])
    key = cache_key('t', 'movie', 'top', None)
    cache.store(key, [_meta(1)])
    clock['now'] = DEFAULT_MAX_AGE - 1
    assert cache.lookup(key)[0] == 'fresh'
    clock['now'] = DEFAULT_MAX_AGE
    assert cache.lookup(key)[0] == 'stale'


def test_save_is_one_file_and_reloads(tmp_path):
    path = str(tmp_path / 'catalog_pages.json')
    cache = PageCache(path, clock=lambda: 10)
    cache.store(cache_key('t', 'movie', 'top'), [_meta(3)])
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
        cache.store(cache_key('t', 'movie', 'c%d' % index), metas)
    assert len(cache._entries) < 80
    assert cache._encoded_size() <= BUDGET_BYTES
    newest = cache_key('t', 'movie', 'c79')
    assert newest in cache._entries


def test_an_expired_page_is_served_only_when_asked_and_only_for_a_day(tmp_path):
    """#13: past the stale windows (about two hours) the first open of an
    evening fetched every row cold. A caller that repaints from the cache
    and revalidates at once may take a page up to a day old."""
    from lib.stremio.pagecache import EXPIRED_SERVE_SECONDS

    clock = {'now': 0.0}
    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])
    key = cache_key('t', 'movie', 'top', None)
    cache.store(key, [_meta(1)])
    clock['now'] = DEFAULT_MAX_AGE + DEFAULT_STALE_REVALIDATE + DEFAULT_STALE_ERROR + 1
    assert cache.lookup(key)[0] == 'miss'
    state, metas = cache.lookup(key, allow_expired=True)
    assert state == 'expired' and metas[0]['id'] == 'tt1'
    clock['now'] = EXPIRED_SERVE_SECONDS
    assert cache.lookup(key, allow_expired=True)[0] == 'miss'


def test_save_copies_the_entries_it_writes(tmp_path, monkeypatch):
    """A revalidation storing a page while another thread saves must not
    resize the dict json.dumps is walking."""
    import lib.stremio.pagecache as pagecache

    cache = PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: 10)
    cache.store(cache_key('t', 'movie', 'a', None), [_meta(1)])
    real_write = pagecache._atomic_write

    def _write(path, payload):
        cache.store(cache_key('t', 'movie', 'b', None), [_meta(2)])
        real_write(path, payload)

    monkeypatch.setattr(pagecache, '_atomic_write', _write)
    cache.save()
    with open(str(tmp_path / 'catalog_pages.json')) as handle:
        assert list(json.load(handle)['entries']) == [cache_key('t', 'movie', 'a', None)]


def test_slim_meta_keeps_what_the_adult_check_reads():
    from lib.stremio.pagecache import slim_meta

    slim = slim_meta({'id': 'x', 'name': 'X', 'adult': True, 'genre': 'Drama', 'cast': ['A']})
    assert slim['adult'] is True and slim['genre'] == 'Drama'
    assert 'cast' not in slim


def test_slim_ratings_keep_only_the_scores_the_hero_prints():
    from lib.stremio.pagecache import slim_meta

    as_dict = slim_meta({'id': 'x', 'ratings': {'imdb': 7.1, 'RT': '90%', 'trakt': 70}})
    assert as_dict['ratings'] == {'imdb': 7.1, 'RT': '90%'}
    as_list = slim_meta({'id': 'x', 'ratings': [
        'junk',
        {'source': 'Internet Movie Database', 'value': '7.1'},
        {'name': 'Rotten Tomatoes', 'rating': '90%'},
        {'source': 'Trakt', 'value': '70'},
    ]})
    assert as_list['ratings'] == [
        {'source': 'Internet Movie Database', 'value': '7.1'},
        {'source': 'Rotten Tomatoes', 'value': '90%'},
    ]
    many = slim_meta({'ratings': [{'source': 'imdb', 'value': n} for n in range(10)]})
    assert len(many['ratings']) == 6
    assert 'ratings' not in slim_meta({'ratings': {'trakt': 1}})
    assert 'ratings' not in slim_meta({'ratings': 'n/a'})
    assert slim_meta('not a meta') is None


def test_slim_meta_trims_the_description_and_keeps_moviedb_popularity():
    from lib.stremio.pagecache import _DESCRIPTION_LIMIT, slim_meta

    slim = slim_meta({'id': 'x', 'description': 'a' * (_DESCRIPTION_LIMIT + 50),
                      'popularities': {'moviedb': 12.5, 'trakt': 3}})
    assert len(slim['description']) == _DESCRIPTION_LIMIT
    assert slim['popularities'] == {'moviedb': 12.5}
    assert 'popularities' not in slim_meta({'popularities': {'trakt': 3}})




def test_cache_key_orders_extra_pairs_and_skips_malformed_ones():
    from lib.stremio.pagecache import cache_key

    one = cache_key('t', 'movie', 'top', [('skip', 20), ('genre', 'Drama'), 'junk'])
    two = cache_key('t', 'movie', 'top', [('genre', 'Drama'), ('skip', '20')])
    assert one == two
    assert cache_key(None, None, None) == '\n\n\n'


def test_a_corrupt_or_odd_file_starts_empty(tmp_path):
    from lib.stremio.pagecache import PageCache

    path = tmp_path / 'pages.json'
    path.write_text('{not json')
    assert PageCache(str(path)).lookup('k') == ('miss', None)
    path.write_text('["a list"]')
    assert PageCache(str(path)).lookup('k') == ('miss', None)
    path.write_text('{"entries": {"k": {"stored_at": "soon", "metas": []}, "j": "x"}}')
    cache = PageCache(str(path))
    assert cache.lookup('k') == ('miss', None)
    assert cache.lookup('j') == ('miss', None)


def test_ages_fresh_stale_expired_then_gone(tmp_path):
    from lib.stremio.pagecache import EXPIRED_SERVE_SECONDS, PageCache

    cache = PageCache(str(tmp_path / 'pages.json'), clock=lambda: 0.0)
    cache.store('k', [{'id': 'a'}])
    assert cache.lookup('k', now=5)[0] == 'fresh'
    assert cache.lookup('k', now=DEFAULT_MAX_AGE + 1)[0] == 'stale'
    assert cache.lookup('k', now=DEFAULT_MAX_AGE + DEFAULT_STALE_REVALIDATE + DEFAULT_STALE_ERROR + 1) == ('miss', None)
    assert cache.lookup('k', now=DEFAULT_MAX_AGE + DEFAULT_STALE_REVALIDATE + DEFAULT_STALE_ERROR + 1, allow_expired=True)[0] == 'expired'
    assert cache.lookup('k', now=EXPIRED_SERVE_SECONDS + 1, allow_expired=True) == ('miss', None)


def test_save_makes_the_folder_and_round_trips(tmp_path):
    from lib.stremio.pagecache import PageCache

    path = tmp_path / 'new' / 'dir' / 'pages.json'
    cache = PageCache(str(path), clock=lambda: 1.0)
    cache.store('k', [{'id': 'a', 'name': 'A'}, 'junk'])
    cache.save()
    again = PageCache(str(path), clock=lambda: 2.0)
    assert again.lookup('k') == ('fresh', [{'id': 'a', 'name': 'A'}])


def test_a_failed_write_leaves_no_temp_file(tmp_path, monkeypatch):
    import os

    import pytest

    from lib.stremio import pagecache

    cache = pagecache.PageCache(str(tmp_path / 'pages.json'))
    cache.store('k', [{'id': 'a'}])

    def boom(src, dst):
        raise OSError('disk full')

    monkeypatch.setattr(os, 'replace', boom)
    with pytest.raises(OSError):
        cache.save()
    assert [name for name in os.listdir(str(tmp_path)) if name.startswith('.tmp-pages-')] == []


def test_the_oldest_page_goes_first_when_over_budget(tmp_path, monkeypatch):
    from lib.stremio import pagecache

    monkeypatch.setattr(pagecache, 'BUDGET_BYTES', 400)
    cache = pagecache.PageCache(str(tmp_path / 'pages.json'))
    cache.store('old', [{'id': 'a', 'name': 'x' * 100}], now=1)
    cache.store('mid', [{'id': 'b', 'name': 'x' * 100}], now=2)
    cache.store('new', [{'id': 'c', 'name': 'x' * 100}], now=3)
    assert cache.lookup('new', now=3)[0] == 'fresh'
    assert cache.lookup('old', now=3) == ('miss', None)


def test_concurrent_saves_can_create_the_same_directory(tmp_path):
    import threading

    path = tmp_path / 'shared' / 'pages.json'
    caches = [PageCache(str(path)) for _ in range(8)]
    barrier = threading.Barrier(len(caches), timeout=2)
    errors = []

    def save(cache):
        try:
            barrier.wait()
            cache.save()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(cache,)) for cache in caches]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert json.loads(path.read_text()) == {'entries': {}}
