# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Hide titles by production country or original language.

Catalog rows carry this on the meta when the addon knows it. Cinemeta
sends ``country`` ("India", "United States, Canada") and, less often,
``language`` ("Hindi"). TMDB-shaped addons send the same facts as ISO
codes or as ``original_language``. A title with none of those fields
stays visible: guessing from the plot would hide the wrong films.

The tokens are what Settings stores. ``c:in`` is a country, ``l:hi`` is
a language, so India's code cannot collide with Indonesian.
"""
import re

#: What a fresh install hides: nothing. The filter only acts once the
#: user ticks a country or a language in Settings. A co-production that
#: lists a hidden country among its countries is hidden too.
DEFAULT_EXCLUDE = ()

# token, name shown in the checklist, extra spellings addons actually send.
# The name itself is always accepted. Matching is the whole country or
# language, never a substring, so "Indiana" is not India.
_COUNTRY_ROWS = (
    ('c:ar', 'Argentina', ('ar', 'arg')),
    ('c:au', 'Australia', ('au', 'aus')),
    ('c:at', 'Austria', ('at', 'aut')),
    ('c:bd', 'Bangladesh', ('bd', 'bgd')),
    ('c:be', 'Belgium', ('be', 'bel')),
    ('c:br', 'Brazil', ('br', 'bra')),
    ('c:ca', 'Canada', ('ca', 'can')),
    ('c:cn', 'China', ('cn', 'chn', 'prc')),
    ('c:co', 'Colombia', ('co', 'col')),
    ('c:cz', 'Czech Republic', ('cz', 'cze', 'czechia')),
    ('c:dk', 'Denmark', ('dk', 'dnk')),
    ('c:eg', 'Egypt', ('eg', 'egy')),
    ('c:fi', 'Finland', ('fi', 'fin')),
    ('c:fr', 'France', ('fr', 'fra')),
    ('c:de', 'Germany', ('de', 'deu', 'ger')),
    ('c:gr', 'Greece', ('gr', 'grc')),
    ('c:hk', 'Hong Kong', ('hk', 'hkg')),
    ('c:hu', 'Hungary', ('hu', 'hun')),
    ('c:in', 'India', ('in', 'ind')),
    ('c:id', 'Indonesia', ('id', 'idn')),
    ('c:ir', 'Iran', ('ir', 'irn')),
    ('c:ie', 'Ireland', ('ie', 'irl')),
    ('c:il', 'Israel', ('il', 'isr')),
    ('c:it', 'Italy', ('it', 'ita')),
    ('c:jp', 'Japan', ('jp', 'jpn')),
    ('c:mx', 'Mexico', ('mx', 'mex')),
    ('c:nl', 'Netherlands', ('nl', 'nld', 'holland', 'the netherlands')),
    ('c:nz', 'New Zealand', ('nz', 'nzl')),
    ('c:ng', 'Nigeria', ('ng', 'nga')),
    ('c:no', 'Norway', ('no', 'nor')),
    ('c:pk', 'Pakistan', ('pk', 'pak')),
    ('c:ph', 'Philippines', ('ph', 'phl')),
    ('c:pl', 'Poland', ('pl', 'pol')),
    ('c:pt', 'Portugal', ('pt', 'prt')),
    ('c:ro', 'Romania', ('ro', 'rou')),
    ('c:ru', 'Russia', ('ru', 'rus', 'russian federation')),
    ('c:sa', 'Saudi Arabia', ('sa', 'sau')),
    ('c:za', 'South Africa', ('za', 'zaf')),
    ('c:kr', 'South Korea', ('kr', 'kor', 'korea', 'republic of korea')),
    ('c:es', 'Spain', ('es', 'esp')),
    ('c:se', 'Sweden', ('se', 'swe')),
    ('c:ch', 'Switzerland', ('ch', 'che')),
    ('c:tw', 'Taiwan', ('tw', 'twn')),
    ('c:th', 'Thailand', ('th', 'tha')),
    ('c:tr', 'Turkey', ('tr', 'tur', 'turkiye')),
    ('c:ae', 'United Arab Emirates', ('ae', 'are', 'uae')),
    ('c:gb', 'United Kingdom', ('gb', 'gbr', 'uk', 'great britain', 'britain', 'england')),
    ('c:us', 'United States', ('us', 'usa', 'u.s.', 'u.s.a.')),
)

_LANGUAGE_ROWS = (
    ('l:ar', 'Arabic', ('ar', 'ara')),
    ('l:bn', 'Bengali', ('bn', 'ben')),
    ('l:zh', 'Chinese', ('zh', 'zho', 'chi', 'mandarin')),
    ('l:da', 'Danish', ('da', 'dan')),
    ('l:nl', 'Dutch', ('nl', 'nld', 'dut')),
    ('l:en', 'English', ('en', 'eng')),
    ('l:fi', 'Finnish', ('fi', 'fin')),
    ('l:fr', 'French', ('fr', 'fra', 'fre')),
    ('l:de', 'German', ('de', 'deu', 'ger')),
    ('l:el', 'Greek', ('el', 'ell', 'gre')),
    ('l:gu', 'Gujarati', ('gu', 'guj')),
    ('l:he', 'Hebrew', ('he', 'heb')),
    ('l:hi', 'Hindi', ('hi', 'hin')),
    ('l:id', 'Indonesian', ('id', 'ind')),
    ('l:it', 'Italian', ('it', 'ita')),
    ('l:ja', 'Japanese', ('ja', 'jpn')),
    ('l:kn', 'Kannada', ('kn', 'kan')),
    ('l:ko', 'Korean', ('ko', 'kor')),
    ('l:ml', 'Malayalam', ('ml', 'mal')),
    ('l:mr', 'Marathi', ('mr', 'mar')),
    ('l:no', 'Norwegian', ('no', 'nor')),
    ('l:fa', 'Persian', ('fa', 'fas', 'per')),
    ('l:pl', 'Polish', ('pl', 'pol')),
    ('l:pt', 'Portuguese', ('pt', 'por')),
    ('l:pa', 'Punjabi', ('pa', 'pan')),
    ('l:ro', 'Romanian', ('ro', 'ron', 'rum')),
    ('l:ru', 'Russian', ('ru', 'rus')),
    ('l:es', 'Spanish', ('es', 'spa')),
    ('l:sv', 'Swedish', ('sv', 'swe')),
    ('l:ta', 'Tamil', ('ta', 'tam')),
    ('l:te', 'Telugu', ('te', 'tel')),
    ('l:th', 'Thai', ('th', 'tha')),
    ('l:tr', 'Turkish', ('tr', 'tur')),
    ('l:uk', 'Ukrainian', ('uk', 'ukr')),
    ('l:ur', 'Urdu', ('ur', 'urd')),
    ('l:vi', 'Vietnamese', ('vi', 'vie')),
)

_COUNTRY_FIELDS = (
    'country', 'countries', 'origin_country', 'originCountry',
    'production_countries', 'productionCountries',
)
_LANGUAGE_FIELDS = (
    'language', 'originalLanguage', 'original_language', 'originalLang',
)
_SPLIT = re.compile(r'\s+and\s+|[,;/|]+', re.IGNORECASE)

_KNOWN = frozenset(token for token, _name, _aliases in _COUNTRY_ROWS + _LANGUAGE_ROWS)


def _choices(rows):
    """``(token, name)`` in checklist order."""
    return tuple(sorted(
        ((token, name) for token, name, _aliases in rows),
        key=lambda item: item[1].lower(),
    ))


COUNTRIES = _choices(_COUNTRY_ROWS)
LANGUAGES = _choices(_LANGUAGE_ROWS)


def _norm(text):
    return ' '.join(str(text).strip().lower().replace('.', '').split())


def _index(rows):
    table = {}
    for token, name, aliases in rows:
        keys = [name]
        keys.extend(aliases)
        code = token.split(':', 1)[1]
        keys.append(code)
        for key in keys:
            table[_norm(key)] = token
    return table


_COUNTRY_INDEX = _index(_COUNTRY_ROWS)
_LANGUAGE_INDEX = _index(_LANGUAGE_ROWS)
_NAMES = dict(COUNTRIES + LANGUAGES)


def _parts(value):
    """One country or language claim, split into whole names.

    A list, a comma-separated string, and a TMDB object
    (``iso_3166_1`` / ``iso_639_1`` / ``name``) all become the same
    shape. A bool is not a code.
    """
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, dict):
        pieces = []
        for key in ('iso_3166_1', 'iso_639_1', 'name', 'english_name'):
            pieces.extend(_parts(value.get(key)))
        return pieces
    if isinstance(value, (list, tuple)):
        pieces = []
        for item in value:
            pieces.extend(_parts(item))
        return pieces
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in _SPLIT.split(text) if part.strip()]


def _tokens_from(value, index):
    found = set()
    for part in _parts(value):
        token = index.get(_norm(part))
        if token:
            found.add(token)
    return found


def signals(meta):
    """Country and original-language tokens this meta actually states.

    Empty means the addon did not say. Callers keep that title.
    """
    if not isinstance(meta, dict):
        return frozenset()
    found = set()
    for key in _COUNTRY_FIELDS:
        if key in meta:
            found.update(_tokens_from(meta.get(key), _COUNTRY_INDEX))
    for key in _LANGUAGE_FIELDS:
        if key in meta:
            found.update(_tokens_from(meta.get(key), _LANGUAGE_INDEX))
    links = meta.get('links')
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            category = str(link.get('category') or '').strip().lower()
            name = link.get('name')
            if category in ('country', 'countries'):
                found.update(_tokens_from(name, _COUNTRY_INDEX))
            elif category in ('language', 'original language', 'originallanguage'):
                found.update(_tokens_from(name, _LANGUAGE_INDEX))
    return frozenset(found)


def is_excluded(meta, excluded):
    """True only when a stated country or language is one the user hid.

    No statement, or a statement we cannot read, stays visible.
    """
    if not excluded:
        return False
    found = signals(meta)
    if not found:
        return False
    return bool(found.intersection(excluded))


def filter_metas(metas, excluded):
    """``metas`` without the hidden titles, in the same order.

    ``excluded`` empty is the list unchanged, including its identity,
    so a caller that has not configured the filter pays nothing.
    """
    if not excluded or not metas:
        return metas
    return [meta for meta in metas if not is_excluded(meta, excluded)]


def parse_exclude(raw):
    """Tokens from the setting string. Unknown tokens are dropped."""
    found = []
    seen = set()
    for part in str(raw or '').split(','):
        token = part.strip().lower()
        if token in _KNOWN and token not in seen:
            seen.add(token)
            found.append(token)
    return frozenset(found)


def format_exclude(tokens):
    """The setting string. Order is stable so a save does not churn."""
    return ','.join(sorted(token for token in tokens if token in _KNOWN))


def names_for(tokens):
    """Checklist names for a summary line, alphabetical."""
    names = [_NAMES[token] for token in tokens if token in _NAMES]
    names.sort(key=lambda name: name.lower())
    return names


def replace_group(current, choices, picked):
    """``current`` with this checklist's tokens replaced by ``picked``.

    Indexes that are not rows are ignored. The other group's tokens
    stay, so confirming Countries does not clear Languages.
    """
    group = frozenset(token for token, _name in choices)
    chosen = set()
    for index in picked or []:
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if index < 0 or index >= len(choices):
            continue
        chosen.add(choices[index][0])
    kept = set(token for token in current if token not in group)
    return format_exclude(kept.union(chosen))
