"""Unit tests for cobalto.reports: junit.xml and sonar-tests.xml of a run
that stopped with an error."""
import os
import unittest
import xml.etree.ElementTree as ET

import support  # noqa: F401  (puts src/ on sys.path)
from support import TempDirTestCase

from cobalto.reports import write_junit, write_sonar_tests
from cobalto.results import error_run


class ErrorRunReportsTest(TempDirTestCase):
    def run_model(self):
        return error_run("gnucobol", {"code": "CBLT-E202", "message": 'the build failed (exit 1) & "quoted"'})

    def junit(self, run):
        path = os.path.join(self.tmp, "junit.xml")
        write_junit(run, path)
        return ET.parse(path).getroot()

    def test_junit_has_one_suite_with_one_error_named_after_the_code(self):
        root = self.junit(self.run_model())
        suites = root.findall("testsuite")
        self.assertEqual([(s.get("name"), s.get("tests"), s.get("errors"), s.get("failures")) for s in suites],
                         [("cobalto", "1", "1", "0")])
        case = suites[0].find("testcase")
        self.assertEqual((case.get("classname"), case.get("name")), ("cobalto", "CBLT-E202"))

    def test_junit_error_carries_the_code_and_the_message(self):
        error = self.junit(self.run_model()).find("testsuite/testcase/error")
        self.assertEqual(error.get("type"), "CBLT-E202")
        self.assertEqual(error.get("message"), 'CBLT-E202: the build failed (exit 1) & "quoted"')

    def test_junit_error_without_details_has_no_text(self):
        error = self.junit(self.run_model()).find("testsuite/testcase/error")
        self.assertIsNone(error.text)

    def test_junit_error_of_a_build_failure_lists_each_compile_error(self):
        run = self.run_model()
        run["error"]["details"] = [
            {"code": "CBLT-E201", "file": "tests/CALC.cblt", "line": 12, "generated": "build/TSTCALC.cbl:40",
             "message": "'WS-NOSUCH' is not defined"},
            {"code": "CBLT-E201", "file": "src/CALC.cbl", "line": 7, "generated": None,
             "message": "syntax error, unexpected ]]>"}]
        error = self.junit(run).find("testsuite/testcase/error")
        self.assertEqual(error.text.splitlines(), [
            "CBLT-E201: compile error in tests/CALC.cblt:12 (generated at build/TSTCALC.cbl:40): "
            "'WS-NOSUCH' is not defined",
            "CBLT-E201: compile error in src/CALC.cbl:7: syntax error, unexpected ]]>"])

    def test_junit_error_of_a_build_failure_without_details_holds_the_compiler_output(self):
        run = self.run_model()
        run["error"]["output"] = "cobc: error: something the profile could not map\n"
        error = self.junit(run).find("testsuite/testcase/error")
        self.assertEqual(error.text, "cobc: error: something the profile could not map\n")

    def test_junit_of_a_run_without_error_has_no_cobalto_suite(self):
        run = self.run_model()
        del run["error"]
        self.assertEqual(self.junit(run).findall("testsuite"), [])

    def test_sonar_report_of_an_error_has_no_files(self):
        path = os.path.join(self.tmp, "sonar-tests.xml")
        write_sonar_tests(self.run_model(), path)
        root = ET.parse(path).getroot()
        self.assertEqual((root.tag, root.get("version"), list(root)), ("testExecutions", "1", []))


if __name__ == "__main__":
    unittest.main()
