"""Build the dark dialog skins (Dark*.xml) from the classic dialogs.

Settings > Interface > Dark dialogs swaps the classic dialogs for these
(`lib.ui.uicommon.open_window`). Each Dark*.xml is the classic file with
rounded translucent-black plates and a hairline instead of square slate
boxes with four 1px edges, focused rows and buttons on rounded dark-grey
plates, the accent in light grey and white text. The classic files are
not touched. Run from the repository root after changing a classic
dialog; textures come from tools/make_dialog_textures.py.
"""
import re
import sys

DIALOGS = ('BusyDialog.xml', 'ProgressDialog.xml', 'CountdownDialog.xml', 'ConfirmDialog.xml',
           'OptionListDialog.xml')
SKIN = 'resources/skins/Default/1080i/'

PANEL = re.compile(
    r'<control type="image"><left>(\d+)</left><top>(\d+)</top><width>(\d+)</width><height>(\d+)</height>'
    r'<texture colordiffuse="FF12161A">white.png</texture></control>')
EDGE = re.compile(
    r'[ \t]*<control type="image"><left>(\d+)</left><top>(\d+)</top><width>(\d+)</width><height>(\d+)</height>'
    r'<texture colordiffuse="([0-9A-F]{8})">white.png</texture>(<visible>[^<]*</visible>)?</control>\n')


def _panel(match):
    left, top, width, height = match.groups()
    box = '<left>%s</left><top>%s</top><width>%s</width><height>%s</height>' % (left, top, width, height)
    return ('<control type="image">%s<texture border="32" colordiffuse="E60A0A0A">dlg_panel.png</texture></control>\n'
            '            <control type="image">%s<texture border="32" colordiffuse="26FFFFFF">dlg_stroke.png</texture></control>'
            % (box, box))


def _drop_panel_edges(text):
    """The four 1px lines around each panel: the rounded hairline replaces them."""
    for left, top, width, height in [tuple(map(int, m.groups())) for m in PANEL.finditer(text)]:
        edges = {(left, top, width, 1), (left, top + height - 1, width, 1),
                 (left, top, 1, height), (left + width - 1, top, 1, height)}

        def keep(match, edges=edges):
            geom = tuple(int(v) for v in match.groups()[:4])
            return '' if geom in edges and match.group(5) == '1AFFFFFF' else match.group(0)
        text = EDGE.sub(keep, text)
    return text


def _buttons(text):
    """Hollow buttons (four 1px edges shown while unfocused) become one
    rounded hairline; the focused fill becomes a rounded plate."""
    edges = [m for m in EDGE.finditer(text) if m.group(6) and '!Control.HasFocus' in m.group(6)]
    groups = {}
    for m in edges:
        groups.setdefault(m.group(6), []).append(m)
    for visible, members in groups.items():
        if len(members) != 4:
            continue
        boxes = [tuple(int(v) for v in m.groups()[:4]) for m in members]
        left = min(b[0] for b in boxes)
        top = min(b[1] for b in boxes)
        right = max(b[0] + b[2] for b in boxes)
        bottom = max(b[1] + b[3] for b in boxes)
        color = members[0].group(5)
        stroke = ('            <control type="image"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
                  '<texture border="20" colordiffuse="%s">dlg_row_stroke.png</texture>%s</control>\n'
                  % (left, top, right - left, bottom - top, color, visible))
        first = True
        for m in members:
            text = text.replace(m.group(0), stroke if first else '', 1)
            first = False
    # Focused fills: a white.png plate shown on focus.
    text = re.sub(
        r'(<control type="image"><left>\d+</left><top>\d+</top><width>\d+</width><height>\d+</height>)'
        r'<texture colordiffuse="([0-9A-F]{8})">white.png</texture>(<visible>Control.HasFocus\(\d+\)</visible></control>)',
        r'\1<texture border="20" colordiffuse="\2">dlg_row.png</texture>\3', text)
    return text


def _list_rows(text):
    """The option list's focused row: a rounded plate, no blue edge bar."""
    text = text.replace(
        '<control type="image"><width>728</width><height>72</height><texture colordiffuse="FF1B2126">white.png</texture></control>',
        '<control type="image"><left>8</left><width>712</width><height>72</height><texture border="20" colordiffuse="FF2E2E2E">dlg_row.png</texture></control>')
    text = text.replace(
        '                    <control type="image"><width>6</width><height>72</height><texture colordiffuse="FF38BDF8">white.png</texture></control>\n', '')
    return text


