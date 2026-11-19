"""Unit tests for cobalto.results: reading the records of the driver and the run model.

The records are written by hand in the layout the COBOL library uses:
T|suite, A|status|number|kind(8)|expected(60)|actual(60)|message(60), E|suite.
"""
import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from support import TempDirTestCase

from cobalto import results
from cobalto.messages import SCHEMA, VERSION
from cobalto.model import Generated, SuiteRef
from cobalto.results import build_run, parse_results


def assert_record(status, number, kind, expected="", actual="", message=""):
    """An A record with its fields at their fixed positions."""
    return f"A|{status}|{number:05d}|{kind:<8}|{expected:<60}|{actual:<60}|{message:<60}"


def case_record(name, status="C"):
    return assert_record(status, 0, "CASE", name)


RATES = ["T|TSTRATES",
         case_record("large amount gets the top rate"),
         assert_record("P", 1, "EQN", "1600", "1600", "EXPECT WS-RESULT TO BE NUMERIC 1600"),
         assert_record("F", 2, "EQ", "PREMIUM", "BASIC", "EXPECT WS-CATEGORY TO BE 'PREMIUM'"),
         case_record("pending: negative amounts", status="I"),
         case_record("small amount is unchanged"),
         assert_record("P", 3, "EQN", "10", "10", "EXPECT WS-RESULT TO BE NUMERIC 10"),
         "E|TSTRATES"]


class ParseResultsTest(unittest.TestCase):
    def setUp(self):
        self.suites = parse_results(RATES)
        self.suite = self.suites[0]

    def test_t_record_opens_a_suite(self):
        self.assertEqual([s["name"] for s in self.suites], ["TSTRATES"])

    def test_e_record_marks_the_suite_as_ended(self):
        self.assertTrue(self.suite["ended"])

    def test_e_record_carries_what_the_suite_counted(self):
        suite = parse_results(RATES[:-1] + ["E|TSTRATES                      |00003|00001"])[0]
        self.assertEqual((suite["asserts"], suite["failed"]), (3, 1))

    def test_e_record_without_counts_still_ends_the_suite(self):
        self.assertTrue(self.suite["ended"])
        self.assertNotIn("asserts", self.suite)

    def test_suite_without_e_record_did_not_end(self):
        self.assertFalse(parse_results(RATES[:-1])[0]["ended"])

    def test_case_records_open_the_test_cases_in_order(self):
        self.assertEqual([c["name"] for c in self.suite["cases"]],
                         ["large amount gets the top rate", "pending: negative amounts", "small amount is unchanged"])

    def test_status_i_marks_an_ignored_case(self):
        self.assertEqual([c["ignored"] for c in self.suite["cases"]], [False, True, False])

    def test_asserts_belong_to_the_case_that_was_open(self):
        self.assertEqual([[a["nr"] for a in c["asserts"]] for c in self.suite["cases"]], [[1, 2], [], [3]])

    def test_assert_fields_are_trimmed(self):
        self.assertEqual(self.suite["cases"][0]["asserts"][1],
                         {"status": "F", "nr": 2, "kind": "EQ", "exp": "PREMIUM", "act": "BASIC",
                          "msg": "EXPECT WS-CATEGORY TO BE 'PREMIUM'"})

    def test_pipe_inside_a_value_does_not_shift_the_fields(self):
        records = ["T|TSTPIPE", case_record("values with pipes"),
                   assert_record("F", 1, "EQ", "A|B", "C|D|E", "EXPECT WS-TEXT TO BE 'A|B'"), "E|TSTPIPE"]
        found = parse_results(records)[0]["cases"][0]["asserts"][0]
        self.assertEqual((found["exp"], found["act"], found["msg"]), ("A|B", "C|D|E", "EXPECT WS-TEXT TO BE 'A|B'"))

    def test_record_with_trailing_spaces_trimmed_is_read_the_same(self):
        trimmed = [r.rstrip() for r in RATES]
        self.assertEqual(parse_results(trimmed), self.suites)

    def test_record_that_is_not_in_fixed_positions_is_split_by_the_separator(self):
        records = ["T|TSTFREE", "A|C|0|CASE|compact case", "A|F|7|EQ|left|right|why", "E|TSTFREE"]
        case = parse_results(records)[0]["cases"][0]
        self.assertEqual(case["name"], "compact case")
        self.assertEqual(case["asserts"], [{"status": "F", "nr": 7, "kind": "EQ", "exp": "left",
                                            "act": "right", "msg": "why"}])

    def test_asserts_before_any_case_go_to_a_case_named_after_the_suite(self):
        records = ["T|TSTOLD", assert_record("P", 1, "EQ", "A", "A", "first"),
                   assert_record("P", 2, "EQ", "B", "B", "second"), "E|TSTOLD"]
        cases = parse_results(records)[0]["cases"]
        self.assertEqual([(c["name"], len(c["asserts"])) for c in cases], [("TSTOLD", 2)])

    def test_suite_without_records_has_no_cases(self):
        self.assertEqual(parse_results(["T|TSTEMPTY", "E|TSTEMPTY"])[0]["cases"], [])

    def test_several_suites_keep_their_own_cases(self):
        records = RATES + ["T|TSTOTHER", case_record("another case"), "E|TSTOTHER"]
        self.assertEqual([(s["name"], len(s["cases"])) for s in parse_results(records)],
                         [("TSTRATES", 3), ("TSTOTHER", 1)])

    def test_case_of_a_new_suite_does_not_inherit_the_previous_one(self):
        records = RATES[:-1] + ["T|TSTOTHER", assert_record("P", 9, "EQ", "A", "A", "loose"), "E|TSTOTHER"]
        other = parse_results(records)[1]
        self.assertEqual([c["name"] for c in other["cases"]], ["TSTOTHER"])

    def test_coverage_and_summary_records_are_ignored(self):
        self.assertEqual(parse_results(RATES + ["C|RATES|1|3", "S|3|3|1"]), self.suites)

    def test_records_before_the_first_suite_are_ignored(self):
        self.assertEqual(parse_results([assert_record("P", 1, "EQ", "A", "A", "stray"), "E|NOSUITE"] + RATES),
                         self.suites)

    def test_no_records_no_suites(self):
        self.assertEqual(parse_results([]), [])


