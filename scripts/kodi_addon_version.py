# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Kodi addon version compare, matching xbmc/addons/AddonVersion.cpp.

Kodi splits on the first '-' into an upstream version and a Debian revision,
lowercases both, then compares components the Debian way: a digit run is one
integer, '~' sorts before anything, and a version that still has characters
left is newer unless the remainder starts with '~'.

That is why 0.30.1 < 0.30.1-ui.1 < 0.30.1.rev1, and why 0.30.1.rev9 <
0.30.1.rev10. A string sort gets the last pair backwards, so the publisher
must use this comparator or Kodi will ignore a new zip.
"""

_VALID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.+_@~")


def _invalid(text):
    return any(ch not in _VALID for ch in text)


def split_version(version):
    """Return (epoch, upstream, revision) the way CAddonVersion does."""
    text = (version or "").strip().lower()
    if not text:
        text = "0.0.0"
    epoch = 0
    if ":" in text:
        epoch_text, text = text.split(":", 1)
        if epoch_text.isdigit():
            epoch = int(epoch_text)
        else:
            epoch = 0
    revision = ""
    hyphen = text.find("-")
    if hyphen != -1:
        revision = text[hyphen + 1 :]
        text = text[:hyphen]
        if _invalid(revision):
            revision = ""
    if _invalid(text):
        text = "0.0.0"
    return epoch, text, revision


def compare_component(left, right):
    """Debian component compare. Returns -1, 0, or 1."""
    ia = 0
    ib = 0
    na = len(left)
    nb = len(right)
    while ia < na and ib < nb:
        while ia < na and ib < nb and not left[ia].isdigit() and not right[ib].isdigit():
            if left[ia] != right[ib]:
                if left[ia] == "~":
                    return -1
                if right[ib] == "~":
                    return 1
                return -1 if left[ia] < right[ib] else 1
            ia += 1
            ib += 1
        if ia < na and ib < nb and (not left[ia].isdigit() or not right[ib].isdigit()):
            if left[ia] == "~":
                return -1
            if right[ib] == "~":
                return 1
            return -1 if left[ia].isdigit() else 1
        ja = ia
        while ja < na and left[ja].isdigit():
            ja += 1
        jb = ib
        while jb < nb and right[jb].isdigit():
            jb += 1
        num_a = int(left[ia:ja] or "0")
        num_b = int(right[ib:jb] or "0")
        if num_a != num_b:
            return -1 if num_a < num_b else 1
        ia = ja
        ib = jb
    if ia == na and ib == nb:
        return 0
    if ia < na:
        return -1 if left[ia] == "~" else 1
    return 1 if right[ib] == "~" else -1


def kodi_cmp(left, right):
    """Return -1, 0, or 1 if `left` is older, equal, or newer than `right`."""
    epoch_l, up_l, rev_l = split_version(left)
    epoch_r, up_r, rev_r = split_version(right)
    if epoch_l != epoch_r:
        return -1 if epoch_l < epoch_r else 1
    upstream = compare_component(up_l, up_r)
    if upstream:
        return upstream
    return compare_component(rev_l, rev_r)


def kodi_lt(left, right):
    return kodi_cmp(left, right) < 0


def bump_rev(version):
    """Next .revN strictly after `version` under Kodi's comparator.

    0.30.1 becomes 0.30.1.rev1. 0.30.1.rev9 becomes 0.30.1.rev10. A hyphenated
    revision such as 0.30.1-ui.1 grows a .rev1 on the end (0.30.1-ui.1.rev1),
    which Kodi treats as a newer Debian revision of the same upstream.
    """
    text = (version or "").strip()
    dot = text.rfind(".rev")
    if dot != -1 and text[dot + 4 :].isdigit():
        # Only the trailing .revN counts. 1.rev2.rev3 is not a form we emit.
        return "%s.rev%d" % (text[:dot], int(text[dot + 4 :]) + 1)
    return text + ".rev1"


def ensure_newer(current, published):
    """A version Kodi will treat as an update of `published`.

    `published` None means nothing is on the repository yet, so `current`
    ships as-is. Otherwise the result is strictly newer than both.
    """
    if not published or kodi_lt(published, current):
        return current
    version = published
    # Bound the loop: each bump adds one integer, and Kodi orders those.
    for _ in range(10000):
        version = bump_rev(version)
        if kodi_lt(published, version) and kodi_lt(current, version):
            return version
    raise RuntimeError("could not bump %r past %r" % (current, published))
