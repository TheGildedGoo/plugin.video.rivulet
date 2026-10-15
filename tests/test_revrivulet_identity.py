# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The fork id lives in one Python constant and the files Kodi reads itself.

The official addon id must not appear in the code that runs as this addon.
Skin XML, settings.xml and the Stream4Me bridge cannot import lib.addonid,
so they repeat the literal and this test checks them.
"""

import importlib.util
from pathlib import Path

from lib.addonid import ADDON_ID, ADDON_NAME, WORDMARK

_ROOT = Path(__file__).resolve().parents[1]
# Split so a mechanical rename of this fork's id cannot retarget the check.
_OFFICIAL_ID = "plugin.video." + "rivulet"
_SCAN_ROOTS = (
    _ROOT / "lib",
    _ROOT / "default.py",
    _ROOT / "service.py",
    _ROOT / "resources" / "settings.xml",
    _ROOT / "resources" / "skins",
    _ROOT / "resources" / "s4me_bridge",
)


def _py_files():
    for root in _SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if path.suffix in {".py", ".xml"} and "__pycache__" not in path.parts:
                yield path


def test_constant_is_the_side_by_side_id():
    assert ADDON_ID == "plugin.video.revrivulet"
    assert ADDON_NAME == "RevRivulet"
    assert WORDMARK == "RevRivulet"
    assert _OFFICIAL_ID not in ADDON_ID


def test_runtime_files_do_not_name_the_official_addon():
    offenders = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if _OFFICIAL_ID in text:
            offenders.append(str(path.relative_to(_ROOT)))
    assert not offenders, "official addon id still hardcoded:\n  " + "\n  ".join(offenders)


def test_kodi_metadata_uses_the_constant():
    addon = (_ROOT / "addon.xml").read_text(encoding="utf-8")
    assert 'id="%s"' % ADDON_ID in addon
    assert 'name="%s"' % ADDON_NAME in addon
    settings = (_ROOT / "resources" / "settings.xml").read_text(encoding="utf-8")
    assert 'section id="%s"' % ADDON_ID in settings
    assert "plugin://%s/" % ADDON_ID in settings
    skin_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (_ROOT / "resources" / "skins").rglob("*.xml")
    )
    assert "$ADDON[%s " % ADDON_ID in skin_text
    assert _OFFICIAL_ID not in skin_text
    assert WORDMARK in skin_text
    po = (_ROOT / "resources" / "language" / "resource.language.en_gb" / "strings.po").read_text(
        encoding="utf-8"
    )
    assert "# Addon id: %s" % ADDON_ID in po
    assert "Project-Id-Version: %s" % ADDON_ID in po


def test_bridge_literal_matches_the_constant():
    bridge = (_ROOT / "resources" / "s4me_bridge" / "bridge.py").read_text(encoding="utf-8")
    assert 'ADDON_ID = "%s"' % ADDON_ID in bridge
    # The shutdown header is a matched protocol string, not the addon id.
    assert "X-Rivulet-Bridge-Shutdown" in bridge


def test_repository_points_at_this_fork_pages():
    text = (_ROOT / "repository.revrivulet" / "addon.xml").read_text(encoding="utf-8")
    assert 'id="repository.revrivulet"' in text
    # Pages path is the GitHub repository name, which is still the official id.
    base = "https://thegildedgoo.github.io/%s/" % _OFFICIAL_ID
    assert base + "addons.xml" in text
    assert base + "addons.xml.md5" in text
    assert 'datadir zip="true">%s</datadir>' % base in text
    # The upstream repository definition stays pointed at upstream.
    official = (_ROOT / "repository.rivulet" / "addon.xml").read_text(encoding="utf-8")
    assert ("https://rivulet-kodi.github.io/%s/addons.xml" % _OFFICIAL_ID) in official


def test_publish_repo_imports():
    spec = importlib.util.spec_from_file_location(
        "publish_repo", _ROOT / "scripts" / "publish_repo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ADDON_ID == ADDON_ID
    assert module.PAGES_BASE.startswith("https://thegildedgoo.github.io/")
