# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Draw Rev2Rivulet's masks, scrims and icons.

Run on a dev machine (Pillow >= 9.2) and commit the PNGs. Nothing here
runs on the box.

The poster mask RevRivulet shipped in rev4-ui is a 48px square
(``round_mask.png``) used with ``border="16"`` and a grey
``round_fill.png`` plate behind the art. On a CoreELEC box that square
stretches into a jagged grey oval. These masks are a different file:

* the same pixel size as the control they diffuse (2:3 posters, 16:9
  landscapes), so Kodi does not stretch them into an oval
* a rounded rectangle, not a circle: corner radius 12px, well under a
  sixth of the short side, so the sides stay straight
* full opacity inside (alpha 255). There is no grey plate behind the art
* antialiased by drawing at 4x and downsampling

Do not point a Rev2 control at ``round_mask.png`` / ``round_fill.png`` /
``round_frame.png``, and do not set ``border`` on a diffuse mask. A
9-slice border is what collapsed the old mask's straight edges.
"""
import os

from PIL import Image, ImageDraw, ImageFilter

MEDIA = os.path.join('resources', 'skins', 'Default', 'media')
SS = 4
WHITE = (255, 255, 255, 255)
#: Small enough that the sides stay straight. 12px at the control's own
#: pixel size, which is the size these masks are drawn at.
CORNER_RADIUS = 12


def _rrect(width, height, radius, stroke=0):
    image = Image.new('RGBA', (width * SS, height * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = (0, 0, width * SS - 1, height * SS - 1)
    if stroke:
        draw.rounded_rectangle(box, radius * SS, outline=WHITE, width=stroke * SS)
    else:
        draw.rounded_rectangle(box, radius * SS, fill=WHITE)
    return image.resize((width, height), Image.LANCZOS)


def _shadow(size=160, inset=48, radius=16, blur=18, alpha=153):
    image = Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle(
        (inset * SS, inset * SS, (size - inset) * SS, (size - inset) * SS),
        radius * SS,
        fill=(0, 0, 0, alpha),
    )
    return image.filter(ImageFilter.GaussianBlur(blur * SS)).resize((size, size), Image.LANCZOS)


def _gradient(width, height, horizontal, start, end):
    """White with an alpha ramp. Smoothstep hides the hard band."""
    image = Image.new('RGBA', (width, height))
    span = width if horizontal else height
    for index in range(span):
        t = index / (span - 1)
        t = t * t * (3 - 2 * t)
        alpha = round(start + (end - start) * t)
        if horizontal:
            image.paste((255, 255, 255, alpha), (index, 0, index + 1, height))
        else:
            image.paste((255, 255, 255, alpha), (0, index, width, index + 1))
    return image


#: The right vignette stops here. 255 turned the right quarter into a
#: black rectangle behind the ratings. The scrim is what the text sits on.
_FADE_H_PEAK = 88


def _fade_h(width=480, height=1080):
    """Clear on the left, a light vignette on the right, same on every row.

    The file this replaced reached alpha 255, so the right quarter was a
    solid dark panel with a hard rectangular shape. The ratings scrim is
    the contrast now. This ramp only takes the glare off a bright edge.
    """
    image = Image.new('RGBA', (width, height))
    pixels = image.load()
    last = width - 1
    for x in range(width):
        t = x / float(last)
        t = t * t * (3 - 2 * t)
        color = (255, 255, 255, int(round(_FADE_H_PEAK * t)))
        for y in range(height):
            pixels[x, y] = color
    return image


def _fade_v(width=8, height=1080):
    """Clear through the hero text, opaque from 75% of the height down.

    A smoothstep that started at y=0 was already most of the way to black
    behind the title, and that dark band read as a hard-edged block. The
    ramp holds clear until 72% of the opaque point, then eases to black.
    Windows size the control so the opaque point meets the poster row.
    """
    image = Image.new('RGBA', (width, height))
    pixels = image.load()
    hold = int(round(0.75 * (height - 1)))
    ramp = int(round(0.72 * hold))
    span = hold - ramp
    for y in range(height):
        if y >= hold:
            alpha = 255
        elif y <= ramp:
            alpha = 0
        else:
            t = (y - ramp) / float(span) if span else 1.0
            t = t * t * (3 - 2 * t)
            alpha = int(round(255 * t))
        color = (255, 255, 255, alpha)
        for x in range(width):
            pixels[x, y] = color
    return image


def _scrim_feather(size=128, border=40, center=210):
    """White, dark in the middle, clear at the rim.

    The skin draws this with ``border="40"``. Kodi does not scale that
    rim, so the fade stays 40px when the center stretches to the text.
    Distance is from the inner rectangle, which makes the corners round
    off instead of meeting in a square edge. Alpha 0 on the outer pixel
    is what removes the hard line.
    """
    image = Image.new('RGBA', (size, size))
    pixels = image.load()
    inner0 = border
    inner1 = size - border - 1
    for y in range(size):
        for x in range(size):
            if x < inner0:
                dx = inner0 - x
            elif x > inner1:
                dx = x - inner1
            else:
                dx = 0
            if y < inner0:
                dy = inner0 - y
            elif y > inner1:
                dy = y - inner1
            else:
                dy = 0
            if dx == 0 and dy == 0:
                alpha = center
            else:
                dist = (dx * dx + dy * dy) ** 0.5
                t = dist / float(border)
                if t > 1.0:
                    t = 1.0
                t = t * t * (3 - 2 * t)
                alpha = int(round(center * (1.0 - t)))
            pixels[x, y] = (255, 255, 255, alpha)
    return image


def write_hero_fades():
    """Write fade_h.png and fade_v.png. Run from the repo root."""
    os.makedirs(MEDIA, exist_ok=True)
    _fade_h().save(os.path.join(MEDIA, 'fade_h.png'), optimize=True)
    _fade_v().save(os.path.join(MEDIA, 'fade_v.png'), optimize=True)


def write_scrim():
    """Write scrim_feather.png. Run from the repo root."""
    os.makedirs(MEDIA, exist_ok=True)
    _scrim_feather().save(os.path.join(MEDIA, 'scrim_feather.png'), optimize=True)


def _switch(on):
    image = Image.new('RGBA', (72 * SS, 40 * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    track = (90, 184, 255, 255) if on else (255, 255, 255, 60)
    draw.rounded_rectangle((0, 0, 72 * SS - 1, 40 * SS - 1), 20 * SS, fill=track)
    cx = (52 if on else 20) * SS
    draw.ellipse((cx - 16 * SS, 4 * SS, cx + 16 * SS, 36 * SS), fill=WHITE)
    return image.resize((72, 40), Image.LANCZOS)


def _icon(draw_fn):
    image = Image.new('RGBA', (64 * SS, 64 * SS), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(image), SS)
    return image.resize((64, 64), Image.LANCZOS)


def _search(draw, scale):
    draw.ellipse((14 * scale, 14 * scale, 40 * scale, 40 * scale), outline=WHITE, width=4 * scale)
    draw.line((36 * scale, 36 * scale, 50 * scale, 50 * scale), fill=WHITE, width=4 * scale)


def _addons(draw, scale):
    for left, top in ((14, 14), (34, 14), (14, 34), (34, 34)):
        draw.rounded_rectangle(
            (left * scale, top * scale, (left + 16) * scale, (top + 16) * scale),
            3 * scale,
            outline=WHITE,
            width=3 * scale,
        )


def _settings(draw, scale):
    draw.ellipse((22 * scale, 22 * scale, 42 * scale, 42 * scale), outline=WHITE, width=4 * scale)
    for index in range(8):
        # Eight ticks around the hub. A full gear polygon is more ink than a TV needs.
        angle = index * 45
        import math
        rad = math.radians(angle)
        x0 = 32 + int(round(math.cos(rad) * 14))
        y0 = 32 + int(round(math.sin(rad) * 14))
        x1 = 32 + int(round(math.cos(rad) * 22))
        y1 = 32 + int(round(math.sin(rad) * 22))
        draw.line((x0 * scale, y0 * scale, x1 * scale, y1 * scale), fill=WHITE, width=4 * scale)


def _play(draw, scale):
    draw.polygon(
        [(22 * scale, 16 * scale), (22 * scale, 48 * scale), (48 * scale, 32 * scale)],
        fill=WHITE,
    )


def _plus(draw, scale):
    draw.line((32 * scale, 16 * scale, 32 * scale, 48 * scale), fill=WHITE, width=4 * scale)
    draw.line((16 * scale, 32 * scale, 48 * scale, 32 * scale), fill=WHITE, width=4 * scale)


def _check(draw, scale):
    draw.line((16 * scale, 34 * scale, 28 * scale, 46 * scale), fill=WHITE, width=4 * scale)
    draw.line((28 * scale, 46 * scale, 50 * scale, 18 * scale), fill=WHITE, width=4 * scale)


def _more(draw, scale):
    for cx in (18, 32, 46):
        draw.ellipse(
            ((cx - 4) * scale, 28 * scale, (cx + 4) * scale, 36 * scale),
            fill=WHITE,
        )


def _check_circle(draw, scale):
    draw.ellipse((8 * scale, 8 * scale, 56 * scale, 56 * scale), outline=WHITE, width=4 * scale)
    _check(draw, scale)


TEXTURES = {
    'mask_poster.png': _rrect(200, 300, 12),
    'mask_landscape.png': _rrect(384, 216, 12),
    'mask_search.png': _rrect(160, 240, 10),
    'rr12.png': _rrect(64, 64, 12),
    'rr20.png': _rrect(96, 96, 20),
    'rr3.png': _rrect(12, 6, 3),
    'pill56.png': _rrect(112, 56, 28),
    'pill72.png': _rrect(144, 72, 36),
    'circle64.png': _rrect(64, 64, 32),
    'circle72.png': _rrect(72, 72, 36),
    'focus_frame.png': _rrect(64, 64, 18, stroke=4),
    'shadow.png': _shadow(),
    'scrim_left.png': _gradient(512, 8, True, 235, 0),
    'scrim_bottom.png': _gradient(8, 512, False, 0, 255),
    'switch_on.png': _switch(True),
    'switch_off.png': _switch(False),
    'white.png': Image.new('RGBA', (8, 8), WHITE),
}


def _icons():
    folder = os.path.join(OUT, 'icons')
    os.makedirs(folder, exist_ok=True)
    glyphs = {
        'search.png': _search,
        'addons.png': _addons,
        'settings.png': _settings,
        'play.png': _play,
        'plus.png': _plus,
        'check.png': _check,
        'more.png': _more,
        'check_circle.png': _check_circle,
    }
    for name, fn in glyphs.items():
        path = os.path.join(folder, name)
        _icon(fn).save(path, optimize=True)
        print('wrote', path)


def mask_filename(width, height):
    """Diffuse mask named for the control it is drawn at, so Kodi does not scale it."""
    return 'rv_mask_%dx%d.png' % (width, height)


def _assert_rounded_rect(image, radius):
    """Fail the build if this mask would read as an oval or a grey plate.

    A rounded rectangle is opaque along the middle of every edge and
    transparent only in the corners. An ellipse (what the 48px square
    mask became once a poster stretched it) leaves the edge middles
    transparent or eats a fifth of the pixels.
    """
    width, height = image.size
    pixels = image.load()
    center = pixels[width // 2, height // 2]
    if center != WHITE:
        raise SystemExit('mask center %s is not opaque white' % (center,))
    if pixels[0, 0][3] > 16:
        raise SystemExit('mask corner is filled; radius ate the corner')
    for point in (
        (width // 2, 0),
        (width // 2, height - 1),
        (0, height // 2),
        (width - 1, height // 2),
    ):
        if pixels[point][3] < 250:
            raise SystemExit('edge %s is transparent; the mask is an oval' % (point,))
    transparent = 0
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] < 16:
                transparent += 1
    ratio = transparent / float(width * height)
    if ratio > 0.05:
        raise SystemExit('mask is %.1f%% empty; a 12px corner cannot do that' % (ratio * 100))
    if radius > 16 or radius < 12:
        raise SystemExit('corner radius %s is outside 12-16px' % radius)


def write_assets(mask_sizes):
    """Write the masks the Rev2 skin diffuses, plus the key and focus stroke.

    `mask_sizes` is an iterable of `(width, height)` at the control's
    pixel size. Each file is that size, so a 2:3 poster stays a 2:3
    rounded rectangle.
    """
    os.makedirs(MEDIA, exist_ok=True)
    written = []
    for width, height in sorted(set(mask_sizes)):
        image = _rrect(width, height, CORNER_RADIUS)
        _assert_rounded_rect(image, CORNER_RADIUS)
        path = os.path.join(MEDIA, mask_filename(width, height))
        image.save(path, optimize=True)
        written.append(path)
    key = _rrect(48, 48, CORNER_RADIUS)
    key.save(os.path.join(MEDIA, 'rv_key.png'), optimize=True)
    frame = _rrect(48, 48, CORNER_RADIUS, stroke=3)
    frame.save(os.path.join(MEDIA, 'rv_focus_frame.png'), optimize=True)
    # Home and hub draw this on the poster rectangle with border=16.
    # A filled plate behind the art, or a stroke on a larger box, sat
    # off the card. Radius 16 matches the poster mask at display size.
    # Inset by half the stroke so the line is inside the 9-slice border
    # instead of clipped off the texture edge.
    stroke = _rrect(64, 64, 16, stroke=3)
    stroke.save(os.path.join(MEDIA, 'focus_stroke.png'), optimize=True)
    return written


def main():
    # Sizes the skin builder asks for. Running this file alone still
    # produces the poster and landscape masks the home rows use.
    write_assets(((200, 300), (392, 220), (340, 510)))
    write_hero_fades()
    write_scrim()


if __name__ == '__main__':
    main()
