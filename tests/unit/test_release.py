"""Unit tests for .github/scripts/release.py, the helpers of the release
workflow: the checks on the version and the changelog, the release notes and
the absolute links of the README that goes to PyPI.
"""
import importlib.util
import os
import unittest

import support

SCRIPT = os.path.join(support.REPO, ".github", "scripts", "release.py")
_spec = importlib.util.spec_from_file_location("release", SCRIPT)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

CHANGELOG = """# Changelog

Intro text.

## 0.9.0 - Unreleased

- Something new.

## 0.8.0 - 2027-01-12

First release.

- One thing.
- Another thing.
"""


class ChangelogTest(unittest.TestCase):
    def test_sections_with_their_label_and_body(self):
        sections = release.changelog_sections(CHANGELOG)
        self.assertEqual(list(sections), ["0.9.0", "0.8.0"])
        self.assertEqual(sections["0.9.0"], ("Unreleased", "- Something new."))
        self.assertEqual(sections["0.8.0"][0], "2027-01-12")
        self.assertEqual(sections["0.8.0"][1], "First release.\n\n- One thing.\n- Another thing.")

    def test_two_sections_for_one_version_are_an_error(self):
        with self.assertRaises(release.ReleaseError):
            release.changelog_sections("## 0.8.0 - Unreleased\n\n## 0.8.0 - 2027-01-12\n")

    def test_notes_take_the_tag_or_the_version(self):
        self.assertEqual(release.notes(CHANGELOG, "v0.8.0"), release.notes(CHANGELOG, "0.8.0"))
        self.assertTrue(release.notes(CHANGELOG, "v0.8.0").startswith("First release."))
        with self.assertRaises(release.ReleaseError):
            release.notes(CHANGELOG, "v0.7.0")

    def test_the_changelog_of_the_repository_is_well_formed(self):
        with open(os.path.join(support.REPO, "CHANGELOG.md"), encoding="utf-8") as fh:
            release.check(release.package_version(support.REPO), fh.read())


class CheckTest(unittest.TestCase):
    def test_without_a_tag_only_the_format_is_checked(self):
        release.check("0.7.0", CHANGELOG)

    def test_a_tag_that_matches_a_dated_section_passes(self):
        release.check("0.8.0", CHANGELOG, "v0.8.0")

    def test_a_tag_that_does_not_match_the_version_fails(self):
        with self.assertRaisesRegex(release.ReleaseError, "does not match"):
            release.check("0.8.0", CHANGELOG, "v0.8.1")

    def test_a_version_still_unreleased_cannot_be_published(self):
        with self.assertRaisesRegex(release.ReleaseError, "no date"):
            release.check("0.9.0", CHANGELOG, "v0.9.0")

    def test_a_version_missing_from_the_changelog_cannot_be_published(self):
        with self.assertRaisesRegex(release.ReleaseError, "no section"):
            release.check("0.7.0", CHANGELOG, "v0.7.0")

    def test_a_heading_without_a_date_or_unreleased_is_an_error(self):
        for heading in ("## 0.8.0", "## 0.8.0 - soon", "## 0.8.0 - 12/01/2027"):
            with self.subTest(heading=heading), self.assertRaises(release.ReleaseError):
                release.check("0.8.0", heading + "\n\nText.\n")

    def test_a_changelog_without_sections_is_an_error(self):
        with self.assertRaises(release.ReleaseError):
            release.check("0.8.0", "# Changelog\n\nNothing yet.\n")


class ReadmeLinksTest(unittest.TestCase):
    REF = "v0.8.0"
    BLOB = "https://github.com/abstracta/cobalto/blob/v0.8.0/"
    TREE = "https://github.com/abstracta/cobalto/tree/v0.8.0/"
    RAW = "https://raw.githubusercontent.com/abstracta/cobalto/v0.8.0/"

    def rewrite(self, text):
        return release.absolute_links(text, self.REF)

    def test_a_link_to_a_file_keeps_its_anchor(self):
        self.assertEqual(self.rewrite("[First suite](docs/reference.md#first-suite)"),
                         "[First suite](%sdocs/reference.md#first-suite)" % self.BLOB)

    def test_a_link_to_a_folder_goes_to_its_tree(self):
        self.assertEqual(self.rewrite("[examples/](examples/)"), "[examples/](%sexamples/)" % self.TREE)

    def test_an_image_gets_the_raw_file(self):
        self.assertEqual(self.rewrite("![demo](vscode-cobalto/images/demo.gif)"),
                         "![demo](%svscode-cobalto/images/demo.gif)" % self.RAW)

    def test_html_src_and_srcset_get_the_raw_file(self):
        html = '<source srcset="docs/logo/white.svg"><img src="./docs/logo/logo.svg" alt="Cobalto">'
        self.assertEqual(self.rewrite(html),
                         '<source srcset="%sdocs/logo/white.svg"><img src="%sdocs/logo/logo.svg" alt="Cobalto">'
                         % (self.RAW, self.RAW))

    def test_a_path_from_the_root_of_the_repository(self):
        self.assertEqual(self.rewrite("[license](/LICENSE)"), "[license](%sLICENSE)" % self.BLOB)

    def test_urls_and_anchors_are_left_alone(self):
        text = "[Abstracta](https://abstracta.us), [up](#roadmap), [mail](mailto:a@example.com)"
        self.assertEqual(self.rewrite(text), text)

    def test_a_link_text_with_code_and_brackets(self):
        self.assertEqual(self.rewrite("[`a [b]`](docs/design.md)"), "[`a [b]`](%sdocs/design.md)" % self.BLOB)

    def test_nothing_relative_is_left_in_the_readme_of_the_repository(self):
        with open(os.path.join(support.REPO, "README.md"), encoding="utf-8") as fh:
            rewritten = self.rewrite(fh.read())
        self.assertEqual(release.relative_links(rewritten), [])

    def test_relative_links_are_listed(self):
        self.assertEqual(release.relative_links('[a](docs/a.md) [b](https://x.org) <img src="c.png">'),
                         ["docs/a.md", "c.png"])


if __name__ == "__main__":
    unittest.main()
