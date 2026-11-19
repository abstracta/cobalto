#!/usr/bin/env python3
"""Helpers for the release workflow of the CLI (.github/workflows/release.yml).

    python3 .github/scripts/release.py check [--tag vX.Y.Z]
        Prints the version of the package and checks CHANGELOG.md. With
        --tag, it also fails unless the tag is "v" plus that version and the
        version has a dated section in CHANGELOG.md.
    python3 .github/scripts/release.py notes vX.Y.Z
        Prints the body of that version's section of CHANGELOG.md, the
        notes of the GitHub release.
    python3 .github/scripts/release.py readme REF
        Rewrites the relative links and images of README.md as absolute URLs
        of the repository at REF (a tag or a commit). PyPI shows the README
        as the page of the package and does not resolve relative links.
    python3 .github/scripts/release.py relative-links FILE
        Lists the relative links left in FILE (a README, or the METADATA of
        a built wheel) and fails if there is any.

Standard library only, like the CLI.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPOSITORY = "abstracta/cobalto"

# "## 0.8.0 - 2027-01-12" or "## 0.8.0 - Unreleased"
SECTION = re.compile(r"^## (\d+\.\d+\.\d+)(?: - (.+?))?\s*$", re.M)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Markdown links and images: [text](target) and ![alt](target)
MD_LINK = re.compile(r"(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)\)")
# HTML attributes that load an image
HTML_SRC = re.compile(r'\b(src|srcset)="([^"]+)"')
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class ReleaseError(Exception):
    pass


def package_version(root=ROOT):
    with open(os.path.join(root, "src", "cobalto", "__init__.py"), encoding="utf-8") as fh:
        m = re.search(r'^__version__ = "([^"]+)"', fh.read(), re.M)
    if not m:
        raise ReleaseError("no __version__ in src/cobalto/__init__.py")
    return m.group(1)


def changelog_sections(text):
    """{version: (label, body)} of the text of a CHANGELOG.md. The label is
    what follows the dash in the heading: a date, "Unreleased" or None."""
    found = list(SECTION.finditer(text))
    sections = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        if m.group(1) in sections:
            raise ReleaseError("CHANGELOG.md has two sections for %s" % m.group(1))
        sections[m.group(1)] = (m.group(2), text[m.end():end].strip("\n"))
    return sections


def check(version, changelog, tag=None):
    """Raises ReleaseError if the changelog is malformed or, with a tag, if
    the tag does not match the version or the version has no dated section."""
    sections = changelog_sections(changelog)
    if not sections:
        raise ReleaseError('CHANGELOG.md has no section like "## X.Y.Z - YYYY-MM-DD"')
    for v, (label, _) in sections.items():
        if label is None or not (DATE.match(label) or label == "Unreleased"):
            raise ReleaseError('the heading of %s in CHANGELOG.md has to end in " - YYYY-MM-DD" '
                               'or " - Unreleased"' % v)
    if tag is None:
        return
    if tag != "v" + version:
        raise ReleaseError("the tag %s does not match the version of the package, %s" % (tag, version))
    if version not in sections:
        raise ReleaseError("CHANGELOG.md has no section for %s" % version)
    if not DATE.match(sections[version][0]):
        raise ReleaseError("the section for %s in CHANGELOG.md has no date: "
                           "replace Unreleased with the date of the release" % version)


def notes(changelog, tag):
    version = tag[1:] if tag.startswith("v") else tag
    sections = changelog_sections(changelog)
    if version not in sections:
        raise ReleaseError("CHANGELOG.md has no section for %s" % version)
    return sections[version][1] + "\n"


def is_relative(target):
    """A path in the repository: not a URL, not an anchor of the same page.
    A path that starts with "/" counts, since GitHub reads it from the root
    of the repository."""
    return not (SCHEME.match(target) or target.startswith(("#", "//")))


def absolute(target, ref, image):
    """The URL of a relative target of the README in the repository at ref:
    raw content for an image, the page on GitHub for a link."""
    path, _, fragment = target.partition("#")
    path = path[2:] if path.startswith("./") else path.lstrip("/")
    if image:
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (REPOSITORY, ref, path)
    else:
        kind = "tree" if path.endswith("/") else "blob"
        url = "https://github.com/%s/%s/%s/%s" % (REPOSITORY, kind, ref, path)
    return url + ("#" + fragment if fragment else "")


def absolute_links(text, ref):
    def md(m):
        bang, label, target = m.groups()
        if not is_relative(target):
            return m.group(0)
        return "%s[%s](%s)" % (bang, label, absolute(target, ref, image=bool(bang)))

    def html(m):
        attr, value = m.groups()
        candidates = []
        for candidate in value.split(","):
            parts = candidate.strip().split()
            if parts and is_relative(parts[0]):
                parts[0] = absolute(parts[0], ref, image=True)
            candidates.append(" ".join(parts))
        return '%s="%s"' % (attr, ", ".join(candidates))

    return HTML_SRC.sub(html, MD_LINK.sub(md, text))


def relative_links(text):
    found = [target for _, _, target in MD_LINK.findall(text) if is_relative(target)]
    for _, value in HTML_SRC.findall(text):
        found += [c.split()[0] for c in value.split(",") if c.split() and is_relative(c.split()[0])]
    return found


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("--tag")
    p = sub.add_parser("notes")
    p.add_argument("tag")
    p = sub.add_parser("readme")
    p.add_argument("ref")
    p = sub.add_parser("relative-links")
    p.add_argument("file")
    args = ap.parse_args(argv)
    changelog = os.path.join(ROOT, "CHANGELOG.md")
    try:
        if args.command == "check":
            version = package_version()
            check(version, read(changelog), args.tag)
            print(version)
        elif args.command == "notes":
            sys.stdout.write(notes(read(changelog), args.tag))
        elif args.command == "readme":
            readme = os.path.join(ROOT, "README.md")
            text = absolute_links(read(readme), args.ref)
            with open(readme, "w", encoding="utf-8") as fh:
                fh.write(text)
        elif args.command == "relative-links":
            found = relative_links(read(args.file))
            for target in found:
                print("relative link: %s" % target)
            if found:
                raise ReleaseError("%d relative links in %s" % (len(found), args.file))
    except ReleaseError as e:
        print("::error::%s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
