# SPDX-FileCopyrightText: 2026 M0RF30
# SPDX-License-Identifier: MIT
"""On-screen keyboard rows for the Rev2 search sheet.

Letters are applied from Python in ``onInit``. A literal ``Q`` inside a
skin ``<label>`` is an untranslated English word to the skin check, and
the remote never needs the XML to carry the caption.
"""

DELETE = 'delete'
SPACE = 'space'
SEARCH = 'search'

#: String ids for the three keys that are words. Letters and digits are
#: their own caption.
KEY_STRINGS = {
    DELETE: 30433,
    SPACE: 30434,
    SEARCH: 30001,
}

ROWS = (
    tuple('QWERTYUIOP'),
    tuple('ASDFGHJKL'),
    tuple('ZXCVBNM'),
    tuple('1234567890'),
    (SPACE, DELETE),
    (SEARCH,),
)

FIRST_BUTTON = 32200
FIRST_ROW = 32300
QUERY_LABEL = 32100
HISTORY_LIST = 32120
CLEAR_BUTTON = 32121


def button_map():
    """``{control id: key}`` in row order. The skin builder uses the same map."""
    mapping = {}
    number = FIRST_BUTTON
    for row in ROWS:
        for key in row:
            mapping[number] = key
            number += 1
    return mapping


def row_ids():
    """Grouplist id for each keyboard row."""
    return [FIRST_ROW + index for index in range(len(ROWS))]