class TruncatedAssertsTest(unittest.TestCase):
    def test_complete_records_are_not_reported(self):
        self.assertEqual(results.truncated_asserts(RATES), [])

    def test_complete_record_with_empty_fields_and_no_padding_is_not_reported(self):
        record = assert_record("P", 1, "EQ", "", "", "").rstrip()
        self.assertEqual(len(record), 141)
        self.assertEqual(results.truncated_asserts([record]), [])

    def test_record_cut_before_the_message_reports_its_length(self):
        cut = assert_record("F", 2, "EQ", "PREMIUM", "BASIC", "message")[:109]
        self.assertEqual(results.truncated_asserts([RATES[2], cut]), [109])

    def test_other_records_are_never_reported(self):
        self.assertEqual(results.truncated_asserts(["T|TSTRATES", "C|RATES|1|3", "E|TSTRATES" + " " * 40]), [])


class ReadRecordsTest(TempDirTestCase):
    def write_bytes(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_missing_file_is_none(self):
        missing = os.path.join(self.tmp, "nothing.txt")
        self.assertIsNone(results.read_records(missing, "lines"))
        self.assertIsNone(results.read_results(missing, "lines"))

    def test_lines_format_gives_one_record_per_line(self):
        path = self.write_bytes("results.txt", b"T|TSTRATES\nE|TSTRATES\n")
        self.assertEqual(results.read_records(path, "lines"), ["T|TSTRATES", "E|TSTRATES"])

    def test_blank_lines_are_dropped(self):
        path = self.write_bytes("results.txt", b"T|TSTRATES\n\n   \nE|TSTRATES\n")
        self.assertEqual(results.read_records(path, "lines"), ["T|TSTRATES", "E|TSTRATES"])

    def test_fixed200_without_separators_is_cut_every_200_bytes(self):
        data = "T|TSTRATES".ljust(200) + "E|TSTRATES".ljust(200)
        path = self.write_bytes("results.dat", data.encode("latin-1"))
        self.assertEqual(results.read_records(path, "fixed200"), ["T|TSTRATES".ljust(200), "E|TSTRATES".ljust(200)])

    def test_fixed200_that_arrived_with_line_breaks_is_read_by_lines(self):
        path = self.write_bytes("results.dat", b"T|TSTRATES   \nE|TSTRATES\n")
        self.assertEqual(results.read_records(path, "fixed200"), ["T|TSTRATES   ", "E|TSTRATES"])

    def test_read_records_keeps_the_padding_and_read_results_removes_it(self):
        path = self.write_bytes("results.txt", b"T|TSTRATES     \n")
        self.assertEqual(results.read_records(path, "lines"), ["T|TSTRATES     "])
        self.assertEqual(results.read_results(path, "lines"), ["T|TSTRATES"])

    def test_bytes_outside_ascii_do_not_break_the_reading(self):
        path = self.write_bytes("results.txt", b"T|TSTRATES\nA|F|00001|EQ      |caf\xe9\n")
        self.assertEqual(results.read_results(path, "lines")[1], "A|F|00001|EQ      |caf\xe9")


class SplitOutputTest(unittest.TestCase):
    OUTPUT = "\n".join(["start-up banner",
                        "CBLT-T|TSTRATES",
                        "suite level line",
                        "CBLT-C|large amount gets the top rate   ",
                        "RATE=20",
                        "CBLT-C|small amount is unchanged",
                        "CBLT-T|TSTOTHER",
                        "CBLT-C|another case",
                        "from the other suite"])

    def setUp(self):
        self.out = results.split_output(self.OUTPUT)

    def test_lines_after_a_case_marker_belong_to_that_case(self):
        self.assertEqual(self.out[("TSTRATES", "large amount gets the top rate")], ["RATE=20"])

    def test_case_without_output_has_an_empty_list(self):
        self.assertEqual(self.out[("TSTRATES", "small amount is unchanged")], [])

    def test_lines_before_the_first_case_belong_to_the_suite(self):
        self.assertEqual(self.out[("TSTRATES", None)], ["suite level line"])

    def test_new_suite_starts_its_own_cases(self):
        self.assertEqual(self.out[("TSTOTHER", "another case")], ["from the other suite"])

    def test_lines_before_the_first_suite_are_dropped(self):
        self.assertNotIn("start-up banner", [line for lines in self.out.values() for line in lines])


class BuildRunTest(unittest.TestCase):
    def run_model(self, records=RATES, suites=None, outputs=None, rc=0, **generated):
        gen = Generated(suites=[SuiteRef("TSTRATES", "tests/RATES.cblt", "Rates by amount")]
                        if suites is None else suites, **generated)
        return build_run(gen, parse_results(records), outputs or {}, rc, records, "gnucobol")

    def test_header_of_the_run(self):
        run = self.run_model()
        self.assertEqual((run["schema"], run["cobalto"], run["profile"], run["binary_exit"], run["coverage"]),
                         (SCHEMA, VERSION, "gnucobol", 0, None))

    def test_totals(self):
        self.assertEqual(self.run_model()["totals"],
                         {"cases": 3, "asserts": 3, "failed_asserts": 1, "failed_cases": 1, "skipped": 1,
                          "errors": 0, "interface": 0, "internal": 0})

    def test_run_with_a_failed_assert_is_not_ok(self):
        self.assertFalse(self.run_model()["ok"])

    def test_run_with_everything_passed_is_ok(self):
        records = [r for r in RATES if not r.startswith("A|F")]
        run = self.run_model(records)
        self.assertTrue(run["ok"])
        self.assertEqual(run["totals"]["failed_asserts"], 0)

    def test_binary_that_exits_with_an_error_makes_the_run_not_ok(self):
        records = [r for r in RATES if not r.startswith("A|F")]
        self.assertFalse(self.run_model(records, rc=3)["ok"])

    def test_suite_carries_its_file_and_description(self):
        suite = self.run_model()["suites"][0]
        self.assertEqual((suite["id"], suite["file"], suite["description"], suite["ended"]),
                         ("TSTRATES", os.path.join("tests", "RATES.cblt"), "Rates by amount", True))

    def test_external_suite_is_not_in_program(self):
        suite = self.run_model()["suites"][0]
        self.assertEqual((suite["in_program"], suite["program"]), (False, None))

    def test_in_program_suite_names_the_original_program(self):
        suite = self.run_model(inprog={"TSTRATES": "RATES.cbl"})["suites"][0]
        self.assertEqual((suite["in_program"], suite["program"]), (True, "RATES.cbl"))

    def test_case_status_is_passed_failed_or_skipped(self):
        cases = self.run_model()["suites"][0]["cases"]
        self.assertEqual([(c["name"], c["status"]) for c in cases],
                         [("large amount gets the top rate", "failed"), ("pending: negative amounts", "skipped"),
                          ("small amount is unchanged", "passed")])

    def test_assert_keeps_expected_actual_and_message(self):
        failed = self.run_model()["suites"][0]["cases"][0]["asserts"][1]
        self.assertEqual(failed, {"nr": 2, "status": "failed", "kind": "EQ", "expected": "PREMIUM",
                                  "actual": "BASIC", "message": "EXPECT WS-CATEGORY TO BE 'PREMIUM'"})

    def test_case_kinds_are_attached_and_counted(self):
        reasons = [{"construct": "PERFORM 2100-CALC", "line": 12}]
        run = self.run_model(case_kinds={("TSTRATES", "large amount gets the top rate"): ("internal", reasons),
                                         ("TSTRATES", "small amount is unchanged"): ("interface", [])})
        first, _, third = run["suites"][0]["cases"]
        self.assertEqual((first["kind"], first["reasons"], third["kind"]), ("internal", reasons, "interface"))
        self.assertEqual((run["totals"]["internal"], run["totals"]["interface"]), (1, 1))

    def test_case_without_a_known_kind_is_not_classified(self):
        case = self.run_model()["suites"][0]["cases"][0]
        self.assertEqual((case["kind"], case["reasons"]), ("", []))

    def test_output_is_attached_to_its_case(self):
        outputs = {("TSTRATES", "small amount is unchanged"): ["RATE=0"]}
        cases = self.run_model(outputs=outputs)["suites"][0]["cases"]
        self.assertEqual([c["output"] for c in cases], [[], [], ["RATE=0"]])

    def test_stderr_of_the_binary_is_kept(self):
        run = self.run_model(outputs={("__stderr__", None): ["libcob: warning"]})
        self.assertEqual(run["stderr"], ["libcob: warning"])

    def test_suite_that_did_not_end_is_an_error(self):
        run = self.run_model(RATES[:-1])
        self.assertEqual(run["totals"]["errors"], 1)
        self.assertFalse(run["suites"][0]["ended"])
        self.assertFalse(run["ok"])

    def test_suite_that_never_started_is_missing_and_warned(self):
        suites = [SuiteRef("TSTRATES", "tests/RATES.cblt"), SuiteRef("TSTLATER", "tests/LATER.cblt")]
        run = self.run_model(suites=suites)
        self.assertEqual((run["missing_suites"], run["totals"]["errors"]), (1, 1))
        self.assertEqual([w["code"] for w in run["warnings"]], ["CBLT-W301"])
        self.assertIn("1 test(s) never started", run["warnings"][0]["message"])

    def test_complete_run_has_no_warnings(self):
        run = self.run_model()
        self.assertEqual((run["missing_suites"], run["warnings"]), (0, []))

    def test_assert_records_cut_in_transit_are_warned_with_the_column(self):
        records = list(RATES)
        records[3] = records[3][:109]
        run = self.run_model(records)
        self.assertEqual([w["code"] for w in run["warnings"]], ["CBLT-W307"])
        self.assertIn("1 assert record(s) arrived cut at column 109", run["warnings"][0]["message"])

    # The log of a suite keeps a fixed number of entries; the E record still
    # says how many asserts ran and how many failed.
    def test_counts_of_the_e_record_that_match_the_log_change_nothing(self):
        run = self.run_model(RATES[:-1] + ["E|TSTRATES|00003|00001"])
        self.assertEqual(run["warnings"], [])
        self.assertEqual((run["totals"]["asserts"], run["totals"]["failed_asserts"], run["totals"]["errors"]),
                         (3, 1, 0))
        self.assertEqual((run["suites"][0]["unlogged_asserts"], run["suites"][0]["unlogged_failures"]), (0, 0))

    def test_asserts_past_the_log_are_counted_and_warned(self):
        records = [r for r in RATES[:-1] if not r.startswith("A|F")] + ["E|TSTRATES|00010|00000"]
        run = self.run_model(records)
        self.assertEqual([w["code"] for w in run["warnings"]], ["CBLT-W308"])
        self.assertIn("TSTRATES ran 10 assert(s) and 0 failed, but the detail of only 2 arrived",
                      run["warnings"][0]["message"])
        self.assertEqual((run["totals"]["asserts"], run["totals"]["failed_asserts"], run["totals"]["errors"]),
                         (10, 0, 0))
        self.assertEqual(run["suites"][0]["unlogged_asserts"], 8)
        self.assertTrue(run["ok"])

    def test_failure_past_the_log_is_an_error_and_never_a_pass(self):
        records = [r for r in RATES[:-1] if not r.startswith("A|F")] + ["E|TSTRATES|00010|00002"]
        run = self.run_model(records)
        self.assertEqual((run["totals"]["failed_asserts"], run["totals"]["errors"]), (2, 1))
        self.assertEqual(run["suites"][0]["unlogged_failures"], 2)
        self.assertFalse(run["ok"])

    def test_failures_in_the_log_are_not_counted_twice(self):
        run = self.run_model(RATES[:-1] + ["E|TSTRATES|00010|00003"])
        self.assertEqual((run["totals"]["failed_asserts"], run["suites"][0]["unlogged_failures"]), (3, 2))

    def test_suite_without_declared_cases_gets_one_implicit_case(self):
        records = ["T|TSTOLD", "E|TSTOLD"]
        run = self.run_model(records, suites=[SuiteRef("TSTOLD", "tests/TSTOLD.cbl")],
                             outputs={("TSTOLD", None): ["hand-written test"]})
        case = run["suites"][0]["cases"][0]
        self.assertEqual((case["name"], case["implicit"], case["status"], case["output"]),
                         ("TSTOLD", True, "passed", ["hand-written test"]))
        self.assertEqual(run["totals"]["cases"], 1)

    def test_implicit_case_of_a_suite_that_aborted_is_left_out_of_the_totals(self):
        run = self.run_model(["T|TSTOLD"], suites=[SuiteRef("TSTOLD", "tests/TSTOLD.cbl")])
        self.assertEqual((run["totals"]["cases"], run["totals"]["errors"]), (0, 1))
        self.assertEqual(len(run["suites"][0]["cases"]), 1)

    def test_declared_cases_are_not_implicit(self):
        self.assertEqual({c["implicit"] for c in self.run_model()["suites"][0]["cases"]}, {False})

    def test_suite_that_ran_but_was_not_asked_for_has_no_file(self):
        run = self.run_model(suites=[])
        self.assertEqual((run["suites"][0]["file"], run["suites"][0]["description"]), ("", ""))
        self.assertEqual(run["missing_suites"], 0)


class ReasonTextTest(unittest.TestCase):
    def test_reason_with_a_line(self):
        self.assertEqual(results.reason_text({"construct": "PERFORM 2100-CALC", "line": 12}),
                         "PERFORM 2100-CALC (line 12)")

    def test_reason_without_a_line(self):
        self.assertEqual(results.reason_text({"construct": "MOCK PARAGRAPH"}), "MOCK PARAGRAPH")


if __name__ == "__main__":
    unittest.main()
