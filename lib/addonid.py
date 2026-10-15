# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Identity of this fork.

Official Rivulet stays installed beside this addon. Skin XML, settings.xml,
addon.xml and the Stream4Me bridge cannot import this module (Kodi reads
those as data, and the bridge is launched by RunScript with only its own
directory on sys.path). Those files repeat ADDON_ID literally.
tests/test_revrivulet_identity.py fails if they drift.
"""

ADDON_ID = "plugin.video.revrivulet"
ADDON_NAME = "RevRivulet"
#: On-screen wordmark. ASCII, so it is safe in every skin font.
WORDMARK = "REVRIVULET"
