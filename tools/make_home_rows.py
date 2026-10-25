"""Extend Home's original poster group without changing its appearance.

Run from the repository root. The first shipped row is the byte-for-byte
template: only ids, visibility property and navigation links are replaced.
Existing texture generators do not generate XML.
"""
import re
from pathlib import Path

SKIN = Path('resources/skins/Default/1080i/NewHomeWindow.xml')
ROW = re.compile(
    r'<control type="group"><left>0</left><top>0</top><width>1856</width>'
    r'<height>450</height><visible>!String.IsEmpty\(Window.Property\(shelf_slot\d+\)\)</visible>'
    r'.*?</focusedlayout>\n</control>\n</control>', re.DOTALL)


def generate(text):
    """Keep the first twelve slots' ids, then use three disjoint blocks."""
    matches = list(ROW.finditer(text))
    template = matches[0].group()
    panels = [30041 + i if i < 12 else 30200 + i - 12 for i in range(40)]
    rows = []
    for index, panel in enumerate(panels):
        header = ((30141 + index if index < 5 else 30160 + index - 5)
                  if index < 12 else 30300 + index - 12)
        counter = ((30151 + index if index < 5 else 30170 + index - 5)
                   if index < 12 else 30400 + index - 12)
        row = template.replace('shelf_slot0', 'shelf_slot%d' % index)
        for old, new in ((30041, panel), (30141, header), (30151, counter)):
            row = row.replace(str(old), str(new))
        row = row.replace('<onup>30040</onup>',
                          '<onup>%d</onup>' % (panels[index - 1] if index else 30040))
        row = row.replace('<ondown>30042</ondown>',
                          '<ondown>%d</ondown>' % panels[min(index + 1, 39)])
        rows.append(row)
    return text[:matches[0].start()] + '\n'.join(rows) + text[matches[-1].end():]


if __name__ == '__main__':
    SKIN.write_text(generate(SKIN.read_text(encoding='utf-8')), encoding='utf-8')
