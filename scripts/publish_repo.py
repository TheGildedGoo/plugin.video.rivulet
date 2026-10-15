# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Build the RevRivulet Kodi repository and keep its version increasing.

`.github/workflows/repo.yml` runs this on every push to main. Kodi polls
addons.xml, so the video addon's version has to be strictly newer than the
one already published or an install never updates. The bump is Kodi's
comparator (scripts/kodi_addon_version.py), not a string sort.

The streaming server is not involved here. Publishing replaces this fork's
gh-pages tree; it does not publish official plugin.video.rivulet.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.addonid import ADDON_ID, ADDON_NAME  # noqa: E402
from scripts.kodi_addon_version import ensure_newer  # noqa: E402

REPO_ID = "repository.revrivulet"
# GitHub Pages URL is the repository name, which stays plugin.video.rivulet.
# The addon id inside that site is plugin.video.revrivulet.
PAGES_BASE = "https://thegildedgoo.github.io/plugin.video.rivulet/"
VIDEO_MEMBERS = ("addon.xml", "default.py", "service.py", "resources", "lib", "LICENSE")


def addon_version(addon_xml):
    return ET.parse(str(addon_xml)).getroot().get("version")


def version_in_addons_xml(payload, addon_id):
    """The version attribute for `addon_id` in an addons.xml document, or None."""
    if not payload:
        return None
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    for addon in root.findall("addon"):
        if addon.get("id") == addon_id:
            return addon.get("version")
    return None


def published_version(ref):
    """Version of this video addon on `ref`'s addons.xml, or None if absent."""
    try:
        proc = subprocess.run(
            ["git", "show", "%s:addons.xml" % ref],
            cwd=str(ROOT),
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return version_in_addons_xml(proc.stdout, ADDON_ID)


def set_version(addon_xml, version):
    """Write `version` into addon.xml and prepend a one-line news entry."""
    text = addon_xml.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(<addon\b[^>]*\bversion=")[^"]+(")',
        lambda match: match.group(1) + version + match.group(2),
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("addon.xml has no version attribute")
    news = "v%s:\n- Updated: %s %s.\n" % (version, ADDON_NAME, version)
    updated, count = re.subn(r"<news>", "<news>" + news, updated, count=1)
    if count != 1:
        raise SystemExit("addon.xml has no <news> element")
    addon_xml.write_text(updated, encoding="utf-8")


def bump_addon_xml(published):
    """Raise addon.xml when `published` is missing-or-newer-or-equal. Return the version."""
    addon_xml = ROOT / "addon.xml"
    current = addon_version(addon_xml)
    chosen = ensure_newer(current, published)
    if chosen != current:
        set_version(addon_xml, chosen)
    return chosen


def _add_path(zf, source, arcname):
    source = Path(source)
    if source.is_file():
        zf.write(str(source), arcname.replace("\\", "/"))
        return
    for dirpath, dirnames, filenames in os.walk(str(source)):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for filename in filenames:
            if filename.endswith(".pyc"):
                continue
            full = Path(dirpath) / filename
            rel = full.relative_to(source)
            arc = str(Path(arcname) / rel).replace("\\", "/")
            zf.write(str(full), arc)


def _zip_members(destination, prefix, members):
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(str(destination), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            _add_path(zf, ROOT / member, "%s/%s" % (prefix, member))


def _zip_dir(destination, folder, prefix):
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(str(destination), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _add_path(zf, folder, prefix)


def _read_from_zip(zip_path, name):
    with zipfile.ZipFile(str(zip_path)) as zf:
        return zf.read(name)


def _write_folder_index(folder, addon_id, version, zip_name):
    (folder / "index.html").write_text(
        "<!DOCTYPE html>\n<meta charset=\"utf-8\">\n<title>%s %s</title>\n"
        "<h1>%s %s</h1>\n<ul>\n<li><a href=\"%s\">%s</a></li>\n"
        "<li><a href=\"addon.xml\">addon.xml</a></li>\n</ul>\n"
        % (addon_id, version, addon_id, version, zip_name, zip_name),
        encoding="utf-8",
    )


def _publish_one(repo_dir, addon_id, zip_path, icon_arc, fanart_arc):
    addon_dir = repo_dir / addon_id
    addon_dir.mkdir(parents=True, exist_ok=True)
    addon_el = ET.fromstring(_read_from_zip(zip_path, "%s/addon.xml" % addon_id))
    version = addon_el.get("version")
    versioned = addon_dir / ("%s-%s.zip" % (addon_id, version))
    shutil.copyfile(str(zip_path), str(versioned))
    (addon_dir / "icon.png").write_bytes(_read_from_zip(zip_path, "%s/%s" % (addon_id, icon_arc)))
    (addon_dir / "fanart.jpg").write_bytes(
        _read_from_zip(zip_path, "%s/%s" % (addon_id, fanart_arc))
    )
    metadata = addon_el.find("extension[@point='xbmc.addon.metadata']")
    assets = metadata.find("assets") if metadata is not None else None
    for asset in list(assets) if assets is not None else []:
        rel = (asset.text or "").strip()
        if not rel:
            continue
        try:
            payload = _read_from_zip(zip_path, "%s/%s" % (addon_id, rel))
        except KeyError:
            raise SystemExit("%s declares asset %r which the zip does not carry" % (addon_id, rel))
        dest = addon_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
    _write_folder_index(addon_dir, addon_id, version, versioned.name)
    shutil.copyfile(str(versioned), str(repo_dir / ("%s.zip" % addon_id)))
    return addon_el


def build_repo(output_dir):
    """Write the gh-pages tree (addons.xml, md5, both zips, the site) to `output_dir`."""
    output = Path(output_dir)
    if output.exists():
        shutil.rmtree(str(output))
    output.mkdir(parents=True)
    site = ROOT / "site"
    if site.is_dir():
        shutil.copytree(str(site), str(output), dirs_exist_ok=True)

    staging = output / "_staging"
    staging.mkdir()
    video_zip = staging / ("%s.zip" % ADDON_ID)
    repo_zip = staging / ("%s.zip" % REPO_ID)
    _zip_members(video_zip, ADDON_ID, VIDEO_MEMBERS)
    _zip_dir(repo_zip, ROOT / REPO_ID, REPO_ID)

    addons_root = ET.Element("addons")
    addons_root.append(
        _publish_one(output, ADDON_ID, video_zip, "resources/icon.png", "resources/fanart.jpg")
    )
    addons_root.append(_publish_one(output, REPO_ID, repo_zip, "icon.png", "fanart.jpg"))
    addons_xml = output / "addons.xml"
    ET.ElementTree(addons_root).write(str(addons_xml), encoding="UTF-8", xml_declaration=True)
    digest = hashlib.md5(addons_xml.read_bytes()).hexdigest()
    (output / "addons.xml.md5").write_text(digest, encoding="utf-8")
    shutil.rmtree(str(staging))
    return output


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    bump = sub.add_parser("bump")
    bump.add_argument("--published-ref", default="origin/gh-pages")
    build = sub.add_parser("build")
    build.add_argument("--output", default=str(ROOT / "_repo"))
    args = parser.parse_args(argv)
    if args.cmd == "bump":
        published = published_version(args.published_ref)
        chosen = bump_addon_xml(published)
        print("version %s (published %s)" % (chosen, published or "none"))
        return 0
    build_repo(args.output)
    print("wrote %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
