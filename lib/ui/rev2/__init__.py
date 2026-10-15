# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Rev2Rivulet UI.

This package is the test build's screens. It is inert unless
``lib.addonid.ADDON_ID`` is ``plugin.video.rev2rivulet``, which the
publish step stamps into a second zip. RevRivulet's entry point never
imports it.

The screens call the existing loaders, library writes and
``open_streams()``. They do not replace playback, the streaming server,
subtitle fetch, or the Stremio client.
"""

REV2_ID = "plugin.video.rev2rivulet"


def is_rev2():
    """True only inside the Rev2Rivulet zip.

    Imported at call time so a test can patch ``lib.addonid.ADDON_ID``
    without reloading every screen.
    """
    from lib.addonid import ADDON_ID
    return ADDON_ID == REV2_ID
