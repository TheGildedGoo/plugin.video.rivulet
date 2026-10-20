"""Home intent survives catalog churn
    resolution stays deterministic."""
import itertools
import json
import os

import pytest

from lib import homelayout as h
from lib.store import Store


def addon(catalogs, aid='a', name='Addon'):
    return {'transportUrl': aid, 'manifest': {'id': aid, 'name': name, 'catalogs': catalogs}}


def catalog(cid='top', ctype='movie', name=None, **kwargs):
    return dict({'id': cid, 'type': ctype, 'name': name or cid}, **kwargs)


def empty():
    return {'version': 1, 'tabs': {tab: [] for tab in h.TABS}}


def test_default_and_normalization():
    assert h.default_layout() == h.DEFAULT
    layout = empty()
    layout['tabs']['home'] = ['library', 'continue:movie', 'library', 'continue',
                              'unknown', None, 'cat:missing|movie|saved', 'cat:a|channel|x']
    assert h.normalize(layout)['tabs']['home'] == ['continue:movie', 'library', 'cat:missing|movie|saved']
    assert h.DEFAULT['tabs']['home'] == ['continue', 'new:movie', 'new:series']


@pytest.mark.parametrize('value', [None, [], {}, {'version': True, 'tabs': {}},
    {'version': 2, 'tabs': {}}, {'version': 1, 'tabs': {'oops': []}},
    {'version': 1, 'tabs': dict.fromkeys(h.TABS, 'bad')}])
def test_bad_envelopes_are_rejected(value):
    with pytest.raises(h.LayoutError):
        h.normalize(value)


def test_new_rule_whole_words_and_installed_order():
    cats = h.installed_catalogs([addon([catalog('renew'), catalog('latest films'), catalog('new')]),
                                 addon([catalog('fresh')], 'b')])
    plan = h.resolve(h.default_layout(), 'home', cats)
    assert plan[1][0] == 'cat:a|movie|latest films'
    assert plan[1][4] == (30529,)
    fallback = h.installed_catalogs([addon([catalog('renew'), catalog('archive')])])
    assert h.resolve(h.DEFAULT, 'home', fallback)[1][0] == 'cat:a|movie|renew'
    layout = empty()
    layout['tabs']['home'] = ['new:movie', 'rest:movie', 'cat:a|movie|new']
    ids = [row[0] for row in h.resolve(layout, 'home', cats)]
    assert ids == ['cat:a|movie|latest films', 'cat:a|movie|renew', 'cat:a|movie|new', 'cat:b|movie|fresh']


def test_catalog_eligibility_and_anime_split():
    cats = h.installed_catalogs([addon([
        catalog('channel', 'channel'), catalog('plain', 'anime'),
        catalog('films', 'anime.movie'), catalog('shows', 'anime.series'),
        catalog('search', extra=[{'name': 'search', 'isRequired': True}]),
        catalog('genre', extraRequired=['genre']), catalog('skip', extraRequired=['skip']),
        catalog('adult', adult=True),
    ])])
    assert [row['kind'] for row in cats] == ['anime-movie', 'anime-series', 'anime-movie', 'anime-series', 'movie']
    assert cats[0]['list_id'].endswith('|movie') and cats[1]['list_id'].endswith('|series')
    assert h.matches_catalog({'type': 'movie'}, 'movie')
    assert not h.matches_catalog({'type': 'anime.movie'}, 'movie')
    assert h.matches_catalog({'type': 'anime'}, 'series')
    assert h.matches_catalog({}, '')
    unhidden = h.installed_catalogs([addon([catalog('adult', adult=True)])], False)
    assert len(unhidden) == 1
    assert h.resolve({'version': 1, 'tabs': dict(empty()['tabs'], home=['new:movie'])}, 'home', unhidden) == []


@pytest.mark.parametrize('ctype,sid,variant', [('movie','tt1','movie'), ('tv','tt2','series'),
    ('series','tt3','series'), ('anime.movie','a','anime'), ('movie','kitsu:1','anime')])
def test_continue_anime_precedence(ctype, sid, variant):
    meta = {'type': ctype, 'id': sid}
    assert h.matches_continue(meta)
    assert [v for v in ('movie', 'series', 'anime') if h.matches_continue(meta, v)] == [variant]


@pytest.mark.parametrize('ctype,variant', [('movie','movie'), ('anime.movie','movie'),
    ('tv','series'), ('series','series'), ('anime','series'), ('anime.series','series')])
def test_library_split(ctype, variant):
    assert h.matches_library({'type': ctype})
    assert h.matches_library({'type': ctype}, variant)
    assert not h.matches_library({'type': ctype}, 'movie' if variant == 'series' else 'series')


