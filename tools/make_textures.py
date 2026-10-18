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


def _hero_bar(width=16, height=128, fade=64):
    """White. The top ``fade`` rows ease from clear to solid.

    The skin draws this with ``border="0,64,0,8"``, so that fade stays
    64px when the control grows. The rest is solid and stretches.
    """
    image = Image.new('RGBA', (width, height))
    pixels = image.load()
    last = fade - 1 if fade > 1 else 1
    for y in range(height):
        if y >= fade:
            alpha = 255
        else:
            t = y / float(last)
            t = t * t * (3 - 2 * t)
            alpha = int(round(255 * t))
        color = (255, 255, 255, alpha)
        for x in range(width):
            pixels[x, y] = color
    return image


def _card_shade(width=16, height=220, clear_until=0.58, peak=210):
    """Clear over the picture, dark along the bottom of an episode card.

    Stretched to the whole card and clipped by the landscape mask, so
    the gradient follows the rounded corners instead of a rectangle.
    """
    image = Image.new('RGBA', (width, height))
    pixels = image.load()
    start = int(round(clear_until * (height - 1)))
    span = (height - 1) - start
    for y in range(height):
        if y <= start:
            alpha = 0
        else:
            t = (y - start) / float(span) if span else 1.0
            t = t * t * (3 - 2 * t)
            alpha = int(round(peak * t))
        color = (255, 255, 255, alpha)
        for x in range(width):
            pixels[x, y] = color
    return image


def write_hero_bar():
    """Write hero_bar.png and card_shade.png. Run from the repo root."""
    os.makedirs(MEDIA, exist_ok=True)
    _hero_bar().save(os.path.join(MEDIA, 'hero_bar.png'), optimize=True)
    _card_shade().save(os.path.join(MEDIA, 'card_shade.png'), optimize=True)


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
    folder = os.path.join(MEDIA, 'icons')
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


# --- Fuse look (lib/ui/fuse.py) -------------------------------------------

def _ramp(points, span):
    """Alpha at each of `span` steps along piecewise smoothstep `points`.

    `points` are ``(position 0..1, alpha 0..255)`` in order.
    """
    values = []
    for index in range(span):
        x = index / (span - 1)
        alpha = points[-1][1]
        for (x0, a0), (x1, a1) in zip(points, points[1:]):
            if x0 <= x <= x1:
                t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                t = t * t * (3 - 2 * t)
                alpha = a0 + (a1 - a0) * t
                break
        values.append(int(round(alpha)))
    return values


def _fade(points, span, horizontal, thickness=8):
    """Black with an alpha ramp: the Fuse fades are drawn colour-true."""
    size = (span, thickness) if horizontal else (thickness, span)
    image = Image.new('RGBA', size)
    for index, alpha in enumerate(_ramp(points, span)):
        box = (index, 0, index + 1, thickness) if horizontal else (0, index, thickness, index + 1)
        image.paste((0, 0, 0, alpha), box)
    return image


#: Left fade: dark under the title and plot, clear past two thirds of
#: the width, so the picture shows to the right of the text.
FUSE_FADE_LEFT = ((0.0, 235), (0.34, 168), (0.66, 0), (1.0, 0))
#: Bottom fade, top to bottom: clear through the picture, solid from the
#: row band (y=630 of 1080, 0.583) down, so posters never sit on art.
FUSE_FADE_BOTTOM = ((0.0, 0), (0.36, 0), (0.52, 150), (0.583, 255), (1.0, 255))
#: A light shade behind the date and clock at the top edge.
FUSE_FADE_TOP = ((0.0, 140), (1.0, 0))


def _star_points(cx, cy, outer, inner):
    import math
    points = []
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.radians(-90 + index * 36)
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points


def _stars(half_stars, size=28, gap=5):
    """Five stars, `half_stars` of ten lit. Unlit is white at 30%."""
    width = size * 5 + gap * 4
    lit = Image.new('RGBA', (width * SS, size * SS), (0, 0, 0, 0))
    dim = Image.new('RGBA', (width * SS, size * SS), (0, 0, 0, 0))
    for index in range(5):
        cx = (index * (size + gap) + size / 2) * SS
        cy = (size / 2 + 1) * SS
        points = _star_points(cx, cy, size / 2 * SS, size / 2 * 0.45 * SS)
        ImageDraw.Draw(lit).polygon(points, fill=WHITE)
        ImageDraw.Draw(dim).polygon(points, fill=(255, 255, 255, 77))
    # Lit up to the half-star boundary, dim after it.
    full, half = divmod(half_stars, 2)
    cut = int(min(width, full * (size + gap) + (size / 2 if half else 0)) * SS)
    out = dim.copy()
    if cut:
        out.paste(lit.crop((0, 0, cut, size * SS)), (0, 0))
    return out.resize((width, size), Image.LANCZOS)


