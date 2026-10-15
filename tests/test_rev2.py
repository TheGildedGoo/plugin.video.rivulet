# SPDX-FileCopyrightText: 2026 M0RF30
# SPDX-License-Identifier: MIT
"""Rev2Rivulet stays beside RevRivulet, and its posters are not the oval mask."""
import re
import struct
import zipfile
from pathlib import Path

import pytest

from lib.ui.rev2 import REV2_ID, is_rev2
from lib.ui.rev2.keyboard import CLEAR_BUTTON, HISTORY_LIST, QUERY_LABEL, button_map, row_ids
from lib.ui.rev2.rank import Prefs, parse, score
from lib.ui.rev2.rows import keep_library, peek_for, visible_rows
from lib.ui.rev2.skin import skin_for

_ROOT = Path(__file__).resolve().parents[1]
_SKIN = _ROOT / 'resources' / 'skins' / 'Default' / '1080i'
_MEDIA = _ROOT / 'resources' / 'skins' / 'Default' / 'media'
_PNG = b'\x89PNG\r\n\x1a\n'


def test_source_tree_is_revrivulet_not_the_variant():
    assert is_rev2() is False
    assert skin_for('HomeWindow.xml') == 'HomeWindow.xml'
    assert skin_for('StreamsWindow.xml') == 'StreamsWindow.xml'


def test_variant_id_selects_the_rev2_skin(monkeypatch):
    monkeypatch.setattr('lib.addonid.ADDON_ID', REV2_ID)
    assert is_rev2() is True
    assert skin_for('HomeWindow.xml') == 'Rev2HomeWindow.xml'
    assert skin_for('Rev2HomeWindow.xml') == 'Rev2HomeWindow.xml'


def test_every_revrivulet_window_has_a_rev2_skin():
    missing = []
    for path in sorted(_SKIN.glob('*.xml')):
        if path.name.startswith('Rev2'):
            continue
        if not (_SKIN / ('Rev2' + path.name)).is_file():
            missing.append(path.name)
    assert not missing


def test_rev2_art_is_a_full_opacity_rounded_rect_mask():
    """The oval was a square mask stretched over a tall poster, with a grey plate behind it."""
    offenders = []
    for path in _SKIN.glob('Rev2*.xml'):
        text = path.read_text(encoding='utf-8')
        if 'round_mask.png' in text or 'round_fill.png' in text or 'round_frame.png' in text:
            offenders.append('%s still uses the oval mask' % path.name)
        for tag in re.findall(r'<texture\b[^>]*>', text):
            # ``colordiffuse`` contains the letters "diffuse"; only a real
            # diffuse mask attribute is the oval bug.
            if re.search(r'(^|\s)diffuse=', tag) and (
                'border=' in tag or re.search(r'(^|\s)colordiffuse=', tag)
            ):
                offenders.append('%s diffuse is sliced or tinted: %s' % (path.name, tag))
    assert not offenders


def _png_size(path):
    with open(path, 'rb') as handle:
        assert handle.read(8) == _PNG
        handle.read(4)
        assert handle.read(4) == b'IHDR'
        return struct.unpack('>II', handle.read(8))


def test_mask_files_match_the_control_they_are_named_for():
    masks = list(_MEDIA.glob('rv_mask_*.png'))
    assert masks
    for path in masks:
        width, height = (int(part) for part in path.stem.replace('rv_mask_', '').split('x'))
        assert _png_size(path) == (width, height)
        assert min(width, height) > 48


