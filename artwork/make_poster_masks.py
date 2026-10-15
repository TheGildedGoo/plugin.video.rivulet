# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Build the poster and landscape diffuse masks.

Kodi stretches a ``diffuse`` image to the control. ``border`` 9-slices the
main texture only, so it does nothing to the mask. The old ``round_mask.png``
was a 48x48 square with a 16px corner. Stretched onto a 200x300 poster that
square becomes an ellipse, and the grey plate shows through the corners.
That is the jagged oval on unfocused rows.

These files are the control's own aspect at 2x, so the stretch is uniform
and the shape stays a rectangle. They are white (diffuse multiplies RGB)
with alpha 255 everywhere except an antialiased corner. The corner radius
is 32px here, which is 16px when drawn at the Home poster (200x300) or the
Continue card (392x220). The same file is the grey plate: a missing poster
is the same rounded rectangle, not a square behind an oval.

Run from the repo root: ``python3 artwork/make_poster_masks.py``
"""
import os

import numpy as np
from PIL import Image

_MEDIA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'resources', 'skins', 'Default', 'media',
)

# 2x the Home poster (200x300) and the Continue card (392x220). Every other
# poster control is the same 2:3, so one mask covers Home, the hub, the
# grid and the showcase. Radius 32 is 16px at those Home sizes.
_MASKS = (
    ('mask_poster.png', 400, 600, 32),
    ('mask_land.png', 784, 440, 32),
)


def rounded_rect(width, height, radius, samples=8):
    """RGBA rounded rect. Interior alpha is exactly 255; only the arc is partial."""
    sw = width * samples
    sh = height * samples
    xs = (np.arange(sw, dtype=np.float64) + 0.5) / samples
    ys = (np.arange(sh, dtype=np.float64) + 0.5) / samples
    x = xs[np.newaxis, :]
    y = ys[:, np.newaxis]
    inside = np.ones((sh, sw), dtype=bool)
    span = float(radius)
    corners = (
        (span, span, x < span, y < span),
        (width - span, span, x > width - span, y < span),
        (span, height - span, x < span, y > height - span),
        (width - span, height - span, x > width - span, y > height - span),
    )
    limit = span * span
    for cx, cy, in_x, in_y in corners:
        region = in_x & in_y
        outside = region & ((x - cx) ** 2 + (y - cy) ** 2 > limit)
        inside &= ~outside
    count = inside.reshape(height, samples, width, samples).sum(axis=(1, 3))
    total = samples * samples
    alpha = ((count * 255 + total // 2) // total).astype(np.uint8)
    image = np.full((height, width, 4), 255, dtype=np.uint8)
    image[:, :, 3] = alpha
    return image


def main():
    for name, width, height, radius in _MASKS:
        image = rounded_rect(width, height, radius)
        path = os.path.join(_MEDIA, name)
        Image.fromarray(image, 'RGBA').save(path, optimize=True)
        alpha = image[:, :, 3]
        print(
            '%s %dx%d radius %d  corner %d  edge %d  solid_from_x %d  partial %d'
            % (
                name,
                width,
                height,
                radius,
                int(alpha[0, 0]),
                int(alpha[height // 2, 0]),
                int(np.argmax(alpha[0] == 255)),
                int(((alpha > 0) & (alpha < 255)).sum()),
            )
        )


if __name__ == '__main__':
    main()