def _dots(text):
    """The spinner's squares become dots (the round pill plate)."""
    return re.sub(r'(<width>16</width><height>16</height>\s*<texture colordiffuse="[0-9A-F]{8}">)white.png',
                  r'\1pill_fill.png', text)


def _readable_text(text):
    """Secondary text one step brighter on the black plates: 40-60% white
    reads as grey mush there. A focused menu row's second line goes
    further, to match its bright first line."""
    def focused(match):
        return match.group(0).replace('<textcolor>99FFFFFF</textcolor>', '<textcolor>D9FFFFFF</textcolor>')
    text = re.sub(r'<focusedlayout\b.*?</focusedlayout>', focused, text, flags=re.S)
    return re.sub(r'<textcolor>(?:66|80|99)FFFFFF</textcolor>', '<textcolor>B3FFFFFF</textcolor>', text)


#: The spinner fades in after this long, so a load that finishes sooner
#: (a cache hit) never flashes the dim plate. The dialog is up from the
#: first frame, so Back still reaches it: only a closing animation drops
#: input.
BUSY_FADE_DELAY = '350'


def _busy_fade(text):
    return text.replace('<effect type="fade" delay="0" end="100" time="200" />',
                        '<effect type="fade" delay="%s" end="100" time="200" />' % BUSY_FADE_DELAY, 1)


COLORS = (
    ('C707090B', 'A6000000'),   # the dim behind a dialog: black, lighter
    ('C70A0C0E', 'A6000000'),   # (the same dim, as the stock dialogs write it)
    ('FF1B2126', 'FF2E2E2E'),   # focus plate: dark grey
    ('38BDF8', 'D6D6D6'),       # the accent: light grey (alpha kept)
    ('FF04222E', 'FF0B0B0B'),   # text on the accent
    ('EEF3F6', 'FFFFFF'),       # text: white (alpha kept)
)


COMMENTS = (
    ("""Unfocused: hollow border built from four
                 white.png edges, same technique as the panel border
                 above.""", """Unfocused: a rounded hairline
                 (dlg_row_stroke.png)."""),
    ("""Unfocused:
                 hollow accent border so it still reads as the
                 recommended action before it has focus. Focused: solid
                 accent fill + dark bold text per spec;""", """Unfocused:
                 a light-grey rounded hairline so it still reads as the
                 recommended action before it has focus. Focused: a
                 light-grey rounded plate with dark text;"""),
)


def restyle(text):
    for old, new in COMMENTS:
        text = text.replace(old, new)
    text = _drop_panel_edges(text)
    text = PANEL.sub(_panel, text)
    text = _buttons(text)
    text = _list_rows(text)
    text = _dots(text)
    for old, new in COLORS:
        text = text.replace(old, new)
    return _readable_text(text)


def _option_list_ids(text):
    """Ids on the menu's plate, hairline and divider, so
    `dialogs._fit_option_list` can size the plate to the rows."""
    text = text.replace(
        '<control type="image"><left>580</left><top>140</top><width>760</width><height>730</height>'
        '<texture border="32" colordiffuse="E60A0A0A">dlg_panel.png</texture></control>',
        '<control type="image" id="30343"><left>580</left><top>140</top><width>760</width><height>730</height>'
        '<texture border="32" colordiffuse="E60A0A0A">dlg_panel.png</texture></control>')
    text = text.replace(
        '<control type="image"><left>580</left><top>140</top><width>760</width><height>730</height>'
        '<texture border="32" colordiffuse="26FFFFFF">dlg_stroke.png</texture></control>',
        '<control type="image" id="30344"><left>580</left><top>140</top><width>760</width><height>730</height>'
        '<texture border="32" colordiffuse="26FFFFFF">dlg_stroke.png</texture></control>')
    return text.replace(
        '<control type="image"><left>628</left><top>230</top><width>664</width><height>1</height>',
        '<control type="image" id="30345"><left>628</left><top>230</top><width>664</width><height>1</height>')


def main(paths=None):
    for name in paths or DIALOGS:
        with open(SKIN + name, encoding='utf-8') as handle:
            text = restyle(handle.read())
        if name == 'OptionListDialog.xml':
            text = _option_list_ids(text)
        if name == 'BusyDialog.xml':
            text = _busy_fade(text)
        out = SKIN + 'Dark' + name
        with open(out, 'w', encoding='utf-8') as handle:
            handle.write(text)
        print('wrote', out)


if __name__ == '__main__':
    main(sys.argv[1:])
