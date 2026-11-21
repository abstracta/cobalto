"""Unit tests for cobalto.runner: compile errors mapped to the line of the
source that caused them, on the console and in the JSON error object. The
compiler is replaced by the text it writes or by a shell command."""
import argparse
import contextlib
import io
import os
import types
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from cobalto.messages import CobaltoError
from cobalto.runner import report_compile_errors, run_local

GENERATED = os.path.normpath("build/TSTCALC.cbl")
# line 2 of the generated file comes from line 12 of the suite; line 1 has no origin
LINEMAPS = {GENERATED: [None, ("tests/CALC.cblt", 12)]}


def compiled(stderr="", stdout=""):
    return types.SimpleNamespace(stderr=stderr, stdout=stdout, returncode=1)


class ReportCompileErrorsTest(unittest.TestCase):
    def report(self, r, prof=None):
        console = io.StringIO()
        with contextlib.redirect_stderr(console):
            extra = report_compile_errors(r, prof or {}, LINEMAPS)
        return extra, console.getvalue()

    def test_error_in_generated_cobol_is_mapped_to_the_line_of_the_suite(self):
        extra, console = self.report(compiled("build/TSTCALC.cbl:2: error: 'WS-NOSUCH' is not defined\n"))
        self.assertEqual(extra, {"details": [{"code": "CBLT-E201", "file": "tests/CALC.cblt", "line": 12,
                                              "generated": f"{GENERATED}:2",
                                              "message": "'WS-NOSUCH' is not defined"}]})
        self.assertEqual(console, f"CBLT-E201: compile error in tests/CALC.cblt:12 (generated at {GENERATED}:2): "
                                  "'WS-NOSUCH' is not defined\n")

    def test_error_on_a_line_with_no_origin_keeps_the_generated_line(self):
        extra, _ = self.report(compiled("build/TSTCALC.cbl:1: error: bad\n"))
        self.assertEqual(extra["details"][0], {"code": "CBLT-E201", "file": GENERATED, "line": 1,
                                               "generated": None, "message": "bad"})

    def test_error_in_a_file_with_no_line_map_keeps_its_own_line(self):
        extra, _ = self.report(compiled("src/CALC.cbl:7: Error: syntax error\n"))
        self.assertEqual(extra["details"][0]["file"], os.path.normpath("src/CALC.cbl"))
        self.assertEqual((extra["details"][0]["line"], extra["details"][0]["generated"]), (7, None))

    def test_every_matching_message_is_a_detail_in_order(self):
        extra, console = self.report(compiled("build/TSTCALC.cbl:2: error: first\nwarning: not an error\n",
                                              "src/CALC.cbl:9: error: second\n"))
        self.assertEqual([d["message"] for d in extra["details"]], ["first", "second"])
        self.assertEqual(len(console.splitlines()), 2)

    def test_error_regex_of_the_profile_is_used(self):
        prof = {"error_regex": r"^\*\* (?P<file>\S+) line (?P<line>\d+): (?P<msg>.*)$"}
        extra, _ = self.report(compiled("** build/TSTCALC.cbl line 2: undefined name\n"), prof)
        self.assertEqual((extra["details"][0]["file"], extra["details"][0]["message"]),
                         ("tests/CALC.cblt", "undefined name"))

    def test_nothing_matched_gives_the_compiler_output(self):
        extra, console = self.report(compiled("cobc: something unexpected\n", "ignored\n"))
        self.assertEqual(extra, {"output": "cobc: something unexpected\n"})
        self.assertIn("cobc: something unexpected", console)

    def test_nothing_matched_and_nothing_on_stderr_gives_stdout(self):
        extra, console = self.report(compiled("", "COMPILER: 1 severe error\n"))
        self.assertEqual(extra, {"output": "COMPILER: 1 severe error\n"})
        self.assertIn("COMPILER: 1 severe error", console)


class RunLocalTest(unittest.TestCase):
    def test_a_failed_build_raises_e202_with_the_details(self):
        prof = {"compile": "echo 'build/TSTCALC.cbl:2: error: boom' >&2; exit 3"}
        a = argparse.Namespace(verbose=False, no_run=False)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(CobaltoError) as e:
                run_local(prof, a, {}, LINEMAPS)
        self.assertEqual(e.exception.code, "E202")
        self.assertEqual(e.exception.message, "the build failed (exit 3)")
        self.assertEqual(e.exception.as_json()["details"][0]["file"], "tests/CALC.cblt")


if __name__ == "__main__":
    unittest.main()
