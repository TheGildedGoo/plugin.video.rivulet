# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Write the Fuse skin files (lib/ui/fuse.py). Run from the repo root.

    python3 tools/build_fuse_skins.py [1080i dir]

Writes FuseHomeWindow.xml, FuseHubWindow.xml, FuseShowcaseWindow.xml and
FuseDetailWindow.xml. Each declares every control id its classic file
does, with the classic navigation, so the same window class drives
either; tests/test_fuse.py checks that. Edit the look here, not in the
XML, and commit both. Nothing here comes from another skin.
"""
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join('resources', 'skins', 'Default', '1080i')

BAND = 560          # top of the row band
VIEW_H = 520        # band to the bottom edge: one row per viewport
CARD_TOP = 72       # inside a row: heading 44, line at 50, cards at 72
POSTER = (200, 300)
LAND = (392, 220)
POSTER_STEP = 232
LAND_STEP = 424
REFLECT_GAP = 8
FONT_TEXT = 'font13'
BULLET = '•'


def ctl(kind, inner, cid=None):
    ident = ' id="%d"' % cid if cid else ''
    return '<control type="%s"%s>%s</control>' % (kind, ident, inner)


def box(left, top, width, height):
    return '<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (left, top, width, height)


def vis(*conds):
    return ''.join('<visible>%s</visible>' % c for c in conds if c)


def image(left, top, width, height, texture, extra='', conds=(), cid=None, attrs=''):
    return ctl('image', box(left, top, width, height) + '<texture%s>%s</texture>%s%s' % (attrs, texture, extra, vis(*conds)), cid)


def label(left, top, width, height, text, font=FONT_TEXT, color='FFEDEDED', align='', conds=(), cid=None, extra=''):
    a = '<align>%s</align>' % align if align else ''
    return ctl('label', box(left, top, width, height) +
               '<font>%s</font><textcolor>%s</textcolor>%s<aligny>center</aligny>%s<label>%s</label>%s' % (
                   font, color, a, extra, text, vis(*conds)), cid)


def card(left, top, size, art, mask, conds, keep=True, reflect=True):
    """Art on a plate, with its mirror image under it."""
    width, height = size
    aspect = '<aspectratio align="center" aligny="center">keep</aspectratio>' if keep else '<aspectratio>scale</aspectratio>'
    out = [
        image(left, top, width, height, mask, conds=conds[:1] if conds else (), attrs=' colordiffuse="FF16191C"'),
        image(left, top, width, height, art, aspect, conds=conds, attrs=' diffuse="%s" background="true"' % mask),
    ]
    if reflect:
        rtop = top + height + REFLECT_GAP
        out.append(image(left, rtop, width, height, art, aspect, conds=conds,
                         attrs=' flipy="true" diffuse="%s" colordiffuse="66FFFFFF" background="true"' % mask))
        out.append(image(left, rtop, width, height, 'fuse_reflect_fade.png', '<aspectratio>stretch</aspectratio>',
                         conds=conds, attrs=' colordiffuse="FFFFFFFF"'))
    return ''.join(out)


def ring(left, top, size, conds):
    width, height = size
    return image(left - 8, top - 8, width + 16, height + 16, 'fuse_ring.png', conds=conds,
                 attrs=' border="24" colordiffuse="FFFFFFFF"')


# --- shared pieces -----------------------------------------------------------

def head(defaultcontrol):
    dc = '<defaultcontrol>%s</defaultcontrol>' % defaultcontrol if defaultcontrol else ''
    return '''<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<!-- The Fuse look (lib/ui/fuse.py). Same control ids as the classic file
     of this name, so the same window class drives either; tests/test_fuse.py
     holds that. 1920x1080, standard font names only (font12, font13,
     font45), which Estuary defines. Written by tools/build_fuse_skins.py;
     edit it there. Keep the classic file's
     ids and navigation when editing. -->
<window>
    %s
    <depth>0.52</depth>
    <coordinates><left>0</left><top>0</top></coordinates>
    <controls>
        <control type="group">
            <left>0</left><top>0</top>
            <visible>!Player.HasVideo</visible>
            <animation type="WindowOpen" reversible="false">
                <effect type="fade" delay="0" end="100" time="200" />
            </animation>
            <!-- No WindowClose animation on purpose: Kodi drops every action while the topmost modal plays one (test_skin_xml.py rule 9). -->
''' % dc


TAIL = '''        </control>
    </controls>
</window>
'''


def warm_slots(ids):
    return ''.join(image(0, 0, 1, 1, '', cid=cid, attrs=' background="true"') for cid in ids) + '\n'


def backdrop():
    return '\n'.join([
        image(0, 0, 1920, 1080, 'white.png', attrs=' colordiffuse="FF000000"'),
        '<!-- The backdrop fills the screen; the fades carry the text. -->',
        image(0, 0, 1920, 1080, '', '<aspectratio align="center" aligny="center">scale</aspectratio>',
              conds=('String.IsEmpty(Window.Property(HeroFill))',), cid=30000, attrs=' background="true" colordiffuse="FFFFFFFF"'),
        image(0, 0, 1920, 1080, '', '<aspectratio align="center" aligny="center">scale</aspectratio>',
              conds=('!String.IsEmpty(Window.Property(HeroFill))',), cid=30028, attrs=' background="true" colordiffuse="FFFFFFFF"'),
        '<!-- No bar: dark toward the left and the bottom, light at the top. -->',
        image(0, 0, 1920, 1080, 'fuse_fade_left.png', '<aspectratio>stretch</aspectratio>', attrs=' colordiffuse="FFFFFFFF"'),
        image(0, 0, 1920, 1080, 'fuse_fade_bottom.png', '<aspectratio>stretch</aspectratio>', attrs=' colordiffuse="FFFFFFFF"'),
        image(0, 0, 1920, 220, 'fuse_fade_top.png', '<aspectratio>stretch</aspectratio>', attrs=' colordiffuse="FFFFFFFF"'),
    ]) + '\n'


def clock():
    return label(1040, 36, 800, 50, '[B]$INFO[System.Time]$INFO[Weather.Temperature,  %s  ,][/B]' % BULLET, align='right') + '\n'


def date():
    return label(80, 36, 900, 50, '[B]$INFO[System.Date][/B]') + '\n'


def hidden_classic(ids_and_kinds):
    """Classic controls the shared code writes to; never shown here."""
    out = ['<!-- The classic bar and ratings column: kept for the shared window code, never shown in this look. -->']
    for cid, kind, inner in ids_and_kinds:
        out.append(ctl(kind, box(0, 0, 1, 1) + inner + '<visible>false</visible>', cid))
    return '\n'.join(out) + '\n'


def hero(bound=False):
    """The stack lib/ui/fuse.py moves; these positions are a full stack."""
    title_text = '[B]$INFO[Container(30002).ListItem.Label][/B]' if bound else ''
    plot_text = '$INFO[Container(30002).ListItem.Property(plot)]' if bound else ''
    return '\n'.join([
        '<!-- Hero, stacked up from the row by lib/ui/fuse.py: the logo (or the title), stars and facts, the plot (three lines at most), the scores. -->',
        ctl('image', box(80, 210, 1000, 120) + '<aspectratio align="left" aligny="bottom">keep</aspectratio><texture background="true"></texture>' +
            vis('!String.IsEmpty(Window.Property(HeroLogo))'), 30023),
        ctl('label', box(80, 250, 1100, 80) + '<font>font45</font><textcolor>FFEDEDED</textcolor><shadowcolor>C8000000</shadowcolor><aligny>center</aligny><wrapmultiline>false</wrapmultiline><label>%s</label>' % title_text +
            vis('String.IsEmpty(Window.Property(HeroLogo))'), 30020),
        ctl('image', box(80, 352, 150, 28) + '<aspectratio>keep</aspectratio><texture></texture>', 30027),
        ctl('label', box(246, 346, 1200, 40) + '<font>font13</font><textcolor>E6EDEDED</textcolor><shadowcolor>C8000000</shadowcolor><aligny>center</aligny><label></label>', 30024),
        ctl('textbox', box(80, 396, 920, 110) + '<font>font13</font><textcolor>C7EDEDED</textcolor><shadowcolor>C8000000</shadowcolor><autoscroll delay="3000" time="4000" repeat="6000">true</autoscroll><label>%s</label>' % plot_text, 30022),
        ctl('label', box(80, 480, 1400, 40) + '<font>font13</font><textcolor>E6EDEDED</textcolor><shadowcolor>C8000000</shadowcolor><aligny>center</aligny><label></label>', 30025),
    ]) + '\n'


def icon_button(cid, name, ondown):
    return ('<control type="button" id="%d"><width>56</width><height>56</height>'
            '<texturefocus colordiffuse="FFFFFFFF">fuse_icon_%s_focus.png</texturefocus>'
            '<texturenofocus colordiffuse="B3FFFFFF">fuse_icon_%s.png</texturenofocus>'
            '<label></label><ondown>%d</ondown><onup>30011</onup></control>' % (cid, name, name, ondown))


def tools(onleft, ondown):
    return '''<control type="grouplist" id="30011">
                <left>1040</left><top>100</top><width>800</width><height>56</height>
                <orientation>horizontal</orientation>
                <align>right</align>
                <itemgap>8</itemgap>
                <onleft>%d</onleft><onright>30072</onright>
                <onup>30011</onup><ondown>%d</ondown>
                <control type="button" id="30073"><width>210</width><height>56</height><font>font13</font><textcolor>E6EDEDED</textcolor><focusedcolor>FF07090B</focusedcolor><align>center</align><aligny>center</aligny><texturefocus border="28" colordiffuse="FFFFFFFF">pill_fill.png</texturefocus><texturenofocus border="28" colordiffuse="24FFFFFF">pill_fill.png</texturenofocus><label>[B]$ADDON[plugin.video.revrivulet 30427][/B]</label><ondown>%d</ondown><onup>30011</onup><visible>!String.IsEmpty(Window.Property(HomeSignedOut))</visible></control>
                %s
                %s
                %s
            </control>
''' % (onleft, ondown, ondown, icon_button(30070, 'search', ondown), icon_button(30071, 'addons', ondown), icon_button(30072, 'settings', ondown))


def row_heading(text_label, counter_label, cond):
    return ''.join([
        text_label,
        counter_label,
        image(16, 50, 1784, 2, 'white.png', conds=(cond,) if cond else (), attrs=' colordiffuse="24EDEDED"'),
    ])


# --- Home ----------------------------------------------------------------------

HOME_ROWS = [
    ('shelf_continue', 30140, 30040, 30150, 30010, 30041, True),
    ('shelf_library', 30141, 30041, 30151, 30040, 30042, False),
    ('shelf_movies', 30142, 30042, 30152, 30041, 30043, False),
    ('shelf_series', 30143, 30043, 30153, 30042, 30044, False),
    ('shelf_anime', 30144, 30044, 30154, 30043, 30045, False),
    ('shelf_other', 30145, 30045, 30155, 30044, 30045, False),
]


def home_wide_layout(panel, focused):
    left, top = 16, 8
    has_land = '!String.IsEmpty(ListItem.Property(land))'
    parts = [
        image(left, top, LAND[0], LAND[1], 'mask_land.png', attrs=' colordiffuse="FF16191C"'),
        image(left, top, LAND[0], LAND[1], '$INFO[ListItem.Property(thumbnail)]',
              '<aspectratio align="center" aligny="center">keep</aspectratio>', attrs=' diffuse="mask_land.png" background="true"'),
        image(left, top, LAND[0], LAND[1], '$INFO[ListItem.Property(land)]', '<aspectratio>scale</aspectratio>',
              conds=(has_land,), attrs=' diffuse="mask_land.png" background="true"'),
        # Mirror of whichever picture the card shows.
        image(left, top + LAND[1] + REFLECT_GAP, LAND[0], LAND[1], '$INFO[ListItem.Property(land)]', '<aspectratio>scale</aspectratio>',
              conds=(has_land,), attrs=' flipy="true" diffuse="mask_land.png" colordiffuse="66FFFFFF" background="true"'),
        image(left, top + LAND[1] + REFLECT_GAP, LAND[0], LAND[1], '$INFO[ListItem.Property(thumbnail)]',
              '<aspectratio align="center" aligny="center">keep</aspectratio>',
              conds=('String.IsEmpty(ListItem.Property(land))', '!String.IsEmpty(ListItem.Property(thumbnail))'),
              attrs=' flipy="true" diffuse="mask_land.png" colordiffuse="66FFFFFF" background="true"'),
        image(left, top + LAND[1] + REFLECT_GAP, LAND[0], LAND[1], 'fuse_reflect_fade.png', '<aspectratio>stretch</aspectratio>',
              attrs=' colordiffuse="FFFFFFFF"'),
        label(left + 16, top, 360, LAND[1], '$INFO[ListItem.Label]', color='E6EDEDED', align='center',
              conds=('String.IsEmpty(ListItem.Property(thumbnail))', 'String.IsEmpty(ListItem.Property(land))'),
              extra='<wrapmultiline>true</wrapmultiline>'),
        image(left, top, LAND[0], LAND[1], 'card_shade.png', '<aspectratio>stretch</aspectratio>',
              conds=('!String.IsEmpty(ListItem.Property(card_show))', has_land), attrs=' diffuse="mask_land.png" colordiffuse="FF000000"'),
        label(left + 16, top + 156, 360, 28, '[B]$INFO[ListItem.Property(card_show)][/B]', font='font12', color='FFFFFFFF',
              conds=('!String.IsEmpty(ListItem.Property(card_show))', has_land), extra='<shadowcolor>C8000000</shadowcolor>'),
        label(left + 16, top + 184, 360, 28, '$INFO[ListItem.Property(card_code)]', font='font12', color='E6FFFFFF',
              conds=('!String.IsEmpty(ListItem.Property(card_code))', has_land), extra='<shadowcolor>C8000000</shadowcolor>'),
    ]
    if focused:
        parts.append(ring(left, top, LAND, ('Control.HasFocus(%d)' % panel,)))
    return ''.join(parts)


def home_poster_layout(panel, focused):
    left, top = 16, 8
    has_art = '!String.IsEmpty(ListItem.Property(thumbnail))'
    parts = [card(left, top, POSTER, '$INFO[ListItem.Property(thumbnail)]', 'mask_poster.png', (has_art,), keep=True)]
    # card() gates the plate on the art; a card with no art still needs one.
    parts.insert(0, image(left, top, POSTER[0], POSTER[1], 'mask_poster.png', conds=('String.IsEmpty(ListItem.Property(thumbnail))',),
                          attrs=' colordiffuse="FF16191C"'))
    parts.append(label(left + 12, top, 176, POSTER[1], '$INFO[ListItem.Label]', color='E6EDEDED', align='center',
                       conds=('String.IsEmpty(ListItem.Property(thumbnail))',), extra='<wrapmultiline>true</wrapmultiline>'))
    if focused:
        parts.append(ring(left, top, POSTER, ('Control.HasFocus(%d)' % panel,)))
    return ''.join(parts)


def home_row(prop, heading, panel, counter, onup, ondown, wide):
    cond = '!String.IsEmpty(Window.Property(%s))' % prop
    width = LAND_STEP if wide else POSTER_STEP
    height = VIEW_H - 64
    layout = home_wide_layout if wide else home_poster_layout
    return (
        '<control type="group">' + box(0, 0, 1856, VIEW_H) + vis(cond) + '\n' +
        row_heading(
            label(16, 0, 1200, 44, '', conds=(cond,), cid=heading),
            label(1440, 0, 360, 44, '', font='font12', color='B3EDEDED', align='right', conds=(cond,), cid=counter),
            cond) + '\n' +
        '<control type="panel" id="%d">' % panel + box(0, 64, 1856, height) +
        '<orientation>horizontal</orientation><onleft>%d</onleft><onright>%d</onright><onup>%d</onup><ondown>%d</ondown>'
        '<scrolltime tween="cubic" easing="out">240</scrolltime><preloaditems>2</preloaditems>%s\n' % (panel, panel, onup, ondown, vis(cond)) +
        '<itemlayout width="%d" height="%d">%s</itemlayout>\n' % (width, height, layout(panel, False)) +
        '<focusedlayout width="%d" height="%d">%s</focusedlayout>\n' % (width, height, layout(panel, True)) +
        '</control>\n</control>\n')


def home():
    hidden = hidden_classic([
        (30026, 'image', '<texture></texture>'),
        (30021, 'textbox', '<font>font12</font><textcolor>FFFFFFFF</textcolor><label></label>'),
        (30005, 'label', '<font>font12</font><textcolor>FFFFFFFF</textcolor><label></label>'),
    ])
    pills = '''<control type="list" id="30010">
                <left>240</left><top>96</top><width>780</width><height>64</height>
                <orientation>horizontal</orientation>
                <onleft>30010</onleft><onright>30011</onright>
                <onup>30010</onup><ondown>30001</ondown>
                <scrolltime tween="cubic" easing="out">180</scrolltime>
                <visible>!String.IsEmpty(Window.Property(HomeBrowse))</visible>
                <itemlayout width="190" height="64">%s</itemlayout>
                <focusedlayout width="190" height="64">%s%s%s</focusedlayout>
            </control>
''' % (
        label(8, 4, 174, 56, '[B]$INFO[ListItem.Label][/B]', color='B3EDEDED', align='center'),
        image(8, 4, 174, 56, 'pill_fill.png', conds=('Control.HasFocus(30010)',), attrs=' border="28" colordiffuse="FFFFFFFF"'),
        label(8, 4, 174, 56, '[B]$INFO[ListItem.Label][/B]', color='FF07090B', align='center', conds=('Control.HasFocus(30010)',)),
        label(8, 4, 174, 56, '[B]$INFO[ListItem.Label][/B]', color='B3EDEDED', align='center', conds=('!Control.HasFocus(30010)',)),
    )
    rows = ''.join(home_row(*spec) for spec in HOME_ROWS)
    body = (
        warm_slots(range(30090, 30100)) + backdrop() + hidden + date() + clock() +
        image(80, 100, 150, 56, 'pill_fill.png', attrs=' border="28" colordiffuse="24FFFFFF"') + '\n' +
        label(80, 100, 150, 56, '[B]$ADDON[plugin.video.revrivulet 30495][/B]', align='center') + '\n' +
        pills + tools(30010, 30001) + hero() +
        '''<!-- Rows: one %dpx group per row, the height of this viewport, so only the focused row is on screen (see HomeWindow.xml). Heading, "row / rows", a faint line, the cards and their reflections; the white ring shows only on the row that has the remote. -->
            <control type="grouplist" id="30001">
                <left>64</left><top>%d</top><width>1856</width><height>%d</height>
                <orientation>vertical</orientation>
                <itemgap>0</itemgap>
                <onup>30010</onup><ondown>30001</ondown>
                <onleft>30001</onleft><onright>30001</onright>
                <usecontrolcoords>true</usecontrolcoords>
                <scrolltime tween="cubic" easing="out">280</scrolltime>
%s            </control>
''' % (VIEW_H, BAND, VIEW_H, rows))
    return head(30001) + body + TAIL


# --- Hub -------------------------------------------------------------------------

def _p(name, i):
    return 'ListItem.Property(%s%d)' % (name, i)


def hub_layout(focused):
    not_land = '!String.IsEqual(ListItem.Property(layout),land)'
    is_land = 'String.IsEqual(ListItem.Property(layout),land)'
    not_decade = '!String.IsEqual(ListItem.Property(layout),decade)'
    is_decade = 'String.IsEqual(ListItem.Property(layout),decade)'
    parts = [label(16, 0, 1200, 44, '[B]$INFO[ListItem.Property(heading)][/B]'),
             image(16, 50, 1784, 2, 'white.png', attrs=' colordiffuse="24EDEDED"')]
    for i in range(8):
        left = 16 + i * POSTER_STEP
        top = CARD_TOP
        has_name = '!String.IsEmpty(%s)' % _p('n', i)
        has_art = '!String.IsEmpty(%s)' % _p('p', i)
        parts.append(image(left, top, POSTER[0], POSTER[1], 'mask_poster.png',
                           conds=(not_land, not_decade, has_name), attrs=' colordiffuse="FF16191C"'))
        art = '$INFO[%s]' % _p('p', i)
        parts.append(image(left, top, POSTER[0], POSTER[1], art, '<aspectratio>keep</aspectratio>',
                           conds=(not_land, has_art), attrs=' diffuse="mask_poster.png" background="true"'))
        rtop = top + POSTER[1] + REFLECT_GAP
        parts.append(image(left, rtop, POSTER[0], POSTER[1], art, '<aspectratio>keep</aspectratio>',
                           conds=(not_land, has_art), attrs=' flipy="true" diffuse="mask_poster.png" colordiffuse="66FFFFFF" background="true"'))
        parts.append(image(left, rtop, POSTER[0], POSTER[1], 'fuse_reflect_fade.png', '<aspectratio>stretch</aspectratio>',
                           conds=(not_land, has_art), attrs=' colordiffuse="FFFFFFFF"'))
        parts.append(label(left + 12, top, 176, POSTER[1], '$INFO[%s]' % _p('n', i), color='E6EDEDED', align='center',
                           conds=(not_land, not_decade, 'String.IsEmpty(%s)' % _p('p', i), has_name),
                           extra='<wrapmultiline>true</wrapmultiline>'))
        # Decade tiles: a plate with the years on it.
        parts.append(image(left, top, POSTER[0], POSTER[1], 'mask_poster.png', conds=(is_decade, has_name),
                           attrs=' colordiffuse="FF1E2328"'))
        parts.append(label(left, top, POSTER[0], POSTER[1], '[B]$INFO[%s][/B]' % _p('n', i), color='FFEDEDED', align='center',
                           conds=(is_decade, has_name)))
        if focused:
            parts.append(ring(left, top, POSTER, ('Control.HasFocus(31000)', not_land, 'String.IsEqual(ListItem.Property(focusslot),%d)' % i)))
    for i in range(4):
        left = 16 + i * LAND_STEP
        top = CARD_TOP
        has_name = '!String.IsEmpty(%s)' % _p('n', i)
        has_art = '!String.IsEmpty(%s)' % _p('p', i)
        art = '$INFO[%s]' % _p('p', i)
        parts.append(image(left, top, LAND[0], LAND[1], 'mask_land.png', conds=(is_land, has_name), attrs=' colordiffuse="FF16191C"'))
        parts.append(image(left, top, LAND[0], LAND[1], art, '<aspectratio>scale</aspectratio>',
                           conds=(is_land, has_art), attrs=' diffuse="mask_land.png" background="true"'))
        rtop = top + LAND[1] + REFLECT_GAP
        parts.append(image(left, rtop, LAND[0], LAND[1], art, '<aspectratio>scale</aspectratio>',
                           conds=(is_land, has_art), attrs=' flipy="true" diffuse="mask_land.png" colordiffuse="66FFFFFF" background="true"'))
        parts.append(image(left, rtop, LAND[0], LAND[1], 'fuse_reflect_fade.png', '<aspectratio>stretch</aspectratio>',
                           conds=(is_land, has_art), attrs=' colordiffuse="FFFFFFFF"'))
        parts.append(label(left + 16, top, 360, LAND[1], '$INFO[%s]' % _p('n', i), color='E6EDEDED', align='center',
                           conds=(is_land, 'String.IsEmpty(%s)' % _p('p', i), has_name), extra='<wrapmultiline>true</wrapmultiline>'))
        # New Episodes: the show and S:1 E:2 bottom-left, a grey line between shows.
        parts.append(image(left, top, LAND[0], LAND[1], 'card_shade.png', '<aspectratio>stretch</aspectratio>',
                           conds=(is_land, has_art), attrs=' diffuse="mask_land.png" colordiffuse="FF000000"'))
        parts.append(label(left + 16, top + 156, 360, 28, '[B]$INFO[%s][/B]' % _p('show', i), font='font12', color='FFFFFFFF',
                           conds=(is_land, '!String.IsEmpty(%s)' % _p('show', i)), extra='<shadowcolor>C8000000</shadowcolor>'))
        parts.append(label(left + 16, top + 184, 360, 28, '$INFO[%s]' % _p('code', i), font='font12', color='F2EEF3F6',
                           conds=(is_land, '!String.IsEmpty(%s)' % _p('code', i)), extra='<shadowcolor>C8000000</shadowcolor>'))
        if i:
            parts.append(image(left - 18, top + 16, 4, 188, 'white.png',
                               conds=(is_land, 'String.IsEqual(ListItem.Property(div%d),1)' % i), attrs=' colordiffuse="FF8B949E"'))
        if focused:
            parts.append(ring(left, top, LAND, ('Control.HasFocus(31000)', is_land, 'String.IsEqual(ListItem.Property(focusslot),%d)' % i)))
    return ''.join(parts)


def hub():
    hidden = hidden_classic([
        (30026, 'image', '<texture></texture>'),
        (30021, 'textbox', '<font>font12</font><textcolor>FFFFFFFF</textcolor><label></label>'),
    ])
    body = (
        warm_slots(range(30090, 30100)) + backdrop() + hidden + date() + clock() +
        '<!-- The page\'s name where Home has its Home pill (#20). -->\n' +
        image(80, 100, 240, 56, 'pill_fill.png', attrs=' border="28" colordiffuse="24FFFFFF"') + '\n' +
        label(80, 100, 240, 56, '', align='center', cid=30005) + '\n' +
        tools(30073, 31000) + hero() +
        '''<!-- One catalog row on screen at a time (focusposition 0, one row tall), as on Home. -->
            <control type="fixedlist" id="31000">
                <left>64</left><top>%d</top><width>1856</width><height>%d</height>
                <orientation>vertical</orientation>
                <focusposition>0</focusposition>
                <onup>30011</onup><ondown>31000</ondown>
                <onleft>31000</onleft><onright>31000</onright>
                <scrolltime tween="cubic" easing="out">280</scrolltime>
                <itemlayout height="%d">%s</itemlayout>
                <focusedlayout height="%d">%s</focusedlayout>
            </control>
''' % (BAND, VIEW_H, VIEW_H, hub_layout(False), VIEW_H, hub_layout(True)) +
        label(1504, BAND, 360, 44, '$INFO[Container(31000).CurrentItem] / $INFO[Container(31000).NumItems]', font='font12',
              color='B3EDEDED', align='right', conds=('Integer.IsGreater(Container(31000).NumItems,0)',)) + '\n')
    return head(31000) + body + TAIL


# --- Showcase (catalog, decade, search and cast lists) --------------------------

def showcase_layout(focused):
    left, top = 16, CARD_TOP
    art = '$INFO[ListItem.Property(thumbnail)]'
    has_art = '!String.IsEmpty(ListItem.Property(thumbnail))'
    parts = [card(left, top, POSTER, art, 'mask_poster.png', (has_art,), keep=True),
             label(left + 12, top, 176, POSTER[1], '$INFO[ListItem.Label]', color='E6EDEDED', align='center',
                   conds=('String.IsEmpty(ListItem.Property(thumbnail))',), extra='<wrapmultiline>true</wrapmultiline>')]
    parts.insert(0, image(left, top, POSTER[0], POSTER[1], 'mask_poster.png', conds=('String.IsEmpty(ListItem.Property(thumbnail))',),
                          attrs=' colordiffuse="FF16191C"'))
    if focused:
        parts.append(ring(left, top, POSTER, ('Control.HasFocus(30002)',)))
    return ''.join(parts)


def showcase():
    hidden = hidden_classic([
        (30026, 'image', '<texture></texture>'),
        (30021, 'textbox', '<font>font12</font><textcolor>FFFFFFFF</textcolor><label>$INFO[ListItem.Property(meta_line)]</label>'),
        (30003, 'button', '<label></label><ondown>30002</ondown>'),
    ])
    body = (
        warm_slots((30098, 30099)) + backdrop() + hidden +
        '<!-- The page\'s name: REVRIVULET / the catalog (infowindow._header_label). -->\n' +
        label(80, 36, 940, 50, '', cid=30100) + '\n' + clock() +
        image(810, 200, 300, 10, 'white.png', cid=30001, attrs=' colordiffuse="8038BDF8"') + '\n' +
        hero(bound=True) +
        label(1504, BAND, 360, 44, '$INFO[Container(30002).CurrentItem] / $INFO[Container(30002).NumItems]', font='font12',
              color='B3EDEDED', align='right', conds=('Integer.IsGreater(Container(30002).NumItems,0)',)) + '\n' +
        image(80, BAND + 50, 1784, 2, 'white.png', attrs=' colordiffuse="24EDEDED"') + '\n' +
        '''<control type="fixedlist" id="30002">
                <left>64</left><top>%d</top><width>1856</width><height>%d</height>
                <viewtype>wrap</viewtype><orientation>horizontal</orientation>
                <scrolltime tween="cubic" easing="out">300</scrolltime>
                <focusposition>0</focusposition>
                <onup>30002</onup><ondown>30002</ondown>
                <itemlayout width="%d" height="%d">%s</itemlayout>
                <focusedlayout width="%d" height="%d">%s</focusedlayout>
            </control>
''' % (BAND, VIEW_H, POSTER_STEP, VIEW_H, showcase_layout(False), POSTER_STEP, VIEW_H, showcase_layout(True)))
    return head(None) + body + TAIL


# --- Episode page ---------------------------------------------------------------

ROW_H = 200
LIST_TOP = 300


def detail_row(focused):
    """One episode: the still, "1x01. Title", the air date, a tick when
    watched, the runtime, two lines of plot. The focused row is a white
    panel with dark text; every other row is light text on the picture."""
    has_focus = 'Control.HasFocus(30002)'
    parts = []
    states = (('dark', has_focus), ('light', '!' + has_focus)) if focused else (('light', ''),)
    if focused:
        parts.append(image(0, 6, 1310, ROW_H - 12, 'fuse_panel.png', conds=(has_focus,), attrs=' border="40" colordiffuse="FFFFFFFF"'))
    # 294x165 is the Continue card's 392:220, so mask_land keeps its corners.
    parts.append(image(16, 18, 294, 165, 'mask_land.png', attrs=' colordiffuse="FF16191C"'))
    parts.append(image(16, 18, 294, 165, '$INFO[ListItem.Property(thumb)]', '<aspectratio>scale</aspectratio>',
                       attrs=' diffuse="mask_land.png" background="true"'))
    parts.append(ctl('progress', box(28, 170, 270, 5) +
                     '<texturebg colordiffuse="40FFFFFF">white.png</texturebg><midtexture colordiffuse="FFFFFFFF">white.png</midtexture>'
                     '<info>ListItem.PercentPlayed</info>' +
                     vis('!String.IsEmpty(ListItem.Property(watched_percent))', 'String.IsEmpty(ListItem.Property(watched))')))
    for tone, cond in states:
        strong = 'FF07090B' if tone == 'dark' else 'FFEDEDED'
        soft = 'B307090B' if tone == 'dark' else 'B3EDEDED'
        tick = 'FF07090B' if tone == 'dark' else 'FFEDEDED'
        conds = (cond,) if cond else ()
        parts.append(label(336, 30, 610, 46, '[B]$INFO[ListItem.Property(ep_title)][/B]', color=strong, conds=conds))
        parts.append(label(950, 30, 200, 46, '$INFO[ListItem.Property(aired)]', color=soft, align='right', conds=conds))
        parts.append(image(1162, 41, 26, 26, 'fuse_check.png', conds=conds + ('String.IsEqual(ListItem.Property(watched),1)',),
                           attrs=' colordiffuse="%s"' % tick))
        parts.append(label(1196, 30, 100, 46, '$INFO[ListItem.Property(runtime)]', color=soft, conds=conds))
        parts.append(ctl('textbox', box(336, 82, 950, 72) +
                         '<font>font12</font><textcolor>%s</textcolor><label>$INFO[ListItem.Property(plot)]</label>' % soft + vis(*conds)))
    return ''.join(parts)


def detail():
    hidden = '\n'.join([
        '<!-- The classic header lines and scrollbar: kept for the window code, never shown in this look. -->',
        ctl('label', box(0, 0, 1, 1) + '<font>font12</font><textcolor>FFFFFFFF</textcolor><label></label><visible>false</visible>', 30101),
        ctl('label', box(0, 0, 1, 1) + '<font>font12</font><textcolor>FFFFFFFF</textcolor><label></label><visible>false</visible>', 30102),
        ctl('scrollbar', box(0, 0, 1, 1) + '<onleft>30002</onleft><onright>30002</onright><orientation>vertical</orientation>'
            '<texturesliderbackground colordiffuse="00FFFFFF">white.png</texturesliderbackground>'
            '<texturesliderbar colordiffuse="00FFFFFF">white.png</texturesliderbar>'
            '<texturesliderbarfocus colordiffuse="00FFFFFF">white.png</texturesliderbarfocus><visible>false</visible>', 30006),
    ]) + '\n'
    pill = ('<control type="button" id="%d">' + box(0, 0, 0, 0)[:0] + '<left>%d</left><top>100</top><width>220</width><height>56</height>'
            '<font>font13</font><textcolor>E6EDEDED</textcolor><focusedcolor>FF07090B</focusedcolor><align>center</align><aligny>center</aligny>'
            '<texturefocus border="28" colordiffuse="FFFFFFFF">pill_fill.png</texturefocus><texturenofocus border="28" colordiffuse="24FFFFFF">pill_fill.png</texturenofocus>'
            '<label>[B]$ADDON[plugin.video.revrivulet %d][/B]</label>'
            '<onup>%d</onup><ondown>30007</ondown><onleft>%d</onleft><onright>%d</onright></control>\n')
    tabs = '''<control type="list" id="30007">
                <left>80</left><top>236</top><width>1000</width><height>52</height>
                <orientation>horizontal</orientation>
                <onleft>30007</onleft><onright>30007</onright>
                <onup>30009</onup><ondown>30002</ondown>
                <itemlayout width="200" height="52">%s</itemlayout>
                <focusedlayout width="200" height="52">%s%s%s</focusedlayout>
            </control>
''' % (
        label(0, 0, 190, 46, '[B]$INFO[ListItem.Label][/B]', color='8CEDEDED'),
        label(0, 0, 190, 46, '[B]$INFO[ListItem.Label][/B]', color='FFEDEDED'),
        image(0, 46, 120, 4, 'white.png', conds=('Control.HasFocus(30007)',), attrs=' colordiffuse="FFEDEDED"'),
        image(0, 46, 120, 2, 'white.png', conds=('!Control.HasFocus(30007)',), attrs=' colordiffuse="80EDEDED"'),
    )
    body = (
        warm_slots((30098, 30099)) +
        image(0, 0, 1920, 1080, 'white.png', attrs=' colordiffuse="FF000000"') + '\n' +
        image(0, 0, 1920, 1080, '', '<aspectratio align="center" aligny="center">scale</aspectratio>', cid=30000,
              attrs=' background="true" colordiffuse="FFFFFFFF"') + '\n' +
        '<!-- The list sits over most of the picture: a light dim everywhere, then the left and bottom fades. -->\n' +
        image(0, 0, 1920, 1080, 'white.png', attrs=' colordiffuse="80000000"') + '\n' +
        image(0, 0, 1920, 1080, 'fuse_fade_left.png', '<aspectratio>stretch</aspectratio>', attrs=' colordiffuse="FFFFFFFF"') + '\n' +
        image(0, 0, 1920, 1080, 'fuse_fade_top.png', '<aspectratio>stretch</aspectratio>', attrs=' colordiffuse="FFFFFFFF"') + '\n' +
        hidden + clock() +
        '<!-- The show: its logo once Kodi has it, else its name (lib/ui/fuse.py). -->\n' +
        ctl('image', box(80, 70, 900, 140) + '<aspectratio align="left" aligny="center">keep</aspectratio><texture background="true"></texture>' +
            vis('!String.IsEmpty(Window.Property(HeroLogo))'), 30023) + '\n' +
        ctl('label', box(80, 100, 1100, 80) + '<font>font45</font><textcolor>FFEDEDED</textcolor><shadowcolor>C8000000</shadowcolor><aligny>center</aligny><label></label>' +
            vis('String.IsEmpty(Window.Property(HeroLogo))'), 30005) + '\n' +
        '<!-- Trailer and Options for remotes without a menu key (#15). -->\n' +
        (pill % (30012, 1364, 30499, 30012, 30012, 30009)) +
        (pill % (30009, 1604, 30492, 30009, 30012, 30009)) +
        tabs +
        label(1100, 236, 270, 46, '', font='font12', color='B3EDEDED', align='right',
              conds=('!String.IsEmpty(Control.GetLabel(30100))',), cid=30100) + '\n' +
        image(80, 290, 1290, 2, 'white.png', attrs=' colordiffuse="24EDEDED"') + '\n' +
        '''<control type="list" id="30002">
                <left>60</left><top>%d</top><width>1310</width><height>%d</height>
                <onup>30007</onup>
                <onleft>30002</onleft><onright>30002</onright>
                <scrolltime tween="cubic" easing="out">200</scrolltime>
                <pagecontrol>30006</pagecontrol>
                <itemlayout height="%d">%s</itemlayout>
                <focusedlayout height="%d">%s</focusedlayout>
            </control>
''' % (LIST_TOP, 3 * ROW_H, ROW_H, detail_row(False), ROW_H, detail_row(True)) +
        '<!-- The show\'s poster on the right. -->\n' +
        image(1410, LIST_TOP, 430, 645, '', '<aspectratio>scale</aspectratio>', cid=30004,
              attrs=' diffuse="mask_poster.png" background="true"') + '\n' +
        label(80, 1000, 600, 40, '$INFO[Container(30002).CurrentItem] / $INFO[Container(30002).NumItems]', font='font12',
              color='B3EDEDED', conds=('Integer.IsGreater(Container(30002).NumItems,0)',)) + '\n' +
        image(80, 1044, 1290, 2, 'white.png', attrs=' colordiffuse="24EDEDED"') + '\n')
    return head(None) + body + TAIL


for name, build in (('FuseHomeWindow.xml', home), ('FuseHubWindow.xml', hub), ('FuseShowcaseWindow.xml', showcase),
                    ('FuseDetailWindow.xml', detail)):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as handle:
        handle.write(build())
    print('wrote', name)
