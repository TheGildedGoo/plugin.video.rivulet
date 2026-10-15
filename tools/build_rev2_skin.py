# SPDX-FileCopyrightText: 2026 M0RF30
# SPDX-License-Identifier: MIT
"""Build the Rev2 skin from the RevRivulet windows and write its strings.

The Rev2 XML keeps every control id the Python already uses, and
replaces the poster mask. RevRivulet's ``round_mask.png`` is a 48px
square used with ``border="16"`` and a grey ``round_fill.png`` behind
the art. On a CoreELEC box that square stretches into a jagged grey
oval. The replacement is a full-opacity rounded rectangle drawn at the
control's own pixel size, with no plate behind it and no ``border`` on
the diffuse (a 9-slice border is what collapsed the straight edges).

Run from the repo root: ``python3 tools/build_rev2_skin.py``
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.make_textures import mask_filename, write_assets  # noqa: E402

SKIN = os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i')
LANG = os.path.join(ROOT, 'resources', 'language')
WORDMARK = '$ADDON[plugin.video.revrivulet 30432]'
IMAGE_RE = re.compile(r'<control type="image"(?P<attrs>[^>]*)>(?P<body>.*?)</control>', re.S)
MASKS = set()

#: Old near-black plates, retinted to the Rev2 background. Alpha stays.
COLORS = (
    ('FF07090B', 'FF0A0D12'),
    ('FF0A0C0E', 'FF0A0D12'),
    ('C70A0C0E', 'C70A0D12'),
    ('D60A0C0E', 'D60A0D12'),
    ('F70A0C0E', 'F70A0D12'),
    ('F207090B', 'F20A0D12'),
    ('5907090B', '590A0D12'),
)

STRINGS = (
    (30432, 'Rev2Rivulet'),
    (30433, 'Delete'),
    (30434, 'Space'),
    (30435, 'All settings'),
    (30436, 'On'),
    (30437, 'Off'),
)

# Short UI words. The brand is not translated.
TRANSLATIONS = {
    'fr_fr': {'Delete': 'Supprimer', 'Space': 'Espace', 'All settings': 'Tous les réglages', 'On': 'Activé', 'Off': 'Désactivé'},
    'de_de': {'Delete': 'Löschen', 'Space': 'Leerzeichen', 'All settings': 'Alle Einstellungen', 'On': 'Ein', 'Off': 'Aus'},
    'es_es': {'Delete': 'Eliminar', 'Space': 'Espacio', 'All settings': 'Todos los ajustes', 'On': 'Activado', 'Off': 'Desactivado'},
    'it_it': {'Delete': 'Elimina', 'Space': 'Spazio', 'All settings': 'Tutte le impostazioni', 'On': 'Attivo', 'Off': 'Disattivo'},
    'pt_br': {'Delete': 'Excluir', 'Space': 'Espaço', 'All settings': 'Todas as configurações', 'On': 'Ligado', 'Off': 'Desligado'},
    'nl_nl': {'Delete': 'Wissen', 'Space': 'Spatie', 'All settings': 'Alle instellingen', 'On': 'Aan', 'Off': 'Uit'},
    'pl_pl': {'Delete': 'Usuń', 'Space': 'Spacja', 'All settings': 'Wszystkie ustawienia', 'On': 'Wł.', 'Off': 'Wył.'},
    'ru_ru': {'Delete': 'Удалить', 'Space': 'Пробел', 'All settings': 'Все настройки', 'On': 'Вкл.', 'Off': 'Выкл.'},
    'tr_tr': {'Delete': 'Sil', 'Space': 'Boşluk', 'All settings': 'Tüm ayarlar', 'On': 'Açık', 'Off': 'Kapalı'},
    'ja_jp': {'Delete': '削除', 'Space': 'スペース', 'All settings': 'すべての設定', 'On': 'オン', 'Off': 'オフ'},
    'ko_kr': {'Delete': '삭제', 'Space': '스페이스', 'All settings': '모든 설정', 'On': '켜기', 'Off': '끄기'},
    'zh_cn': {'Delete': '删除', 'Space': '空格', 'All settings': '全部设置', 'On': '开', 'Off': '关'},
    'ar_sa': {'Delete': 'حذف', 'Space': 'مسافة', 'All settings': 'كل الإعدادات', 'On': 'تشغيل', 'Off': 'إيقاف'},
}


def _dim(body, name):
    match = re.search(r'<%s>(\d+)</%s>' % (name, name), body)
    return int(match.group(1)) if match else None


def _poster_aspect(width, height):
    if not height:
        return False
    ratio = width / float(height)
    return abs(ratio - (2.0 / 3.0)) < 0.04 or abs(ratio - (16.0 / 9.0)) < 0.04


def _retarget_masks(body, width, height):
    name = mask_filename(width, height)
    MASKS.add((width, height))

    def tex(match):
        tag = match.group(0)
        if 'round_mask.png' not in tag:
            return tag
        inner = re.search(r'>(.*)</texture>', tag, re.S).group(1)
        background = ' background="true"' if 'background=' in tag else ''
        return '<texture diffuse="%s"%s>%s</texture>' % (name, background, inner)

    return re.sub(r'<texture\b[^>]*>.*?</texture>', tex, body, flags=re.S)


def _rewrite_images(text):
    def repl(match):
        attrs = match.group('attrs')
        body = match.group('body')
        if 'round_fill.png' in body:
            # Grey plate behind the art. It is what shows around the oval.
            return ''
        if 'round_frame.png' in body:
            body = re.sub(
                r'<texture\b[^>]*>\s*round_frame\.png\s*</texture>',
                '<texture border="12" colordiffuse="FFFFFFFF">rv_focus_frame.png</texture>',
                body,
            )
        width = _dim(body, 'width')
        height = _dim(body, 'height')
        if 'round_mask.png' in body and width and height:
            body = _retarget_masks(body, width, height)
        elif (
            width and height and width <= 600 and _poster_aspect(width, height)
            and re.search(r'<texture\s*>\s*</texture>', body)
        ):
            name = mask_filename(width, height)
            MASKS.add((width, height))
            body = re.sub(
                r'<texture\s*>\s*</texture>',
                '<texture diffuse="%s" background="true"></texture>' % name,
                body,
                count=1,
            )
        return '<control type="image"%s>%s</control>' % (attrs, body)

    return IMAGE_RE.sub(repl, text)


def _recolor(text):
    for old, new in COLORS:
        text = text.replace('"%s"' % old, '"%s"' % new)
        text = text.replace('>%s<' % old, '>%s<' % new)
    return text.replace('RevRivulet', WORDMARK)


def transform(text):
    text = _rewrite_images(text)
    text = _recolor(text)
    note = (
        '    <!-- Rev2Rivulet. Art masks are full-opacity rounded rectangles\n'
        '         at the control size: no grey plate, no border on the diffuse. -->\n'
    )
    return text.replace('<window>', '<window>\n' + note, 1)


def build_windows():
    for name in sorted(os.listdir(SKIN)):
        if not name.endswith('.xml') or name.startswith('Rev2'):
            continue
        source = os.path.join(SKIN, name)
        with open(source, encoding='utf-8') as handle:
            text = handle.read()
        dest = os.path.join(SKIN, 'Rev2' + name)
        with open(dest, 'w', encoding='utf-8') as handle:
            handle.write(transform(text))
        print('wrote', dest)


def _button(control_id, key):
    width = 80
    if key == 'search':
        width = 240
    elif key in ('space', 'delete'):
        width = 180
    return (
        '<control type="button" id="%d"><width>%d</width><height>64</height>'
        '<font>font13</font><textcolor>FFEEF3F6</textcolor><focusedcolor>FF0A0D12</focusedcolor>'
        '<align>center</align><aligny>center</aligny>'
        '<texturefocus border="12" colordiffuse="FFFFFFFF">rv_key.png</texturefocus>'
        '<texturenofocus border="12" colordiffuse="14FFFFFF">rv_key.png</texturenofocus>'
        '<label></label></control>'
    ) % (control_id, width)


def write_search_sheet():
    from lib.ui.rev2.keyboard import FIRST_ROW, HISTORY_LIST, QUERY_LABEL, ROWS, button_map, row_ids

    buttons = button_map()
    # Group buttons back into rows by walking ROWS against the map order.
    ordered = list(buttons.items())
    cursor = 0
    rows_xml = []
    ids = row_ids()
    for index, row in enumerate(ROWS):
        chunk = ordered[cursor:cursor + len(row)]
        cursor += len(row)
        up = ids[index - 1] if index else HISTORY_LIST
        down = ids[index + 1] if index + 1 < len(ids) else HISTORY_LIST
        inner = ''.join(_button(control_id, key) for control_id, key in chunk)
        rows_xml.append(
            '<control type="grouplist" id="%d"><left>80</left><top>%d</top>'
            '<width>1760</width><height>72</height><orientation>horizontal</orientation>'
            '<itemgap>8</itemgap><align>left</align>'
            '<onleft>%d</onleft><onright>%d</onright><onup>%d</onup><ondown>%d</ondown>'
            '%s</control>'
            % (ids[index], 200 + index * 80, ids[index], ids[index], up, down, inner)
        )
    text = '''<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<window>
    <defaultcontrol>32200</defaultcontrol>
    <depth>0.52</depth>
    <coordinates><left>0</left><top>0</top></coordinates>
    <controls>
        <control type="group">
            <left>0</left><top>0</top>
            <visible>!Player.HasVideo</visible>
            <animation type="WindowOpen" reversible="false">
                <effect type="fade" delay="0" end="100" time="200" />
            </animation>
            <!-- No WindowClose animation on purpose: Kodi drops every action while the topmost modal plays one. -->
            <control type="image"><width>1920</width><height>1080</height><texture colordiffuse="FF0A0D12">white.png</texture></control>
            <control type="label"><left>80</left><top>48</top><width>600</width><height>48</height><font>font37</font><textcolor>FFEEF3F6</textcolor><aligny>center</aligny><label>%(word)s</label></control>
            <control type="label" id="%(query)d"><left>80</left><top>120</top><width>1760</width><height>64</height><font>font37</font><textcolor>FFFFFFFF</textcolor><aligny>center</aligny><label></label></control>
            %(rows)s
            <control type="list" id="%(history)d">
                <left>80</left><top>700</top><width>1760</width><height>72</height>
                <orientation>horizontal</orientation>
                <onleft>%(history)d</onleft><onright>%(history)d</onright>
                <onup>%(last)d</onup><ondown>32121</ondown>
                <scrolltime tween="cubic" easing="out">180</scrolltime>
                <itemlayout width="280" height="72">
                    <control type="image"><left>8</left><top>8</top><width>264</width><height>56</height><texture border="12" colordiffuse="14FFFFFF">rv_key.png</texture></control>
                    <control type="label"><left>8</left><top>8</top><width>264</width><height>56</height><font>font12</font><textcolor>FFEEF3F6</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label></control>
                </itemlayout>
                <focusedlayout width="280" height="72">
                    <control type="image"><left>8</left><top>8</top><width>264</width><height>56</height><texture border="12" colordiffuse="FFFFFFFF">rv_key.png</texture></control>
                    <control type="label"><left>8</left><top>8</top><width>264</width><height>56</height><font>font12</font><textcolor>FF0A0D12</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label></control>
                </focusedlayout>
            </control>
            <control type="button" id="32121">
                <left>80</left><top>800</top><width>360</width><height>64</height>
                <font>font13</font><textcolor>FFEEF3F6</textcolor><focusedcolor>FF0A0D12</focusedcolor>
                <align>center</align><aligny>center</aligny>
                <texturefocus border="12" colordiffuse="FFFFFFFF">rv_key.png</texturefocus>
                <texturenofocus border="12" colordiffuse="14FFFFFF">rv_key.png</texturenofocus>
                <label>$ADDON[plugin.video.revrivulet 30044]</label>
                <onup>%(history)d</onup><ondown>32121</ondown>
            </control>
        </control>
    </controls>
</window>
''' % {
        'word': WORDMARK,
        'query': QUERY_LABEL,
        'rows': '\n            '.join(rows_xml),
        'history': HISTORY_LIST,
        'last': FIRST_ROW + len(ROWS) - 1,
    }
    path = os.path.join(SKIN, 'Rev2SearchSheet.xml')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print('wrote', path)


def write_settings():
    def row(width):
        return (
            '<itemlayout height="72">'
            '<control type="label"><left>24</left><top>0</top><width>%d</width><height>72</height>'
            '<font>font13</font><textcolor>FFEEF3F6</textcolor><aligny>center</aligny>'
            '<label>$INFO[ListItem.Label]</label></control>'
            '</itemlayout>'
            '<focusedlayout height="72">'
            '<control type="image"><left>8</left><top>4</top><width>%d</width><height>64</height>'
            '<texture border="12" colordiffuse="FFFFFFFF">rv_key.png</texture></control>'
            '<control type="label"><left>24</left><top>0</top><width>%d</width><height>72</height>'
            '<font>font13</font><textcolor>FF0A0D12</textcolor><aligny>center</aligny>'
            '<label>$INFO[ListItem.Label]</label></control>'
            '</focusedlayout>'
        ) % (width, width + 16, width)

    option_row = (
        '<itemlayout height="72">'
        '<control type="label"><left>24</left><top>0</top><width>900</width><height>72</height>'
        '<font>font13</font><textcolor>FFEEF3F6</textcolor><aligny>center</aligny>'
        '<label>$INFO[ListItem.Label]</label></control>'
        '<control type="label"><left>940</left><top>0</top><width>280</width><height>72</height>'
        '<font>font13</font><textcolor>99EEF3F6</textcolor><align>right</align><aligny>center</aligny>'
        '<label>$INFO[ListItem.Label2]</label></control>'
        '</itemlayout>'
        '<focusedlayout height="72">'
        '<control type="image"><left>8</left><top>4</top><width>1264</width><height>64</height>'
        '<texture border="12" colordiffuse="FFFFFFFF">rv_key.png</texture></control>'
        '<control type="label"><left>24</left><top>0</top><width>900</width><height>72</height>'
        '<font>font13</font><textcolor>FF0A0D12</textcolor><aligny>center</aligny>'
        '<label>$INFO[ListItem.Label]</label></control>'
        '<control type="label"><left>940</left><top>0</top><width>280</width><height>72</height>'
        '<font>font13</font><textcolor>FF0A0D12</textcolor><align>right</align><aligny>center</aligny>'
        '<label>$INFO[ListItem.Label2]</label></control>'
        '</focusedlayout>'
    )
    text = '''<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<window>
    <defaultcontrol>32010</defaultcontrol>
    <depth>0.52</depth>
    <coordinates><left>0</left><top>0</top></coordinates>
    <controls>
        <control type="group">
            <left>0</left><top>0</top>
            <visible>!Player.HasVideo</visible>
            <animation type="WindowOpen" reversible="false">
                <effect type="fade" delay="0" end="100" time="200" />
            </animation>
            <!-- No WindowClose animation on purpose: Kodi drops every action while the topmost modal plays one. -->
            <control type="image"><width>1920</width><height>1080</height><texture colordiffuse="FF0A0D12">white.png</texture></control>
            <control type="label"><left>80</left><top>48</top><width>800</width><height>48</height><font>font37</font><textcolor>FFEEF3F6</textcolor><aligny>center</aligny><label>%s</label></control>
            <control type="label"><left>80</left><top>100</top><width>800</width><height>36</height><font>font12</font><textcolor>99EEF3F6</textcolor><aligny>center</aligny><label>$ADDON[plugin.video.revrivulet 30004]</label></control>
            <control type="list" id="32010">
                <left>64</left><top>180</top><width>460</width><height>288</height>
                <onleft>32010</onleft><onright>32011</onright>
                <onup>32010</onup><ondown>32010</ondown>
                <scrolltime tween="cubic" easing="out">180</scrolltime>
                %s
            </control>
            <control type="list" id="32011">
                <left>560</left><top>180</top><width>1280</width><height>576</height>
                <onleft>32010</onleft><onright>32012</onright>
                <onup>32011</onup><ondown>32012</ondown>
                <scrolltime tween="cubic" easing="out">180</scrolltime>
                %s
            </control>
            <control type="button" id="32012">
                <left>560</left><top>780</top><width>420</width><height>64</height>
                <font>font13</font><textcolor>FFEEF3F6</textcolor><focusedcolor>FF0A0D12</focusedcolor>
                <align>center</align><aligny>center</aligny>
                <texturefocus border="12" colordiffuse="FFFFFFFF">rv_key.png</texturefocus>
                <texturenofocus border="12" colordiffuse="14FFFFFF">rv_key.png</texturenofocus>
                <label>$ADDON[plugin.video.revrivulet 30435]</label>
                <onleft>32011</onleft><onright>32012</onright>
                <onup>32011</onup><ondown>32012</ondown>
            </control>
        </control>
    </controls>
</window>
''' % (WORDMARK, row(400), option_row)
    path = os.path.join(SKIN, 'Rev2SettingsWindow.xml')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print('wrote', path)


def _entry(string_id, msgid, msgstr):
    return 'msgctxt "#%d"\nmsgid "%s"\nmsgstr "%s"\n' % (string_id, msgid, msgstr)


def append_strings():
    for folder in sorted(os.listdir(LANG)):
        path = os.path.join(LANG, folder, 'strings.po')
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        locale = folder.split('.')[-1]
        added = []
        for string_id, msgid in STRINGS:
            if '#%d"' % string_id in text:
                continue
            if locale == 'en_gb':
                msgstr = ''
            elif msgid == 'Rev2Rivulet':
                msgstr = msgid
            else:
                msgstr = TRANSLATIONS.get(locale, {}).get(msgid, msgid)
            added.append(_entry(string_id, msgid, msgstr))
        if not added:
            continue
        if not text.endswith('\n'):
            text += '\n'
        text += '\n' + '\n'.join(added)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        print('strings', path, len(added))


def main():
    os.chdir(ROOT)
    build_windows()
    write_search_sheet()
    write_settings()
    written = write_assets(MASKS)
    print('masks', len(written))
    append_strings()


if __name__ == '__main__':
    main()
