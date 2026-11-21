"""Unit tests for cobalto.runner: the compile step, its two streams taken as
one, and compile errors mapped to the line of the source that caused them,
on the console and in the JSON error object. The compiler is replaced by
the text it writes or by a shell command."""
import argparse
import contextlib
import io
import os
import types
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from cobalto.messages import CobaltoError
from cobalto.runner import compile_step, report_compile_errors, run_local, sh

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

    def test_nothing_matched_gives_the_compiler_output_of_both_streams(self):
        extra, console = self.report(compiled("cobc: something unexpected\n", "and on stdout\n"))
        self.assertEqual(extra, {"output": "cobc: something unexpected\nand on stdout\n"})
        self.assertIn("cobc: something unexpected\nand on stdout", console)

    def test_nothing_matched_and_nothing_on_stderr_gives_stdout(self):
        extra, console = self.report(compiled("", "COMPILER: 1 severe error\n"))
        self.assertEqual(extra, {"output": "COMPILER: 1 severe error\n"})
        self.assertIn("COMPILER: 1 severe error", console)

    def test_output_already_shown_with_verbose_is_not_printed_again(self):
        console = io.StringIO()
        with contextlib.redirect_stderr(console):
            extra = report_compile_errors(compiled("", "COMPILER: 1 severe error\n"), {}, LINEMAPS, shown=True)
        self.assertEqual((extra, console.getvalue()), ({"output": "COMPILER: 1 severe error\n"}, ""))


class ShTest(unittest.TestCase):
    def test_merge_puts_both_streams_in_stdout(self):
        r = sh("echo on-stdout; echo on-stderr >&2", "compile", False, capture=True, merge=True)
        self.assertEqual((sorted(r.stdout.split()), r.stderr), (["on-stderr", "on-stdout"], ""))

    def test_without_merge_the_streams_stay_apart(self):
        r = sh("echo on-stdout; echo on-stderr >&2", "run", False, capture=True)
        self.assertEqual((r.stdout, r.stderr), ("on-stdout\n", "on-stderr\n"))

    def test_verbose_compile_shows_what_the_compiler_wrote_to_either_stream(self):
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            sh("echo on-stdout; echo on-stderr >&2", "compile", True, capture=True, merge=True)
        self.assertIn("on-stdout", console.getvalue())
        self.assertIn("on-stderr", console.getvalue())


class CompileStepTest(unittest.TestCase):
    """A compiler that reports on standard output, with a notice on
    standard error."""

    COMPILE = "echo 'NOTICE: license checked' >&2; echo 'build/TSTCALC.cbl:2: error: boom'; exit 1"

    def fail(self, prof, verbose=False):
        console = io.StringIO()
        with contextlib.redirect_stderr(console), contextlib.redirect_stdout(console):
            with self.assertRaises(CobaltoError) as e:
                compile_step(dict(prof, compile=self.COMPILE), {}, LINEMAPS, verbose)
        return e.exception, console.getvalue()

    def test_errors_on_stdout_are_mapped(self):
        e, console = self.fail({})
        self.assertEqual(e.as_json()["details"][0]["file"], "tests/CALC.cblt")
        self.assertIn("CBLT-E201: compile error in tests/CALC.cblt:12", console)

    def test_unmapped_output_keeps_both_streams(self):
        e, console = self.fail({"error_regex": "^NEVER$"})
        output = e.as_json()["output"]
        self.assertIn("NOTICE: license checked", output)
        self.assertIn("build/TSTCALC.cbl:2: error: boom", output)
        self.assertEqual(console.count("error: boom"), 1)

    def test_with_verbose_the_unmapped_output_is_shown_once(self):
        _, console = self.fail({"error_regex": "^NEVER$"}, verbose=True)
        lines = console.splitlines()      # the first one is the command, echoed by -v
        self.assertTrue(lines[0].startswith("[compile] "), lines[0])
        self.assertEqual(lines[1:].count("build/TSTCALC.cbl:2: error: boom"), 1)
        self.assertEqual(lines[1:].count("NOTICE: license checked"), 1)

    def test_a_build_that_succeeds_returns_the_process(self):
        r = compile_step({"compile": "echo fine"}, {}, LINEMAPS, False)
        self.assertEqual((r.returncode, r.stdout), (0, "fine\n"))


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