def test_mask_pixels_are_a_rounded_rectangle_when_pillow_is_installed():
    pytest.importorskip('PIL')
    from PIL import Image

    for path in _MEDIA.glob('rv_mask_*.png'):
        image = Image.open(path).convert('RGBA')
        width, height = image.size
        pixels = image.load()
        assert pixels[width // 2, height // 2] == (255, 255, 255, 255)
        assert pixels[0, 0][3] < 16
        assert pixels[width // 2, 0][3] > 250
        assert pixels[0, height // 2][3] > 250
        empty = sum(1 for y in range(height) for x in range(width) if pixels[x, y][3] < 16)
        assert empty / float(width * height) < 0.05


def test_keyboard_ids_are_the_ones_the_sheet_declares():
    text = (_SKIN / 'Rev2SearchSheet.xml').read_text(encoding='utf-8')
    for control_id in button_map():
        assert 'id="%d"' % control_id in text
    for control_id in row_ids():
        assert 'id="%d"' % control_id in text
    assert 'id="%d"' % QUERY_LABEL in text
    assert 'id="%d"' % HISTORY_LIST in text
    assert 'id="%d"' % CLEAR_BUTTON in text


def test_rows_drop_empty_bands_and_peek_the_next_one():
    rows = visible_rows([
        ('empty', 'Empty', []),
        ('movies', 'Movies', [{'id': 'a'}, {'id': 'b'}]),
        ('series', 'Series', [{'id': 'c'}]),
    ])
    assert [key for key, _title, _items in rows] == ['movies', 'series']
    assert peek_for(rows, 0, True)[0] == 'Series'
    assert peek_for(rows, 0, False) == ('', [])
    assert keep_library([{'action': 'signin'}, {'name': 'notice'}, {'sid': 'tt1'}]) == [
        {'action': 'signin'}, {'sid': 'tt1'},
    ]


def test_rank_prefers_a_cached_playable_stream_over_a_cam():
    cached = score(parse({'name': '1080p', 'title': '[RD+]'}, 'addon'), Prefs())
    cam = score(parse({'name': '2160p CAM', 'title': '4K'}, 'addon'), Prefs())
    assert cached.score > cam.score


def test_publish_builds_rev2_beside_revrivulet_without_rewriting_the_tree(tmp_path):
    from scripts.publish_repo import REV2_ID as PUBLISHED_ID
    from scripts.publish_repo import build_repo

    addon_before = (_ROOT / 'addon.xml').read_text(encoding='utf-8')
    output = build_repo(tmp_path / 'repo')
    assert (_ROOT / 'addon.xml').read_text(encoding='utf-8') == addon_before
    root = __import__('xml.etree.ElementTree', fromlist=['ElementTree']).parse(
        str(output / 'addons.xml')
    ).getroot()
    ids = [addon.get('id') for addon in root.findall('addon')]
    assert 'plugin.video.revrivulet' in ids
    assert PUBLISHED_ID in ids
    rev2 = root.find("addon[@id='%s']" % PUBLISHED_ID)
    assert rev2.get('version') == '0.1.0.r2.1'
    assert rev2.get('name') == 'Rev2Rivulet'
    zip_path = output / PUBLISHED_ID / ('%s-0.1.0.r2.1.zip' % PUBLISHED_ID)
    with zipfile.ZipFile(str(zip_path)) as zf:
        addon_py = zf.read('%s/lib/addonid.py' % PUBLISHED_ID).decode('utf-8')
        home = zf.read('%s/resources/skins/Default/1080i/Rev2HomeWindow.xml' % PUBLISHED_ID).decode('utf-8')
    assert 'ADDON_ID = "%s"' % PUBLISHED_ID in addon_py
    assert 'round_mask.png' not in home
    assert 'rv_mask_200x300.png' in home
    plain = zipfile.ZipFile(str(output / 'plugin.video.revrivulet.zip'))
    assert 'plugin.video.revrivulet' in plain.read('plugin.video.revrivulet/addon.xml').decode('utf-8')
    assert PUBLISHED_ID not in plain.read('plugin.video.revrivulet/lib/addonid.py').decode('utf-8')


def test_search_sheet_appends_a_letter_and_settings_toggle_a_bool():
    from tests.kodistubs import install_kodi_stubs

    with install_kodi_stubs(reload=(
        'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.rev2.search', 'lib.ui.rev2.settings',
    )) as ctx:
        sheet = ctx.search.SearchSheet('Rev2SearchSheet.xml', '/addon', 'Default', '1080i')
        letter = min(button_map())
        sheet.onClick(letter)
        assert sheet.query == button_map()[letter]
        assert sheet.getControl(QUERY_LABEL).label == sheet.query

        window = ctx.settings.SettingsWindow('Rev2SettingsWindow.xml', '/addon', 'Default', '1080i')
        window.onInit()
        window.onClick(ctx.settings.OPTIONS)
        assert ctx.env.addon.getSetting('home_show_mystuff') == 'false'
