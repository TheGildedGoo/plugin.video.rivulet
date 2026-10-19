# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Country and original-language exclusion.

The match lives in lib.stremio.regionfilter, which has no Kodi imports.
The checklist is a remote multi-select: confirming one group rewrites
only that group's tokens.
"""
import xml.etree.ElementTree as ET

from lib.stremio.regionfilter import (
    COUNTRIES,
    DEFAULT_EXCLUDE,
    LANGUAGES,
    filter_metas,
    format_exclude,
    is_excluded,
    parse_exclude,
    replace_group,
    signals,
)

_ROOT_SETTINGS = 'resources/settings.xml'


def test_the_setting_default_hides_nothing():
    root = ET.parse(_ROOT_SETTINGS).getroot()
    setting = root.find(".//setting[@id='content_exclude']")
    default = (setting.findtext('default') or '').strip()
    assert default == format_exclude(DEFAULT_EXCLUDE) == ''
    assert parse_exclude(default) == frozenset()
    button = root.find(".//setting[@id='content_exclude_edit']")
    assert button.get('type') == 'action'
    assert 'action=content_exclude' in button.findtext('data')


def test_stated_country_or_language_is_hidden_and_unknown_stays():
    excluded = parse_exclude('c:in,l:hi,l:kn,l:ml,l:ta,l:te')
    metas = [
        {'id': 'us', 'country': 'United States'},
        {'id': 'in', 'country': 'India'},
        {'id': 'mix', 'country': 'United States, India'},
        {'id': 'usa', 'country': 'USA'},
        {'id': 'hi', 'country': 'United Kingdom', 'language': 'Hindi'},
        {'id': 'code', 'language': 'hi'},
        {'id': 'ta', 'original_language': 'ta'},
        {'id': 'te', 'originalLanguage': 'Telugu'},
        {'id': 'bare'},
        {'id': 'odd', 'country': 'Narnia'},
        {'id': 'indiana', 'country': 'Indiana'},
        {'id': 'tmdb', 'production_countries': [{'iso_3166_1': 'IN', 'name': 'India'}]},
        {'id': 'link', 'links': [{'category': 'Language', 'name': 'Kannada'}]},
        {'id': 'genre', 'links': [{'category': 'Genres', 'name': 'India'}]},
    ]
    kept = [meta['id'] for meta in filter_metas(metas, excluded)]
    assert kept == ['us', 'usa', 'bare', 'odd', 'indiana', 'genre']
    assert signals({'country': 'India'}) == frozenset({'c:in'})
    assert not is_excluded({'id': 'bare'}, excluded)


def test_an_empty_list_hides_nothing():
    metas = [{'id': 'in', 'country': 'India'}]
    assert filter_metas(metas, frozenset()) is metas
    assert parse_exclude('') == frozenset()
    assert parse_exclude('nope,c:in') == frozenset({'c:in'})


def test_confirming_one_group_leaves_the_other_group():
    current = parse_exclude('c:in,l:hi,l:ta')
    cleared = replace_group(current, COUNTRIES, [])
    assert parse_exclude(cleared) == frozenset({'l:hi', 'l:ta'})
    us = next(index for index, (token, _name) in enumerate(COUNTRIES) if token == 'c:us')
    saved = replace_group(current, COUNTRIES, [us])
    assert parse_exclude(saved) == frozenset({'c:us', 'l:hi', 'l:ta'})
    assert any(token == 'l:hi' for token, _name in LANGUAGES)


def test_confirming_the_country_list_saves_it(monkeypatch):
    from tests.kodistubs import install_kodi_stubs

    with install_kodi_stubs(
        reload=('lib.ui.compat', 'lib.ui.regiondialog'),
        settings={'content_exclude': 'c:in,l:hi,l:ta'},
        localized={30470: 'Hide', 30471: 'Countries', 30472: 'Languages'},
    ) as ctx:
        monkeypatch.setattr('lib.ui.dialogs.choose', lambda heading, rows: 0)
        us = next(index for index, (token, _name) in enumerate(COUNTRIES) if token == 'c:us')
        ctx.env.multiselect_answers.append([us])
        ctx.regiondialog.edit_exclusions()
        saved = set(ctx.env.addon.getSetting('content_exclude').split(','))
        assert saved == {'c:us', 'l:hi', 'l:ta'}
        heading, _options, preselect = ctx.env.dialog_multiselects[0]
        assert heading == 'Countries'
        india = next(index for index, (token, _name) in enumerate(COUNTRIES) if token == 'c:in')
        assert india in preselect


def test_backing_out_of_the_checklist_does_not_save(monkeypatch):
    from tests.kodistubs import install_kodi_stubs

    with install_kodi_stubs(
        reload=('lib.ui.compat', 'lib.ui.regiondialog'),
        settings={'content_exclude': 'c:in,l:hi'},
        localized={30470: 'Hide', 30471: 'Countries', 30472: 'Languages'},
    ) as ctx:
        monkeypatch.setattr('lib.ui.dialogs.choose', lambda heading, rows: -1)
        ctx.regiondialog.edit_exclusions()
        assert ctx.env.addon.getSetting('content_exclude') == 'c:in,l:hi'
        assert ctx.env.dialog_multiselects == []

        monkeypatch.setattr('lib.ui.dialogs.choose', lambda heading, rows: 1)
        ctx.env.multiselect_answers.append(None)
        ctx.regiondialog.edit_exclusions()
        assert ctx.env.addon.getSetting('content_exclude') == 'c:in,l:hi'


def test_apply_region_filter_reads_the_setting():
    from tests.kodistubs import install_kodi_stubs

    with install_kodi_stubs(
        reload=('lib.ui.compat', 'lib.ui.regiondialog'),
        settings={'content_exclude': 'c:in'},
    ) as ctx:
        metas = ctx.regiondialog.apply_region_filter([
            {'id': 'a', 'country': 'India'},
            {'id': 'b', 'country': 'France'},
            {'id': 'c'},
        ])
        assert [meta['id'] for meta in metas] == ['b', 'c']


def test_catalog_pages_and_search_results_go_through_the_filter():
    """The three places titles come in: catalog pages, search, discover links."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / 'lib' / 'ui'
    for name in ('views.py', 'searchwindow.py', 'infowindow.py'):
        assert 'apply_region_filter(' in (root / name).read_text(encoding='utf-8'), name


def test_an_empty_setting_leaves_catalog_pages_unchanged():
    from tests.kodistubs import install_kodi_stubs

    with install_kodi_stubs(reload=('lib.ui.compat', 'lib.ui.regiondialog'), settings={}) as ctx:
        metas = [{'id': 'a', 'country': 'India'}]
        assert ctx.regiondialog.apply_region_filter(metas) is metas
