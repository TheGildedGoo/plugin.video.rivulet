"""Rounded textures for the dark dialogs (tools/build_dark_dialogs.py).

dlg_panel.png and its hairline dlg_stroke.png are drawn 9-slice with
border=32; dlg_row.png and dlg_row_stroke.png (focused rows and buttons,
the spinner's dots) with border=20. Needs Pillow; run from the
repository root.
"""
import os

from PIL import Image, ImageDraw

MEDIA = os.path.join('resources', 'skins', 'Default', 'media')
#: Supersampling: drawn this many times larger, then scaled down, so the
#: curves are smooth.
SS = 4
WHITE = (255, 255, 255, 255)


def _rrect(width, height, radius, stroke=0):
    image = Image.new('RGBA', (width * SS, height * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = (0, 0, width * SS - 1, height * SS - 1)
    if stroke:
        draw.rounded_rectangle(box, radius * SS, outline=WHITE, width=stroke * SS)
    else:
        draw.rounded_rectangle(box, radius * SS, fill=WHITE)
    return image.resize((width, height), Image.LANCZOS)


def main():
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


if __name__ == '__main__':
    main()
