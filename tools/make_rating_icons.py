# SPDX-FileCopyrightText: 2026 Rivulet contributors
# SPDX-License-Identifier: MIT
"""Draw Rivulet's original rating-source pictograms, without reference art.

Hand-authored Pillow geometry, supersampled for the 32px hero. No logo,
skin texture, outline, font or external image is copied or traced.
Run from the repo root; --check validates the seven shipped PNGs.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

MEDIA = Path(__file__).resolve().parents[1] / 'resources/skins/Default/media'
SS = 4


def _canvas():
    return Image.new('RGBA', (64 * SS, 64 * SS))


def _box(box):
    return tuple(int(n * SS) for n in box)


def _polygon(draw, points, color):
    draw.polygon([(int(x * SS), int(y * SS)) for x, y in points], fill=color)


def _tomato():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.ellipse(_box((7, 17, 57, 58)), fill='#EF473D')
    draw.ellipse(_box((9, 18, 34, 51)), fill='#F45745')
    _polygon(draw, [(31, 20), (15, 13), (26, 14), (29, 5), (34, 13),
                    (47, 9), (41, 19), (48, 24), (35, 23), (29, 31)], '#3CA664')
    draw.line(_box((31, 17, 34, 6)), fill='#246C44', width=3 * SS)
    return image


def _splat():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    # Uneven droplets around a solid centre, rather than a traced brand mark.
    for angle, radius, size in [(0, 18, 6), (43, 22, 5), (94, 18, 7),
                                (142, 23, 5), (190, 20, 6), (241, 20, 5), (296, 22, 6)]:
        x = 32 + math.cos(math.radians(angle)) * radius
        y = 32 + math.sin(math.radians(angle)) * radius
        draw.line(_box((32, 32, x, y)), fill='#79B84A', width=10 * SS)
        draw.ellipse(_box((x - size, y - size, x + size, y + size)), fill='#79B84A')
    draw.ellipse(_box((17, 18, 48, 47)), fill='#79B84A')
    return image


def _bucket():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _polygon(draw, [(12, 25), (52, 25), (46, 58), (18, 58)], '#ED5145')
    _polygon(draw, [(20, 25), (27, 25), (28, 58), (23, 58)], '#FFF6E7')
    _polygon(draw, [(36, 25), (43, 25), (40, 58), (35, 58)], '#FFF6E7')
    for x, y, r in [(17, 21, 6), (24, 15, 7), (33, 13, 7), (42, 17, 7), (48, 23, 6), (30, 24, 8)]:
        draw.ellipse(_box((x - r, y - r, x + r, y + r)), fill='#FFF0C5')
    draw.rounded_rectangle(_box((11, 25, 53, 30)), radius=2 * SS, fill='#FFF6E7')
    return image


def _spilled():
    image = _canvas()
    tipped = _bucket().rotate(-67, resample=Image.Resampling.BICUBIC, expand=True)
    tipped = tipped.crop(tipped.getbbox())
    tipped.thumbnail((52 * SS, 49 * SS), Image.Resampling.LANCZOS)
    image.alpha_composite(tipped, (4 * SS, 6 * SS))
    draw = ImageDraw.Draw(image)
    for x, y, r in [(49, 39, 4), (55, 46, 4), (45, 51, 3), (53, 55, 3)]:
        draw.ellipse(_box((x - r, y - r, x + r, y + r)), fill='#FFF0C5')
    return image


def _metacritic(color):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(_box((4, 4, 60, 60)), radius=12 * SS, fill=color)
    # A plain, hand-drawn block M; no font or source logo lettering.
    _polygon(draw, [(15, 47), (15, 17), (23, 17), (32, 32), (41, 17),
                    (49, 17), (49, 47), (41, 47), (41, 31), (32, 44),
                    (23, 31), (23, 47)], '#FFFFFF')
    return image


def icons():
    images = {
        'rating_rt_fresh.png': _tomato(),
        'rating_rt_rotten.png': _splat(),
        'rating_rt_audience_up.png': _bucket(),
        'rating_rt_audience_spilled.png': _spilled(),
        'rating_mc_green.png': _metacritic('#66CC33'),
        'rating_mc_yellow.png': _metacritic('#FFCC33'),
        'rating_mc_red.png': _metacritic('#FF0000'),
    }
    return {name: image.resize((64, 64), Image.Resampling.LANCZOS)
            for name, image in images.items()}


def main(check=False):
    for name, image in icons().items():
        path = MEDIA / name
        if check:
            with Image.open(path) as shipped:
                assert shipped.mode == 'RGBA' and shipped.size == (64, 64), name
                # Pillow's resampling can vary by version; validate the
                # export contract, not cross-version byte identity.
                image = shipped.copy()
        else:
            image.save(path, optimize=True)
        assert path.stat().st_size <= 8192, name
        corners = ((0, 0), (63, 0), (0, 63), (63, 63))
        assert all(image.getpixel(point)[3] == 0 for point in corners), name


if __name__ == '__main__':
    main(check='--check' in sys.argv)
