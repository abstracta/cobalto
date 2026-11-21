"""Unit tests for cobalto.commands: what 'test' and 'report' leave in build/
when they stop with an error before compiling or reading anything. The
compile-and-run cycle needs a COBOL compiler and is covered by
tests/cli/selftest.py."""
import argparse
import json
import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from support import TempDirTestCase

from cobalto.commands import cmd_report, cmd_test, error_reports
from cobalto.messages import CobaltoError

OLD = "from an earlier run\n"
RESULTS = ("results.json", "junit.xml", "sonar-tests.xml")
COVERAGE = ("lcov.info", "coverage.xml", "sonar-coverage.xml")


class ErrorReportsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)

    def old_reports(self, build="build"):
        for name in RESULTS + COVERAGE:
            self.write(os.path.join(build, name), OLD)

    def read(self, name, build="build"):
        with open(os.path.join(self.tmp, build, name), encoding="utf-8") as fh:
            return fh.read()

    def results(self, build="build"):
        return json.loads(self.read("results.json", build))

    def fails(self, command, code, **args):
        with self.assertRaises(CobaltoError) as e:
            command(argparse.Namespace(config="cblt.json", **args))
        self.assertEqual(e.exception.code, code)
        return e.exception

    def test_test_that_stops_on_an_error_writes_it_to_the_reports(self):
        self.write("cblt.json", json.dumps({}))
        self.old_reports()
        self.fails(cmd_test, "E101", profile="nosuch")
        run = self.results()
        self.assertFalse(run["ok"])
        self.assertEqual((run["profile"], run["error"]["code"]), ("nosuch", "CBLT-E101"))
        self.assertIn("'nosuch' does not exist", run["error"]["message"])
        self.assertIn('<error message="CBLT-E101: profile', self.read("junit.xml"))
        self.assertNotIn(OLD, self.read("sonar-tests.xml"))

    def test_test_leaves_the_coverage_reports_as_they_were(self):
        self.write("cblt.json", json.dumps({}))
        self.old_reports()
        self.fails(cmd_test, "E101", profile="nosuch")
        self.assertEqual([self.read(n) for n in COVERAGE], [OLD] * len(COVERAGE))

    def test_the_error_model_goes_on_the_exception_for_json(self):
        self.write("cblt.json", json.dumps({}))
        e = self.fails(cmd_test, "E101", profile="nosuch")
        self.assertEqual(e.run, self.results())

    def test_the_details_of_a_build_failure_reach_results_json_and_junit(self):
        details = [{"code": "CBLT-E201", "file": "tests/CALC.cblt", "line": 12,
                    "generated": "build/TSTCALC.cbl:40", "message": "'WS-NOSUCH' is not defined"}]
        with self.assertRaises(CobaltoError) as e:
            with error_reports("build", "gnucobol"):
                raise CobaltoError("E202", extra={"details": details}, rc=1)
        run = self.results()
        self.assertEqual(run["error"], {"code": "CBLT-E202", "message": "the build failed (exit 1)",
                                        "details": details})
        self.assertEqual(e.exception.run, run)
        self.assertIn("CBLT-E201: compile error in tests/CALC.cblt:12", self.read("junit.xml"))

    def test_test_without_a_profile_reports_the_default_one(self):
        self.write("cblt.json", json.dumps({"tests": ["nosuch/*.cblt"]}))
        self.fails(cmd_test, "E100", profile=None, filter=None, coverage=False)
        self.assertEqual(self.results()["profile"], "gnucobol")

    def test_test_writes_the_reports_in_the_build_folder_of_the_project(self):
        self.write("cblt.json", json.dumps({"build": "out"}))
        self.old_reports("build")
        self.fails(cmd_test, "E101", profile="nosuch")
        self.assertEqual(self.results("out")["error"]["code"], "CBLT-E101")
        self.assertEqual([self.read(n, "build") for n in RESULTS], [OLD] * len(RESULTS))

    def test_test_without_cblt_json_does_not_know_the_build_folder_and_writes_nothing(self):
        self.old_reports()
        self.fails(cmd_test, "E103", profile=None)
        self.assertEqual([self.read(n) for n in RESULTS + COVERAGE], [OLD] * 6)

    def test_report_that_stops_on_an_error_writes_it_to_the_reports(self):
        self.write("cblt.json", json.dumps({}))
        self.old_reports()
        self.fails(cmd_report, "E106", manifest=None, results="CBLT_RESULTS.DAT", output=None, verbose=False)
        run = self.results()
        self.assertEqual((run["ok"], run["profile"], run["error"]["code"]), (False, None, "CBLT-E106"))
        self.assertIn('<error message="CBLT-E106: manifest', self.read("junit.xml"))
        self.assertEqual([self.read(n) for n in COVERAGE], [OLD] * len(COVERAGE))


if __name__ == "__main__":
    unittest.main()
