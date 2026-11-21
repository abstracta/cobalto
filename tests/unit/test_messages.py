"""Unit tests for cobalto.messages: the error object of the JSON outputs and
the line of a compile error."""
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from cobalto.messages import CobaltoError, compile_error_line


class CobaltoErrorTest(unittest.TestCase):
    def test_error_object_has_the_code_and_the_message(self):
        e = CobaltoError("E202", rc=1)
        self.assertEqual(e.as_json(), {"code": "CBLT-E202", "message": "the build failed (exit 1)"})

    def test_extra_fields_go_only_to_the_error_object(self):
        e = CobaltoError("E202", extra={"output": "cobc: error\n"}, rc=1)
        self.assertEqual(e.as_json(), {"code": "CBLT-E202", "message": "the build failed (exit 1)",
                                       "output": "cobc: error\n"})
        self.assertEqual(str(e), "CBLT-E202: the build failed (exit 1)")

    def test_extra_is_a_copy(self):
        extra = {"details": []}
        e = CobaltoError("E202", extra=extra, rc=1)
        extra["output"] = "later"
        self.assertNotIn("output", e.as_json())


class CompileErrorLineTest(unittest.TestCase):
    def test_error_mapped_back_from_the_generated_cobol(self):
        line = compile_error_line({"code": "CBLT-E201", "file": "tests/CALC.cblt", "line": 12,
                                   "generated": "build/TSTCALC.cbl:40", "message": "'WS-NOSUCH' is not defined"})
        self.assertEqual(line, "CBLT-E201: compile error in tests/CALC.cblt:12 "
                               "(generated at build/TSTCALC.cbl:40): 'WS-NOSUCH' is not defined")

    def test_error_in_a_file_that_is_not_generated(self):
        line = compile_error_line({"code": "CBLT-E201", "file": "src/CALC.cbl", "line": 7, "generated": None,
                                   "message": "syntax error"})
        self.assertEqual(line, "CBLT-E201: compile error in src/CALC.cbl:7: syntax error")


if __name__ == "__main__":
    unittest.main()
