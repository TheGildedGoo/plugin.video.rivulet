# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""First catalog page through the slim cache (#13)."""
import contextlib

import pytest

from tests.kodistubs import install_kodi_stubs


@pytest.fixture
def pages():
    with contextlib.ExitStack() as stack:
        ctx = stack.enter_context(install_kodi_stubs(reload=(
            'lib.ui.compat', 'lib.ui.views', 'lib.ui.catalogpages',
        )))
        yield ctx


def _cache(tmp_path, clock):
    from lib.stremio.pagecache import PageCache

    return PageCache(str(tmp_path / 'catalog_pages.json'), clock=lambda: clock['now'])


def test_an_expired_page_paints_and_is_revalidated(pages, tmp_path, monkeypatch):
    module = pages.catalogpages
    clock = {'now': 0.0}
    cache = _cache(tmp_path, clock)
    catalog = {'type': 'movie', 'id': 'top'}
    from lib.stremio.pagecache import cache_key

    key = cache_key('t', 'movie', 'top', None)
    cache.store(key, [{'id': 'tt1', 'type': 'movie', 'name': 'One'}], {'cacheMaxAge': 1, 'staleRevalidate': 1, 'staleError': 1})
    clock['now'] = 3600.0
    monkeypatch.setattr(module, 'get_page_cache', lambda: cache)
    fetched = []
    monkeypatch.setattr(module, '_fetch_first_page', lambda *args: fetched.append(args) or ([], {}))
    revalidated = []
    monkeypatch.setattr(module, '_schedule_revalidate', lambda *args: revalidated.append(args[-1]))

    metas = module.cached_first_page('t', {}, catalog)

    assert [meta['id'] for meta in metas] == ['tt1']
    assert fetched == []
    assert revalidated == [key]


def test_deferred_saves_write_the_file_once(pages, tmp_path, monkeypatch):
    module = pages.catalogpages
    clock = {'now': 0.0}
    cache = _cache(tmp_path, clock)
    saves = []
    real_save = cache.save
    monkeypatch.setattr(cache, 'save', lambda: saves.append(1) or real_save())
    monkeypatch.setattr(module, 'get_page_cache', lambda: cache)
    monkeypatch.setattr(
        module, '_fetch_first_page',
        lambda transport, manifest, catalog, extra: ([{'id': catalog['id'], 'type': 'movie', 'name': 'x'}], {}),
    )

    with module.deferred_saves():
        for cid in ('a', 'b', 'c'):
            module.cached_first_page('t', {}, {'type': 'movie', 'id': cid})
        assert saves == []
    assert saves == [1]

    module.cached_first_page('t', {}, {'type': 'movie', 'id': 'd'})
    assert saves == [1, 1]


def test_a_cached_page_follows_the_current_hide_adult_setting(pages, tmp_path, monkeypatch):
    """Pages are stored as the addon sent them and filtered on the way
    out: a page cached while hide-adult was off loses its adult item as
    soon as the setting is turned on, without waiting for it to expire."""
    module = pages.catalogpages
    clock = {'now': 0.0}
    cache = _cache(tmp_path, clock)
    monkeypatch.setattr(module, 'get_page_cache', lambda: cache)
    page = [
        {'id': 'tt1', 'type': 'movie', 'name': 'Family Film'},
        {'id': 'tt2', 'type': 'movie', 'name': 'Late Night', 'adult': True},
    ]
    fetched = []
    monkeypatch.setattr(module, '_fetch_first_page', lambda *args: fetched.append(1) or ([dict(m) for m in page], {}))
    monkeypatch.setattr(module, '_schedule_revalidate', lambda *args: None)
    catalog = {'type': 'movie', 'id': 'top'}

    pages.env.addon.settings['home_hide_adult'] = 'false'
    shown = module.cached_first_page('t', {}, catalog)
    assert [meta['id'] for meta in shown] == ['tt1', 'tt2']

    pages.env.addon.settings['home_hide_adult'] = 'true'
    shown = module.cached_first_page('t', {}, catalog)
    assert [meta['id'] for meta in shown] == ['tt1']
    assert fetched == [1]  # the second read came from the cache

    from lib.stremio.pagecache import cache_key

    _state, stored = cache.lookup(cache_key('t', 'movie', 'top', None), allow_expired=True)
    assert [meta['id'] for meta in stored] == ['tt1', 'tt2']  # kept unfiltered on disk


