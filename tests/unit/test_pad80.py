"""Unit tests for cobalto.pad80, the converter to 80-column records."""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)
from support import TempDirTestCase

from cobalto import pad80
from cobalto.pad80 import Pad80Error, pad80_file, pad80_text

SOURCE = ("       IDENTIFICATION DIVISION.\n"
          "       PROGRAM-ID. CARDS.\n"
          "\n"
          "       PROCEDURE DIVISION.\n"
          "           GOBACK.\n")


class Pad80TextTest(unittest.TestCase):
    def test_every_line_becomes_exactly_80_characters(self):
        text, _ = pad80_text(SOURCE)
        self.assertEqual([len(line) for line in text.split("\n")[:-1]], [80] * 5)

    def test_lines_are_terminated_by_lf(self):
        text, _ = pad80_text(SOURCE)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(text.count("\n"), 5)

    def test_content_is_kept_and_padded_on_the_right(self):
        text, _ = pad80_text(SOURCE)
        self.assertEqual([line.rstrip() for line in text.splitlines()], SOURCE.splitlines())

    def test_empty_line_becomes_80_spaces(self):
        text, _ = pad80_text(SOURCE)
        self.assertEqual(text.splitlines()[2], " " * 80)

    def test_trailing_spaces_do_not_count_towards_the_length(self):
        text, warnings = pad80_text("       GOBACK." + " " * 200 + "\n")
        self.assertEqual((text, warnings), ("       GOBACK.".ljust(80) + "\n", []))

    def test_tabs_are_expanded(self):
        text, _ = pad80_text("\tGOBACK.\n")
        self.assertEqual(text, "        GOBACK.".ljust(80) + "\n")

    def test_crlf_line_ends_become_lf(self):
        text, _ = pad80_text("       GOBACK.\r\n       STOP RUN.\r\n")
        self.assertNotIn("\r", text)
        self.assertEqual(len(text), 2 * 81)

    def test_last_line_without_a_newline_is_terminated(self):
        text, _ = pad80_text("       GOBACK.")
        self.assertEqual(text, "       GOBACK.".ljust(80) + "\n")

    def test_line_of_exactly_72_columns_gives_no_warning(self):
        _, warnings = pad80_text("X" * 72 + "\n")
        self.assertEqual(warnings, [])

    def test_line_of_73_columns_warns(self):
        _, warnings = pad80_text("X" * 73 + "\n")
        self.assertEqual(len(warnings), 1)

    def test_text_in_columns_73_to_80_only_warns_with_file_and_line(self):
        text, warnings = pad80_text("       GOBACK.\n" + "X" * 72 + "CARD0002\n", "src/CARDS.cbl")
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("src/CARDS.cbl:2:"))
        self.assertEqual(text.splitlines()[1], "X" * 72 + "CARD0002")

    def test_line_of_exactly_80_columns_is_accepted(self):
        text, _ = pad80_text("X" * 80 + "\n")
        self.assertEqual(text, "X" * 80 + "\n")

    def test_line_longer_than_80_columns_is_an_error_with_file_line_and_length(self):
        with self.assertRaises(Pad80Error) as caught:
            pad80_text("       GOBACK.\n" + "X" * 81 + "\n", "src/CARDS.cbl")
        message = str(caught.exception)
        self.assertTrue(message.startswith("src/CARDS.cbl:2:"))
        self.assertIn("81 columns", message)

    def test_width_can_be_changed(self):
        text, _ = pad80_text("       GOBACK.\n", width=132)
        self.assertEqual(len(text.splitlines()[0]), 132)


class Pad80FileTest(TempDirTestCase):
    def test_writes_the_converted_file_and_returns_the_warnings(self):
        src = self.write("CARDS.cbl", SOURCE + "X" * 72 + "CARD0006\n")
        dst = os.path.join(self.tmp, "CARDS.OUT")
        warnings = pad80_file(src, dst)
        with open(dst, encoding="utf-8", newline="") as fh:
            converted = fh.read()
        self.assertEqual([len(line) for line in converted.split("\n")[:-1]], [80] * 6)
        self.assertEqual(len(warnings), 1)
        self.assertIn(":6:", warnings[0])

    def test_error_names_the_source_file(self):
        src = self.write("LONG.cbl", "X" * 90 + "\n")
        with self.assertRaises(Pad80Error) as caught:
            pad80_file(src, os.path.join(self.tmp, "LONG.OUT"))
        self.assertIn(f"{src}:1:", str(caught.exception))


class Pad80CommandTest(TempDirTestCase):
    """python3 -m cobalto.pad80 FILE... --out DIR [--upper] [--ext .CBL]"""

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["pad80"] + list(args)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as caught:
            pad80.main()
        return caught.exception.code, out.getvalue(), err.getvalue()

    def test_converts_each_file_into_the_destination_folder(self):
        one, two = self.write("one.cbl", SOURCE), self.write("two.cbl", SOURCE)
        out_dir = os.path.join(self.tmp, "kit")
        code, _, _ = self.run_main(one, two, "--out", out_dir)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(out_dir)), ["one.cbl", "two.cbl"])

    def test_upper_and_ext_change_the_name_of_the_copy(self):
        src = self.write("items.cpy", "           05  ITEM-CODE PIC X(4).\n")
        out_dir = os.path.join(self.tmp, "kit")
        code, _, _ = self.run_main(src, "--out", out_dir, "--upper", "--ext", ".lib")
        self.assertEqual((code, os.listdir(out_dir)), (0, ["ITEMS.LIB"]))

    def test_too_long_line_exits_with_1_and_says_why_on_stderr(self):
        src = self.write("long.cbl", "X" * 90 + "\n")
        code, _, err = self.run_main(src, "--out", os.path.join(self.tmp, "kit"))
        self.assertEqual(code, 1)
        self.assertIn("90 columns", err)

    def test_text_in_columns_73_to_80_warns_and_still_exits_with_0(self):
        src = self.write("cards.cbl", "X" * 72 + "CARD0001\n")
        code, _, err = self.run_main(src, "--out", os.path.join(self.tmp, "kit"))
        self.assertEqual(code, 0)
        self.assertIn("warning:", err)


if __name__ == "__main__":
    unittest.main()
