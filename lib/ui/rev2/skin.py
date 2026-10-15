# SPDX-FileCopyrightText: 2026 M0RF30
# SPDX-License-Identifier: MIT
"""Pick the Rev2 skin file when this process is the Rev2Rivulet zip.

RevRivulet and Rev2Rivulet share one tree. ``open_window`` asks here
which XML to load. The Rev2 files are the same controls with the oval
mask and the grey plate taken out, so the existing window classes keep
working, including the stream retry and the stop-return path.
"""

from lib.ui.rev2 import is_rev2


def skin_for(xml_name):
    """``HomeWindow.xml`` stays put on RevRivulet. Rev2 loads ``Rev2HomeWindow.xml``."""
    if not xml_name or not is_rev2():
        return xml_name
    if xml_name.startswith('Rev2'):
        return xml_name
    return 'Rev2' + xml_name