class _DirStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir


def test_the_page_cache_lives_in_the_store_folder_and_is_shared(pages, tmp_path, monkeypatch):
    module = pages.catalogpages
    import lib.ui.dependencies as dependencies

    monkeypatch.setattr(dependencies, 'get_store', lambda: _DirStore(str(tmp_path)))
    module._caches.clear()
    first = module.get_page_cache()
    assert first.path == str(tmp_path / 'catalog_pages.json')
    assert module.get_page_cache() is first
    # A store with no folder (the test fakes) has no cache at all.
    monkeypatch.setattr(dependencies, 'get_store', lambda: _DirStore(''))
    assert module.get_page_cache() is None
    module._caches.clear()


def test_with_no_cache_every_call_fetches(pages, monkeypatch):
    module = pages.catalogpages
    monkeypatch.setattr(module, 'get_page_cache', lambda: None)
    fetched = []
    monkeypatch.setattr(module, '_fetch_first_page',
                        lambda *args: fetched.append(1) or ([{'id': 'tt1', 'type': 'movie'}], {}))
    assert module.cached_first_page('t', {}, {'type': 'movie', 'id': 'top'})[0]['id'] == 'tt1'
    module.cached_first_page('t', {}, {'type': 'movie', 'id': 'top'})
    assert fetched == [1, 1]


def test_a_fresh_page_is_served_without_a_fetch_and_gets_its_type(pages, tmp_path, monkeypatch):
    module = pages.catalogpages
    clock = {'now': 0.0}
    cache = _cache(tmp_path, clock)
    from lib.stremio.pagecache import cache_key

    cache.store(cache_key('t', 'series', 'top', None), [{'id': 'tt9', 'name': 'Typeless'}])
    monkeypatch.setattr(module, 'get_page_cache', lambda: cache)
    monkeypatch.setattr(module, '_fetch_first_page', lambda *args: pytest.fail('fetched a fresh page'))
    metas = module.cached_first_page('t', {}, {'type': 'series', 'id': 'top'})
    assert metas == [{'id': 'tt9', 'name': 'Typeless', 'type': 'series'}]


class _HintsClient:
    def __init__(self, metas, hints=None):
        self.calls = []
        self._metas = metas
        self._hints = hints or {}

    def catalog_with_hints(self, transport, ctype, cid, extra=None):
        self.calls.append((transport, ctype, cid, extra))
        return list(self._metas), dict(self._hints)


def test_fetch_uses_the_hints_call_and_keeps_adult_items_for_the_cache(pages, monkeypatch):
    module = pages.catalogpages
    import lib.ui.dependencies as dependencies

    client = _HintsClient([{'id': 'a', 'name': 'A'}, 'junk', {'id': 'b', 'adult': True}], {'cacheMaxAge': 60})
    monkeypatch.setattr(dependencies, 'get_client', lambda: client)
    pages.env.addon.settings['home_hide_adult'] = 'true'
    metas, hints = module._fetch_first_page('t', {}, {'type': 'movie', 'id': 'top'}, [('genre', 'x')])
    assert [meta['id'] for meta in metas] == ['a', 'b']  # stored unfiltered
    assert hints == {'cacheMaxAge': 60}
    assert client.calls == [('t', 'movie', 'top', [('genre', 'x')])]


def test_an_adult_catalog_is_not_requested_while_hidden(pages, monkeypatch):
    module = pages.catalogpages
    import lib.ui.dependencies as dependencies

    client = _HintsClient([{'id': 'a'}])
    monkeypatch.setattr(dependencies, 'get_client', lambda: client)
    adult = {'type': 'movie', 'id': 'xxx', 'name': 'Porn'}
    pages.env.addon.settings['home_hide_adult'] = 'true'
    assert module._fetch_first_page('t', {}, adult, None) == ([], {})
    assert client.calls == []
    pages.env.addon.settings['home_hide_adult'] = 'false'
    assert module._fetch_first_page('t', {}, adult, None)[0] == [{'id': 'a'}]


