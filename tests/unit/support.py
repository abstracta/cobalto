"""Shared setup for the unit tests of the Cobalto CLI.

Importing this module puts <repo>/src on sys.path, so the tests run against
the working copy without installing the package:

    python3 -m unittest discover -s tests/unit -v

It also offers helpers to write small synthetic sources in a temporary
folder. Nothing here needs a COBOL compiler.
"""
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
EXAMPLES = os.path.join(REPO, "examples")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def fixed(text):
    """Fixed-format COBOL from a readable block.

    The block is dedented and its first line becomes line 1. Column 1 of the
    block is Area A (column 8 of the source); a line that starts with "*", "/"
    or "-" has that character placed in the indicator column (7). Lines that
    need an exact layout (sequence area, columns 73-80) are written by hand in
    the tests instead.
    """
    out = []
    for line in textwrap.dedent(text).strip("\n").splitlines():
        if not line.strip():
            out.append("")
        elif line[0] in "*/-":
            out.append(" " * 6 + line)
        else:
            out.append(" " * 7 + line)
        if len(out[-1]) > 72:
            raise AssertionError(f"test source goes past column 72 and would be cut: {line.strip()!r}")
    return "\n".join(out) + "\n"


DEFAULT_DATA = """
    01  WS-A                      PIC 9(3).
    01  WS-B                      PIC 9(3).
    01  WS-C                      PIC 9(3).
    01  WS-FLAG                   PIC X.
        88  WS-DONE               VALUE "Y".
"""


def blocks(*parts):
    """Joins blocks of text into one, each dedented on its own, so that a
    shared header and the lines of one test can be indented differently."""
    return "\n".join(x for x in (textwrap.dedent(p).strip("\n") for p in parts) if x) + "\n"


def program_text(procedure, data=DEFAULT_DATA, program_id="SAMPLE", using=""):
    """A complete program as a block for fixed(): the header, a
    WORKING-STORAGE block (a few made-up fields by default) and the given
    PROCEDURE DIVISION body."""
    return blocks("IDENTIFICATION DIVISION.", f"PROGRAM-ID. {program_id}.",
                  "DATA DIVISION.", "WORKING-STORAGE SECTION.", data,
                  "PROCEDURE DIVISION" + (" USING " + using if using else "") + ".",
                  procedure)


def line_of(text, fragment):
    """1-based number of the only line of text that contains fragment."""
    found = [n for n, line in enumerate(text.splitlines(), 1) if fragment in line]
    if len(found) != 1:
        raise AssertionError(f"{fragment!r} appears on {len(found)} lines, expected exactly one")
    return found[0]


def statement(prog, verb, nth=0):
    """The nth statement (in source order) of a parsed program with that verb."""
    found = [st for st in prog.statements if st.verb == verb]
    if nth >= len(found):
        raise AssertionError(f"the program has {len(found)} {verb} statement(s), asked for number {nth + 1}")
    return found[nth]


def text_of(prog, st):
    """The tokens of a statement joined by one space."""
    return " ".join(t.text for t in prog.tokens[st.start:st.end])


class TempDirTestCase(unittest.TestCase):
    """A test case with a temporary folder that is removed afterwards."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cobalto-unit-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, text):
        """Writes text to name (relative to the temporary folder) and returns
        the path."""
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def write_cobol(self, text, name="PROG.cbl"):
        """Writes a block (see fixed) as a fixed-format source and returns
        (path, source text), the text being what line_of searches."""
        source = fixed(text)
        return self.write(name, source), source

    def parse(self, text, name="PROG.cbl", copy_dirs=None):
        """Parses a block (see fixed) and returns (Program, source text)."""
        from cobalto.cobparse import Program
        path, source = self.write_cobol(text, name)
        return Program(path, copy_dirs), source

    def parse_body(self, procedure, **kw):
        """Parses a program built by program_text around a PROCEDURE
        DIVISION body and returns (Program, source text)."""
        return self.parse(program_text(procedure, **kw))
