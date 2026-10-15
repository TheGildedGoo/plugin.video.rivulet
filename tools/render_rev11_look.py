# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Composite the rev11 screens from the shipped 1920x1080 skin assets.

This is not a Kodi framebuffer capture. The image in this environment
has no kodi package, so the window engine cannot be started. The
coordinates, masks, fades, and pills are the files Kodi would load.
Run: python3 tools/render_rev11_look.py /path/to/outdir
"""
import os
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MEDIA = os.path.join(_ROOT, 'resources', 'skins', 'Default', 'media')
_W, _H = 1920, 1080
_BG = (7, 9, 11, 255)
_INK = (238, 243, 246, 255)
_MUTED = (238, 243, 246, 180)
_DIM = (238, 243, 246, 110)


def _font(size, bold=False):
    name = 'NotoSans-Bold.ttf' if bold else 'NotoSans-Regular.ttf'
    return ImageFont.truetype('/usr/share/fonts/truetype/noto/' + name, size)


def _asset(name):
    return Image.open(os.path.join(_MEDIA, name)).convert('RGBA')


def _paste(canvas, image, box):
    left, top, width, height = box
    scaled = image.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)
    canvas.alpha_composite(scaled, (left, top))


def _masked(canvas, color, box, mask_name):
    left, top, width, height = box
    plate = Image.new('RGBA', (width, height), color)
    mask = _asset(mask_name).resize((width, height), Image.Resampling.LANCZOS).split()[-1]
    plate.putalpha(mask)
    canvas.alpha_composite(plate, (left, top))


def _fanart(canvas):
    art = Image.new('RGBA', (_W, _H), (18, 32, 48, 255))
    draw = ImageDraw.Draw(art)
    for y in range(_H):
        shade = int(40 + 80 * (1 - y / float(_H)))
        draw.line([(0, y), (_W, y)], fill=(shade, shade + 20, shade + 40, 255))
    draw.ellipse((980, -80, 1680, 620), fill=(70, 110, 140, 255))
    art = art.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(art)
    fade_h = _asset('fade_h.png')
    # The file is a horizontal alpha ramp. Stretch it over the left half.
    _paste(canvas, fade_h, (0, 0, 1280, _H))
    fade_v = _asset('fade_v.png')
    _paste(canvas, fade_v, (0, 280, _W, 496))
    plate = Image.new('RGBA', (_W, 428), (7, 9, 11, 255))
    canvas.alpha_composite(plate, (0, 652))


def _hero(canvas, title, meta, plot):
    draw = ImageDraw.Draw(canvas)
    draw.text((64, 188), title, font=_font(40, bold=True), fill=_INK)
    draw.text((64, 248), meta, font=_font(22), fill=_MUTED)
    draw.text((64, 292), plot, font=_font(26), fill=(238, 243, 246, 200))


def _wordmark(canvas):
    logo = _asset('logo.png')
    _paste(canvas, logo, (64, 22, 48, 48))
    ImageDraw.Draw(canvas).text((124, 28), 'RevRivulet', font=_font(28, bold=True), fill=_INK)


def _pills(canvas, labels, focused=0):
    draw = ImageDraw.Draw(canvas)
    pill = _asset('pill_fill.png')
    x = 48
    for index, label in enumerate(labels):
        tint = pill.copy()
        if index == focused:
            tint = ImageEnhance.Brightness(tint).enhance(2.4)
        _paste(canvas, tint, (x, 104, 196, 56))
        color = (7, 9, 11, 255) if index == focused else (238, 243, 246, 160)
        draw.text((x + 28, 116), label, font=_font(22, bold=index == focused), fill=color)
        x += 208


def _stroke(canvas, box):
    stroke = _asset('focus_stroke.png')
    _paste(canvas, stroke, box)


def _posters(canvas, origin, colors, focused=0, land=False):
    draw = ImageDraw.Draw(canvas)
    ox, oy = origin
    if land:
        size = (392, 220)
        step = 420
        mask = 'mask_land.png'
    else:
        size = (200, 300)
        step = 220
        mask = 'mask_poster.png'
    for index, color in enumerate(colors):
        box = (ox + index * step, oy, size[0], size[1])
        _masked(canvas, color, box, mask)
        if index == focused:
            _stroke(canvas, box)
        draw.text((box[0], box[1] + size[1] + 8), 'Title %d' % (index + 1), font=_font(16), fill=_DIM)


def _heading(canvas, text, y):
    ImageDraw.Draw(canvas).text((64, y), text, font=_font(18), fill=(238, 243, 246, 140))


def home(path):
    canvas = Image.new('RGBA', (_W, _H), _BG)
    _fanart(canvas)
    _wordmark(canvas)
    _pills(canvas, ('Movies', 'Series', 'Anime'))
    _hero(canvas, 'Dune', '2021  ·  2h 35m  ·  8.0', 'A noble family becomes the feud of an impossible planet.')
    _heading(canvas, 'CONTINUE', 652)
    _posters(canvas, (58, 692), ((90, 70, 50, 255), (40, 70, 90, 255), (70, 50, 80, 255)), land=True)
    _heading(canvas, 'LIBRARY', 980)
    canvas.save(path)


def hub(path):
    canvas = Image.new('RGBA', (_W, _H), _BG)
    _fanart(canvas)
    _wordmark(canvas)
    _hero(canvas, '1990s', 'MOVIES  ·  YEAR', 'Popular films from 1999, 1998, 1997…')
    _heading(canvas, 'YEAR', 652)
    labels = ('2020s', '2010s', '2000s', '1990s', '1980s', '1970s', '1960s')
    draw = ImageDraw.Draw(canvas)
    for index, label in enumerate(labels):
        box = (58 + index * 220, 692, 200, 300)
        _masked(canvas, (27, 36, 44, 255), box, 'mask_poster.png')
        if index == 3:
            _stroke(canvas, box)
        tw = draw.textlength(label, font=_font(28, bold=True))
        draw.text((box[0] + (200 - tw) / 2, box[1] + 130), label, font=_font(28, bold=True), fill=_INK)
    canvas.save(path)


def library(path):
    canvas = Image.new('RGBA', (_W, _H), _BG)
    _fanart(canvas)
    _wordmark(canvas)
    _hero(canvas, 'The Library', '13 titles', 'Saved on the account. The row keeps going past twelve.')
    _heading(canvas, 'YOUR LIBRARY', 652)
    colors = tuple((40 + i * 12, 60, 80, 255) for i in range(8))
    _posters(canvas, (64, 692), colors, focused=0)
    # Progress underline the width of the focused poster.
    ImageDraw.Draw(canvas).rectangle((74, 992, 254, 998), fill=(56, 189, 248, 255))
    canvas.save(path)


def sources(path):
    canvas = Image.new('RGBA', (_W, _H), (10, 12, 14, 255))
    draw = ImageDraw.Draw(canvas)
    _paste(canvas, _asset('logo.png'), (96, 64, 34, 34))
    draw.text((150, 68), 'RevRivulet', font=_font(16), fill=(238, 243, 246, 80))
    _masked(canvas, (80, 50, 40, 255), (96, 150, 340, 510), 'mask_poster.png')
    draw.text((96, 692), 'Dune', font=_font(28, bold=True), fill=_INK)
    draw.text((512, 158), 'Sources', font=_font(26, bold=True), fill=_INK)
    draw.text((1100, 158), 'Loading all sources…  2/6', font=_font(26), fill=_INK)
    for index, (quality, name) in enumerate((
        ('1080p', 'Cached  ·  Addon A'),
        ('1080p', 'Addon B'),
        ('720p', 'Addon A'),
    )):
        y = 228 + index * 118
        if index == 0:
            draw.rectangle((512, y, 1824, y + 118), fill=(27, 33, 38, 255))
            draw.rectangle((512, y, 518, y + 118), fill=(56, 189, 248, 255))
        draw.text((560, y + 36), quality, font=_font(22, bold=True), fill=_INK)
        draw.text((760, y + 36), name, font=_font(22), fill=_MUTED)
    canvas.save(path)


def up_next(path):
    canvas = Image.new('RGBA', (_W, _H), (10, 12, 14, 200))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((580, 420, 1340, 670), fill=(18, 22, 26, 255))
    draw.text((628, 460), 'Up next', font=_font(32, bold=True), fill=_INK)
    draw.text((628, 520), 'S02E01  ·  Premiere', font=_font(26), fill=_INK)
    draw.rectangle((628, 598, 900, 610), fill=(56, 189, 248, 255))
    draw.rectangle((900, 598, 1172, 610), fill=(255, 255, 255, 30))
    draw.text((1192, 586), '3', font=_font(20), fill=(56, 189, 248, 255))
    draw.text((628, 640), 'BACK cancel    OK play now', font=_font(16), fill=_DIM)
    canvas.save(path)


def continue_dialog(path):
    canvas = Image.new('RGBA', (_W, _H), (10, 12, 14, 200))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((580, 340, 1340, 760), fill=(18, 22, 26, 255))
    draw.text((628, 378), 'Show', font=_font(32, bold=True), fill=_INK)
    draw.rectangle((596, 470, 1324, 542), fill=(27, 33, 38, 255))
    draw.rectangle((596, 470, 602, 542), fill=(56, 189, 248, 255))
    draw.text((628, 486), 'Resume S1E3 from 12:04', font=_font(24), fill=_INK)
    draw.text((628, 570), 'Episode list', font=_font(24), fill=_MUTED)
    canvas.save(path)


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    shots = {
        'home.png': home,
        'hub-decades.png': hub,
        'library.png': library,
        'sources-loading.png': sources,
        'up-next.png': up_next,
        'continue-dialog.png': continue_dialog,
    }
    for name, draw in shots.items():
        dest = os.path.join(outdir, name)
        draw(dest)
        print(dest)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/opt/cursor/artifacts/screenshots')
