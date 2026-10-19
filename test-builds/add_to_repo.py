"""Add stock plugin.video.rivulet (test build) to the gh-pages Kodi repo
without re-serialising the existing entries (their bytes stay identical)."""
import hashlib, re, shutil, sys, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

repo, zip_path = Path(sys.argv[1]), Path(sys.argv[2])
# Optional: a build number appended to the addon's version ("0.32.0" ->
# "0.32.0.<n>") in the published zip only, so every refresh is a new
# version Kodi fetches and offers as an update instead of reusing its
# cached package. The PR branch's own addon.xml is not changed.
suffix = sys.argv[3] if len(sys.argv) > 3 else ""
AID = "plugin.video.rivulet"
if suffix:
    assert re.fullmatch(r"\d+", suffix), suffix
    with zipfile.ZipFile(str(zip_path)) as src:
        raw = src.read(AID + "/addon.xml").decode("utf-8")
        base = ET.fromstring(raw).get("version")
        bumped = base + "." + suffix
        head = re.search(r"<addon\b[^>]*>", raw)
        tag = head.group(0)
        assert tag.count('version="%s"' % base) == 1, tag
        raw = raw[: head.start()] + tag.replace('version="%s"' % base, 'version="%s"' % bumped) + raw[head.end():]
        out_path = zip_path.with_name("bumped.zip")
        with zipfile.ZipFile(str(out_path), "w") as out:
            for info in src.infolist():
                data = raw.encode("utf-8") if info.filename == AID + "/addon.xml" else src.read(info)
                out.writestr(info, data)
    zip_path = out_path
    print("version", base, "->", bumped)
zf = zipfile.ZipFile(str(zip_path))
raw = zf.read(AID + "/addon.xml").decode("utf-8")
el = ET.fromstring(raw)
assert el.get("id") == AID
ver = el.get("version")
block = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", raw).rstrip()

d = repo / AID
if d.exists():
    shutil.rmtree(str(d))
d.mkdir()
name = "%s-%s.zip" % (AID, ver)
shutil.copyfile(str(zip_path), str(d / name))
shutil.copyfile(str(zip_path), str(repo / (AID + ".zip")))
(d / "addon.xml").write_text(raw, encoding="utf-8")
(d / "icon.png").write_bytes(zf.read(AID + "/resources/icon.png"))
(d / "fanart.jpg").write_bytes(zf.read(AID + "/resources/fanart.jpg"))
for a in el.find("extension[@point='xbmc.addon.metadata']").find("assets"):
    rel = (a.text or "").strip()
    if rel:
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(zf.read(AID + "/" + rel))
(d / "index.html").write_text(
    "<!DOCTYPE html>\n<meta charset=\"utf-8\">\n<title>%s %s</title>\n"
    "<h1>%s %s</h1>\n<ul>\n<li><a href=\"%s\">%s</a></li>\n"
    "<li><a href=\"addon.xml\">addon.xml</a></li>\n</ul>\n" % (AID, ver, AID, ver, name, name),
    encoding="utf-8")

ax = repo / "addons.xml"
text = ax.read_text(encoding="utf-8")
# drop any previous copy of this addon's entry (re-runs stay idempotent)
text = re.sub(r'<addon id="%s".*?</addon>(?=<addon |</addons>)' % re.escape(AID), "", text, flags=re.S)
assert text.endswith("</addons>")
text = text[: -len("</addons>")] + block + "</addons>"
ax.write_text(text, encoding="utf-8")
ids = [a.get("id") for a in ET.parse(str(ax)).getroot()]
print("addons.xml ids:", ids)
(repo / "addons.xml.md5").write_text(hashlib.md5(ax.read_bytes()).hexdigest(), encoding="utf-8")

idx = repo / "index.html"
h = idx.read_text(encoding="utf-8")
link = '<p><a href="%s.zip">%s.zip</a> (test build)</p>\n' % (AID, AID)
if link not in h:
    h = h.replace("</body>", link + "</body>")
    idx.write_text(h, encoding="utf-8")
