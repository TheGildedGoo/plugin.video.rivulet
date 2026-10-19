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