def test_a_client_without_hints_reads_the_first_page_of_the_catalog(pages, monkeypatch):
    module = pages.catalogpages
    import lib.ui.dependencies as dependencies

    monkeypatch.setattr(dependencies, 'get_client', lambda: object())
    seen = []

    def pages_of(transport, ctype, cid, extra=None, catalog=None, manifest=None):
        seen.append((ctype, cid))
        return iter([[{'id': 'a'}, None], [{'id': 'b'}]])

    monkeypatch.setattr(pages.views, 'iter_catalog_pages', pages_of)
    assert module._fetch_first_page('t', {}, {'type': 'movie', 'id': 'top'}, None) == ([{'id': 'a'}], {})
    monkeypatch.setattr(pages.views, 'iter_catalog_pages', lambda *a, **k: iter([]))
    assert module._fetch_first_page('t', {}, {'type': 'movie', 'id': 'top'}, None) == ([], {})
    assert seen == [('movie', 'top')]


def test_revalidate_stores_the_new_page_and_ignores_a_failure(pages, tmp_path, monkeypatch):
    module = pages.catalogpages
    cache = _cache(tmp_path, {'now': 0.0})
    monkeypatch.setattr(module, 'get_page_cache', lambda: cache)
    monkeypatch.setattr(module, '_fetch_first_page', lambda *args: ([{'id': 'new'}], {'cacheMaxAge': 5}))
    module._revalidate('t', {}, {'type': 'movie', 'id': 'top'}, None, 'key')
    assert cache.lookup('key', now=1) == ('fresh', [{'id': 'new'}])
    assert (tmp_path / 'catalog_pages.json').exists()

    def boom(*args):
        raise RuntimeError('addon down')

    monkeypatch.setattr(module, '_fetch_first_page', boom)
    module._revalidate('t', {}, {'type': 'movie', 'id': 'top'}, None, 'key')
    assert cache.lookup('key', now=1) == ('fresh', [{'id': 'new'}])
    # No cache to write to: the fetched page is dropped quietly.
    monkeypatch.setattr(module, '_fetch_first_page', lambda *args: ([{'id': 'other'}], {}))
    monkeypatch.setattr(module, 'get_page_cache', lambda: None)
    module._revalidate('t', {}, {'type': 'movie', 'id': 'top'}, None, 'key')


def test_one_revalidation_per_page_at_a_time(pages, monkeypatch):
    import threading

    module = pages.catalogpages
    gate = threading.Event()
    calls = []

    def slow(*args):
        calls.append(args[-1])
        gate.wait(2)

    monkeypatch.setattr(module, '_revalidate', slow)
    module._schedule_revalidate('t', {}, {}, None, 'k1')
    module._schedule_revalidate('t', {}, {}, None, 'k1')  # already in flight
    gate.set()
    deadline = __import__('time').monotonic() + 2
    while module._revalidate_inflight and __import__('time').monotonic() < deadline:
        gate.wait(0.01)
    assert calls == ['k1']
    assert 'k1' not in module._revalidate_inflight


def test_a_failed_deferred_save_does_not_escape(pages, tmp_path, monkeypatch):
    module = pages.catalogpages
    cache = _cache(tmp_path, {'now': 0.0})

    def broken():
        raise OSError('read-only')

    monkeypatch.setattr(cache, 'save', broken)
    monkeypatch.setattr(module, 'get_page_cache', lambda: cache)
    monkeypatch.setattr(module, '_fetch_first_page', lambda *args: ([{'id': 'a'}], {}))
    with module.deferred_saves():
        module.cached_first_page('t', {}, {'type': 'movie', 'id': 'top'})
    assert module._defer == {'depth': 0, 'dirty': False}