@pytest.mark.parametrize('flags', list(itertools.product((False, True), repeat=4)))
def test_all_toggle_migrations(flags):
    keys = ('home_show_mystuff', 'home_show_movies', 'home_show_series', 'home_show_anime')
    layout = h.migrate(dict(zip(keys, flags)))
    rows = sum(layout['tabs'].values(), [])
    assert ('continue' in rows) is flags[0]
    assert ('new:movie' in rows) is flags[1]
    assert ('new:series' in rows) is flags[2]
    assert ('new:anime-movie' in rows) is flags[3]
    assert ('continue:movie' in rows) is (flags[0] and flags[1])
    assert ('continue:series' in rows) is (flags[0] and flags[2])
    assert ('continue:anime' in rows) is (flags[0] and flags[3])
    assert layout['tabs']['mystuff'] == ['library:movie', 'library:series']


def test_editing_materializes_and_preserves_missing_addons():
    cats = h.installed_catalogs([addon([catalog('top'), catalog('latest'), catalog('third')])])
    layout = empty()
    layout['tabs']['home'] = ['continue', 'new:movie', 'rest:movie', 'cat:missing|movie|saved']
    layout = h.materialize(layout, 'home', cats)
    assert layout['tabs']['home'] == ['continue', 'cat:a|movie|latest', 'cat:a|movie|top', 'cat:a|movie|third', 'cat:missing|movie|saved']
    assert len(h.resolve(layout, 'home', cats)) == 4
    assert h.move(layout, 'home', 'continue', 1) == layout
    assert h.move(layout, 'home', 'cat:a|movie|latest', -1) == layout
    moved = h.move(layout, 'home', 'cat:a|movie|latest', 1)
    assert moved['tabs']['home'][1:3] == ['cat:a|movie|top', 'cat:a|movie|latest']
    assert h.move(moved, 'home', 'cat:a|movie|latest', -1) == layout
    moved = h.remove(moved, 'home', 'cat:a|movie|latest')
    assert 'cat:a|movie|latest' not in moved['tabs']['home']
    multi, changed = h.add(moved, 'mystuff', 'cat:a|movie|top')
    assert changed and 'cat:a|movie|top' in multi['tabs']['home'] and 'cat:a|movie|top' in multi['tabs']['mystuff']
    assert not h.add(multi, 'mystuff', 'cat:a|movie|top')[1]
    assert not h.add(multi, 'home', 'continue:anime')[1]
    assert h.add(multi, 'home', 'continue:anime', True)[0]['tabs']['home'][0] == 'continue:anime'
    assert h.reset() == h.DEFAULT


def test_row_cap_and_disambiguated_headings():
    cats = h.installed_catalogs([addon([catalog(str(i), name='Same') for i in range(14)]),
                                 addon([catalog('anime', 'anime', 'Same')], 'b', 'Second')])
    layout = empty()
    layout['tabs']['home'] = ['continue'] + [c['list_id'] for c in cats]
    plan = h.resolve(layout, 'home', cats)
    assert len(plan) == 13
    assert plan[1][4] == ('Same', 'Addon')
    assert not h.add(layout, 'home', 'library')[1]
    layout['tabs']['home'] = [cats[-1]['list_id']]
    parts = h.resolve(layout, 'home', cats)[0][4]
    assert parts == ('Same', 30536)
    assert h.heading_text(parts, lambda n: str(n)) == 'Same · 30536'
    assert h.move(layout, 'home', 'missing', -1) == layout
    assert not h.add(layout, 'home', 'invalid')[1]


@pytest.mark.parametrize('payload', ['{bad', '[]', '{}', '{"version":2,"tabs":{}}',
    json.dumps({'version': 1, 'tabs': dict.fromkeys(h.TABS, False)})])
def test_corrupt_files_reset_and_log_safely(tmp_path, payload, caplog):
    store = Store(str(tmp_path))
    (tmp_path / 'home_layout.json').write_text(payload)
    assert store.get_home_layout() == h.DEFAULT
    assert 'LayoutError' in caplog.text


def test_persistence_bypasses_cached_reads_and_same_size_rewrites(tmp_path, monkeypatch, caplog):
    first, second = Store(str(tmp_path)), Store(str(tmp_path))
    assert first.get_home_layout() == h.DEFAULT
    layout = empty()
    layout['tabs']['home'] = ['cat:a|movie|one']
    first.set_home_layout(layout)
    path = tmp_path / 'home_layout.json'
    stamp = path.stat().st_mtime_ns
    assert first.get_home_layout() == layout
    layout['tabs']['home'] = ['cat:a|movie|two']
    before_size = path.stat().st_size
    second.set_home_layout(layout)
    assert path.stat().st_size == before_size
    os.utime(str(path), ns=(stamp, stamp))
    monkeypatch.setattr(first, '_cached_read', lambda *args: pytest.fail('layout must read fresh'))
    assert first.get_home_layout() == layout
    assert first.set_home_layout({'bad': 'https://user:secret@host'}) == h.DEFAULT
    assert 'secret' not in caplog.text