def _fuse_icon(draw_fn, focused):
    """64px icon button face. Idle: a white glyph (the skin dims it).
    Focused: a white disc with the glyph cut out in near-black."""
    glyph = Image.new('RGBA', (64 * SS, 64 * SS), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(glyph), SS)
    if not focused:
        return glyph.resize((64, 64), Image.LANCZOS)
    face = Image.new('RGBA', (64 * SS, 64 * SS), (0, 0, 0, 0))
    ImageDraw.Draw(face).ellipse((0, 0, 64 * SS - 1, 64 * SS - 1), fill=WHITE)
    ink = Image.new('RGBA', face.size, (7, 9, 11, 255))
    face.paste(ink, (0, 0), glyph.split()[3])
    return face.resize((64, 64), Image.LANCZOS)


#: Over a card's mirror image under the row: part-dark at the card's
#: edge, solid black by the middle, so the reflection fades into the
#: black under the rows. A plain (unflipped) texture over the flipped
#: art, so it does not depend on how Kodi orients a diffuse.
FUSE_REFLECT_FADE = ((0.0, 100), (0.45, 235), (0.65, 255), (1.0, 255))


def _panel(size=96, radius=32):
    """A filled rounded rectangle, drawn 9-slice with border=40: the
    white plate behind a focused list row (Fuse episode list)."""
    return _rrect(size, size, radius)


def write_fuse_assets():
    """Fades, the focus ring, star strips and icon faces for the Fuse look."""
    os.makedirs(MEDIA, exist_ok=True)
    out = {
        'fuse_fade_left.png': _fade(FUSE_FADE_LEFT, 960, True),
        'fuse_fade_bottom.png': _fade(FUSE_FADE_BOTTOM, 540, False),
        'fuse_fade_top.png': _fade(FUSE_FADE_TOP, 64, False),
        # Drawn 9-slice with border=24: radius 20 outside a 12px card
        # corner, 5px of white, so the ring is concentric with the art.
        'fuse_ring.png': _rrect(64, 64, 20, stroke=5),
        'fuse_reflect_fade.png': _fade(FUSE_REFLECT_FADE, 256, False),
        'fuse_panel.png': _panel(),
        'fuse_check.png': _icon(_check),
    }
    for half in range(11):
        out['fuse_stars_%02d.png' % half] = _stars(half)
    for name, fn in (('search', _search), ('addons', _addons), ('settings', _settings)):
        out['fuse_icon_%s.png' % name] = _fuse_icon(fn, False)
        out['fuse_icon_%s_focus.png' % name] = _fuse_icon(fn, True)
    for name, image in out.items():
        path = os.path.join(MEDIA, name)
        image.save(path, optimize=True)
        print('wrote', path)


def write_dialog_assets():
    """Rounded plates for the dialogs (spinner, progress, menus, confirm):
    a filled panel and its hairline, drawn 9-slice with border=32, and a
    smaller filled/stroked pair for focused rows and buttons (border=20)."""
    os.makedirs(MEDIA, exist_ok=True)
    out = {
        'dlg_panel.png': _rrect(96, 96, 28),
        'dlg_stroke.png': _rrect(96, 96, 28, stroke=2),
        'dlg_row.png': _rrect(64, 64, 16),
        'dlg_row_stroke.png': _rrect(64, 64, 16, stroke=2),
    }
    for name, image in out.items():
        path = os.path.join(MEDIA, name)
        image.save(path, optimize=True)
        print('wrote', path)


def main():
    # Sizes the skin builder asks for. Running this file alone still
    # produces the poster and landscape masks the home rows use.
    write_assets(((200, 300), (392, 220), (340, 510)))
    write_hero_fades()
    write_scrim()
    write_hero_bar()
    write_fuse_assets()
    write_dialog_assets()


if __name__ == '__main__':
    main()
