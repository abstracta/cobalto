"""Unit tests for cobalto.dsl: the .cblt parser, VERIFY lines and the COBOL of an EXPECT."""
import re
import unittest

import support
from support import TempDirTestCase, fixed, line_of

from cobalto.cobolgen import CobolWriter
from cobalto.dsl import DslError, gen_expect, parse_dsl, parse_verify
from cobalto.messages import CobaltoError

EXTERNAL = """
    * Synthetic suite for a made-up program.
    TESTSUITE tstrates 'Rates by amount'

    WORKING-STORAGE SECTION.
    01  WS-AMOUNT                 PIC 9(7)V99.
    01  WS-RESULT                 PIC 9(7)V99.

    BEFORE-EACH
        MOVE ZERO TO WS-RESULT
    END-BEFORE

    AFTER-EACH
        MOVE ZERO TO WS-AMOUNT
    END-AFTER

    TESTCASE 'large amount gets the top rate'
        MOVE 2000 TO WS-AMOUNT
        *> an inline comment line
        CALL "RATES" USING WS-AMOUNT WS-RESULT
        EXPECT WS-RESULT TO BE NUMERIC 1600

    IGNORE
    TESTCASE 'pending: negative amounts'
        EXPECT WS-RESULT TO BE ZEROS

    TESTCASE "small amount is unchanged"
        MOVE 10 TO WS-AMOUNT
        EXPECT WS-RESULT TO BE NUMERIC 10
"""

IN_PROGRAM = """
    TESTSUITE TSTBILL 'Billing (in-program)'
    PROGRAM BILLING

    BEFORE-EACH
        MOCK CLOCK
            DATE YYYYMMDD '20300115'
            TIME '10203040'
        END-MOCK
    END-BEFORE

    TESTCASE 'process with mocks'
        MOCK FILE CUST-FILE
            ON READ
                MOVE "C001" TO CUST-REC
            ON READ AT END
            ON WRITE
                MOVE CUST-REC TO WS-CAPTURED
        END-MOCK
        MOCK CALL 'RATES'
            MOVE 999 TO WS-NET
            EXPECT WS-GROSS TO BE NUMERIC 100
        END-MOCK
        MOCK PARAGRAPH 3000-END
        END-MOCK
        MOCK SQL 'FROM CUSTOMERS'
            MOVE 0 TO SQLCODE
        END-MOCK
        RUN USING WS-IN WS-OUT
        PERFORM 2000-PROCESS
        VERIFY PARAGRAPH 2100-CALC HAPPENED 2 TIMES
        VERIFY CALL 'RATES' HAPPENED AT LEAST 2 TIMES
"""


class DslTestCase(TempDirTestCase):
    def suite(self, text):
        """Parses a block as a .cblt file; keeps its text for line_of."""
        self.src = fixed(text)
        return parse_dsl(self.write("SUITE.cblt", self.src))

    def error(self, text):
        with self.assertRaises(DslError) as caught:
            self.suite(text)
        return caught.exception

    def line(self, fragment):
        return line_of(self.src, fragment)


class ExternalSuiteTest(DslTestCase):
    def setUp(self):
        super().setUp()
        self.parsed = self.suite(EXTERNAL)

    def test_suite_id_is_uppercased(self):
        self.assertEqual(self.parsed.id, "TSTRATES")

    def test_description_loses_its_quotes(self):
        self.assertEqual(self.parsed.desc, "Rates by amount")

    def test_suite_remembers_its_file_and_the_line_of_testsuite(self):
        self.assertTrue(self.parsed.file.endswith("SUITE.cblt"))
        self.assertEqual(self.parsed.line, self.line("TESTSUITE"))

    def test_suite_without_program_is_external(self):
        self.assertIsNone(self.parsed.program)

    def test_working_storage_lines_are_kept_as_written_with_their_line(self):
        self.assertEqual([(st.line, st.kind) for st in self.parsed.ws],
                         [(self.line("01  WS-AMOUNT"), "COBOL"), (self.line("01  WS-RESULT"), "COBOL")])
        self.assertEqual(self.parsed.ws[0].payload, self.src.splitlines()[self.line("01  WS-AMOUNT") - 1])

    def test_before_each_block(self):
        self.assertEqual([st.payload.strip() for st in self.parsed.before], ["MOVE ZERO TO WS-RESULT"])

    def test_after_each_block(self):
        self.assertEqual([st.payload.strip() for st in self.parsed.after], ["MOVE ZERO TO WS-AMOUNT"])

    def test_test_cases_in_order_with_name_and_line(self):
        self.assertEqual([(c.name, c.line) for c in self.parsed.cases],
                         [("large amount gets the top rate", self.line("TESTCASE 'large")),
                          ("pending: negative amounts", self.line("TESTCASE 'pending")),
                          ("small amount is unchanged", self.line('TESTCASE "small'))])

    def test_ignore_marks_only_the_next_test_case(self):
        self.assertEqual([c.ignored for c in self.parsed.cases], [False, True, False])

    def test_case_statements_are_cobol_or_expect(self):
        first = self.parsed.cases[0]
        self.assertEqual([(st.kind, st.payload.strip()) for st in first.stmts],
                         [("COBOL", "MOVE 2000 TO WS-AMOUNT"),
                          ("COBOL", 'CALL "RATES" USING WS-AMOUNT WS-RESULT'),
                          ("EXPECT", "WS-RESULT TO BE NUMERIC 1600")])

    def test_statements_carry_their_line_in_the_file(self):
        expect = self.parsed.cases[0].stmts[-1]
        self.assertEqual(expect.line, self.line("NUMERIC 1600"))

    def test_comments_and_blank_lines_are_skipped(self):
        payloads = [st.payload for case in self.parsed.cases for st in case.stmts]
        self.assertFalse([p for p in payloads if "comment" in p])
        self.assertEqual(len(self.parsed.cases[0].stmts), 3)

    def test_external_suite_has_no_mocks_verifies_or_runs(self):
        self.assertEqual((self.parsed.mocks, self.parsed.verifies, self.parsed.runs), ([], [], []))


class SuiteHeaderErrorTest(DslTestCase):
    def test_missing_testsuite(self):
        err = self.error("""
            TESTCASE 'alone'
                EXPECT WS-A TO BE ZEROS
        """)
        self.assertIn("TESTSUITE", err.kw["detail"])

    def test_testsuite_without_an_identifier(self):
        err = self.error("""
            * header comment
            TESTSUITE
        """)
        self.assertEqual(err.kw["line"], 2)

    def test_testsuite_identifier_must_start_with_a_letter(self):
        err = self.error("""
            TESTSUITE 9RATES 'bad id'
        """)
        self.assertEqual(err.kw["line"], 1)

    def test_testsuite_identifier_of_thirty_characters_is_accepted(self):
        parsed = self.suite(f"""
            TESTSUITE {"T" * 30}
            TESTCASE 'one'
                EXPECT WS-A TO BE ZEROS
        """)
        self.assertEqual(parsed.id, "T" * 30)

    def test_testsuite_identifier_longer_than_thirty_characters_is_rejected(self):
        self.error(f"""
            TESTSUITE {"T" * 31}
        """)

    def test_keywords_are_case_insensitive(self):
        parsed = self.suite("""
            testsuite tstlower 'lowercase keywords'
            testcase 'one'
                expect WS-A to be zeros
        """)
        self.assertEqual((parsed.id, [c.name for c in parsed.cases]), ("TSTLOWER", ["one"]))
        self.assertEqual(parsed.cases[0].stmts[0].kind, "EXPECT")


class StructureErrorTest(DslTestCase):
    def test_statement_outside_any_block_reports_its_line(self):
        err = self.error("""
            TESTSUITE TSTBAD 'bad'

                MOVE 1 TO WS-A
            TESTCASE 'one'
                EXPECT WS-A TO BE ZEROS
        """)
        self.assertEqual(err.kw["line"], self.line("MOVE 1 TO WS-A"))

    def test_statement_after_end_before_is_outside_any_block(self):
        err = self.error("""
            TESTSUITE TSTBAD 'bad'
            BEFORE-EACH
                MOVE 1 TO WS-A
            END-BEFORE
                MOVE 2 TO WS-A
        """)
        self.assertEqual(err.kw["line"], self.line("MOVE 2 TO WS-A"))

    def test_expect_outside_a_test_case(self):
        err = self.error("""
            TESTSUITE TSTBAD 'bad'
            BEFORE-EACH
                EXPECT WS-A TO BE ZEROS
            END-BEFORE
        """)
        self.assertEqual(err.kw["line"], self.line("EXPECT"))
        self.assertIn("EXPECT", err.kw["detail"])

    def test_testcase_without_a_description(self):
        err = self.error("""
            TESTSUITE TSTBAD 'bad'
            TESTCASE
                EXPECT WS-A TO BE ZEROS
        """)
        self.assertEqual(err.kw["line"], 2)

    def test_suite_without_test_cases_is_accepted(self):
        parsed = self.suite("""
            TESTSUITE TSTEMPTY 'nothing yet'
        """)
        self.assertEqual(parsed.cases, [])


class DslErrorTest(DslTestCase):
    def test_is_a_catalog_error_with_code_e200(self):
        err = DslError(12, "something is wrong")
        self.assertIsInstance(err, CobaltoError)
        self.assertEqual(err.code, "E200")

    def test_carries_the_line_and_the_detail(self):
        err = DslError(12, "something is wrong")
        self.assertEqual((err.kw["line"], err.kw["detail"]), (12, "something is wrong"))

    def test_message_has_the_code_the_file_and_the_line(self):
        err = DslError(12, "something is wrong", file="tests/RATES.cblt")
        self.assertEqual(str(err), "CBLT-E200: DSL syntax error in tests/RATES.cblt:12: something is wrong")

    def test_file_can_be_filled_in_later_by_whoever_knows_it(self):
        err = self.error("""
            TESTSUITE TSTBAD 'bad'
            TESTCASE
        """)
        err.kw["file"] = "tests/BAD.cblt"
        self.assertIn("tests/BAD.cblt:2:", str(err))


class InProgramSuiteTest(DslTestCase):
    def setUp(self):
        super().setUp()
        self.parsed = self.suite(IN_PROGRAM)
        self.case = self.parsed.cases[0]

    def mock(self, kind):
        return next(m for m in self.parsed.mocks if m.kind == kind)

    def test_program_turns_on_in_program_mode(self):
        self.assertEqual(self.parsed.program, "BILLING")

    def test_all_mocks_of_the_suite_in_order(self):
        self.assertEqual([(m.kind, m.name) for m in self.parsed.mocks],
                         [("CLOCK", ""), ("FILE", "CUST-FILE"), ("CALL", "'RATES'"),
                          ("PARAGRAPH", "3000-END"), ("SQL", "'FROM CUSTOMERS'")])

    def test_mock_knows_its_line_and_where_it_was_declared(self):
        self.assertEqual((self.mock("CLOCK").where, self.mock("CLOCK").line), ("before", self.line("MOCK CLOCK")))
        self.assertEqual((self.mock("FILE").where, self.mock("FILE").line), ("case", self.line("MOCK FILE")))

    def test_mock_in_before_each_is_a_statement_of_that_block(self):
        self.assertEqual([(st.kind, st.payload) for st in self.parsed.before], [("MOCK", self.mock("CLOCK"))])

    def test_mock_clock_lines_give_what_each_accept_returns(self):
        self.assertEqual(self.mock("CLOCK").clock, {"DATE YYYYMMDD": "'20300115'", "TIME": "'10203040'"})

    def test_mock_file_groups_statements_by_operation(self):
        ops = self.mock("FILE").ops
        self.assertEqual(sorted(ops), ["READ", "WRITE"])
        self.assertEqual([st.payload.strip() for st in ops["WRITE"]], ["MOVE CUST-REC TO WS-CAPTURED"])

    def test_on_read_at_end_sets_the_end_of_file_flag(self):
        read = [st.payload.strip() for st in self.mock("FILE").ops["READ"]]
        self.assertEqual(read, ['MOVE "C001" TO CUST-REC', "SET CBLT-AT-END TO TRUE"])

    def test_mock_body_accepts_cobol_and_expect(self):
        self.assertEqual([(st.kind, st.payload.strip()) for st in self.mock("CALL").body],
                         [("COBOL", "MOVE 999 TO WS-NET"), ("EXPECT", "WS-GROSS TO BE NUMERIC 100")])

    def test_empty_mock_has_no_body(self):
        self.assertEqual(self.mock("PARAGRAPH").body, [])

    def test_case_statements_keep_mocks_run_and_verify_in_order(self):
        self.assertEqual([st.kind for st in self.case.stmts],
                         ["MOCK", "MOCK", "MOCK", "MOCK", "RUN", "COBOL", "VERIFY", "VERIFY"])

    def test_statements_inside_a_mock_do_not_leak_into_the_case(self):
        cobol = [st.payload.strip() for st in self.case.stmts if st.kind == "COBOL"]
        self.assertEqual(cobol, ["PERFORM 2000-PROCESS"])

    def test_run_keeps_its_using_list_and_its_line(self):
        run = next(st for st in self.case.stmts if st.kind == "RUN")
        self.assertEqual((run.payload, run.line), ("USING WS-IN WS-OUT", self.line("RUN USING")))
        self.assertEqual(self.parsed.runs, [self.line("RUN USING")])

    def test_verifies_are_collected_in_the_suite(self):
        self.assertEqual([(v.kind, v.name, v.mode, v.count) for v in self.parsed.verifies],
                         [("PARAGRAPH", "2100-CALC", "exact", 2), ("CALL", "'RATES'", "atleast", 2)])


class MockErrorTest(DslTestCase):
    HEAD = """
        TESTSUITE TSTMOCK 'mock errors'
        PROGRAM BILLING
        TESTCASE 'one'
    """

    def mock_error(self, body):
        return self.error(support.blocks(self.HEAD, body))

    def test_mock_without_end_mock_reports_the_line_of_the_mock(self):
        err = self.mock_error("""
            MOCK PARAGRAPH 3000-END
                MOVE 1 TO WS-A
        """)
        self.assertEqual(err.kw["line"], self.line("MOCK PARAGRAPH"))
        self.assertIn("END-MOCK", err.kw["detail"])

    def test_mock_of_an_unknown_kind(self):
        err = self.mock_error("""
            MOCK SCREEN MAIN-MENU
            END-MOCK
        """)
        self.assertEqual(err.kw["line"], self.line("MOCK SCREEN"))

    def test_mock_paragraph_needs_a_name(self):
        err = self.mock_error("""
            MOCK PARAGRAPH
            END-MOCK
        """)
        self.assertIn("MOCK PARAGRAPH needs a name", err.kw["detail"])

    def test_mock_file_statements_must_follow_an_on_block(self):
        err = self.mock_error("""
            MOCK FILE CUST-FILE
                MOVE "C001" TO CUST-REC
            END-MOCK
        """)
        self.assertEqual(err.kw["line"], self.line('MOVE "C001"'))

    def test_mock_file_with_an_unknown_operation(self):
        err = self.mock_error("""
            MOCK FILE CUST-FILE
                ON SORT
            END-MOCK
        """)
        self.assertEqual(err.kw["line"], self.line("ON SORT"))

    def test_mock_clock_with_a_line_that_is_not_a_clock_value(self):
        err = self.mock_error("""
            MOCK CLOCK
                MONTH '01'
            END-MOCK
        """)
        self.assertEqual(err.kw["line"], self.line("MONTH"))

    def test_dsl_keyword_inside_a_mock(self):
        err = self.mock_error("""
            MOCK PARAGRAPH 3000-END
                VERIFY PARAGRAPH 2100-CALC HAPPENED ONCE
            END-MOCK
        """)
        self.assertEqual(err.kw["line"], self.line("VERIFY"))
        self.assertIn("VERIFY", err.kw["detail"])

    def test_mock_outside_a_test_case_or_before_each(self):
        err = self.error("""
            TESTSUITE TSTMOCK 'mock errors'
            PROGRAM BILLING
            MOCK PARAGRAPH 3000-END
            END-MOCK
        """)
        self.assertEqual(err.kw["line"], 3)

    def test_verify_outside_a_test_case(self):
        err = self.error("""
            TESTSUITE TSTMOCK 'mock errors'
            PROGRAM BILLING
            VERIFY PARAGRAPH 2100-CALC HAPPENED ONCE
        """)
        self.assertEqual(err.kw["line"], 3)

    def test_run_outside_a_test_case(self):
        err = self.error("""
            TESTSUITE TSTMOCK 'mock errors'
            PROGRAM BILLING
            RUN
        """)
        self.assertEqual(err.kw["line"], 3)

    def test_program_without_a_name(self):
        err = self.error("""
            TESTSUITE TSTMOCK 'mock errors'
            PROGRAM
        """)
        self.assertEqual(err.kw["line"], 2)

    def test_mock_verify_and_run_need_a_suite_with_program(self):
        for statement in ("MOCK PARAGRAPH 3000-END\n    END-MOCK", "VERIFY STOP HAPPENED ONCE", "RUN"):
            with self.subTest(statement=statement.split()[0]):
                err = self.error("TESTSUITE TSTEXT 'external'\nTESTCASE 'one'\n"
                                 "    MOVE 1 TO WS-A\n    " + statement + "\n")
                self.assertEqual(err.kw["line"], 4)
                self.assertIn("PROGRAM", err.kw["detail"])


class PlainCobolTest(DslTestCase):
    def test_bare_on_outside_a_mock_file_is_plain_cobol(self):
        parsed = self.suite("""
            TESTSUITE TSTON 'on size error'
            TESTCASE 'one'
                ADD 1 TO WS-A
                    ON SIZE ERROR MOVE 0 TO WS-A
                END-ADD
        """)
        self.assertEqual([(st.kind, st.payload.strip()) for st in parsed.cases[0].stmts][1],
                         ("COBOL", "ON SIZE ERROR MOVE 0 TO WS-A"))

    def test_word_that_only_starts_like_a_keyword_is_plain_cobol(self):
        parsed = self.suite("""
            TESTSUITE TSTWORD 'keyword prefixes'
            TESTCASE 'one'
                MOVE 1 TO
                    EXPECT-COUNT
                    RUN-TOTAL
        """)
        self.assertEqual([st.kind for st in parsed.cases[0].stmts], ["COBOL", "COBOL", "COBOL"])
        self.assertEqual(parsed.runs, [])

    def test_program_keyword_is_accepted_with_a_quoted_path(self):
        parsed = self.suite("""
            TESTSUITE TSTPATH 'by path'
            PROGRAM "legacy/BILLING.cbl"
        """)
        self.assertEqual(parsed.program, '"legacy/BILLING.cbl"')


class ParseVerifyTest(unittest.TestCase):
    def fields(self, text):
        v = parse_verify(7, text)
        return v.kind, v.name, v.mode, v.count

    def test_happened_n_times(self):
        self.assertEqual(self.fields("PARAGRAPH 2100-CALC HAPPENED 2 TIMES"), ("PARAGRAPH", "2100-CALC", "exact", 2))

    def test_happened_1_time_in_singular(self):
        self.assertEqual(self.fields("READ CUST-FILE HAPPENED 1 TIME"), ("READ", "CUST-FILE", "exact", 1))

    def test_happened_once(self):
        self.assertEqual(self.fields("WRITE REPORT-FILE HAPPENED ONCE"), ("WRITE", "REPORT-FILE", "exact", 1))

    def test_never_happened(self):
        self.assertEqual(self.fields("PARAGRAPH 3000-END NEVER HAPPENED"), ("PARAGRAPH", "3000-END", "exact", 0))

    def test_at_least(self):
        self.assertEqual(self.fields("CALL 'RATES' HAPPENED AT LEAST 2 TIMES"), ("CALL", "'RATES'", "atleast", 2))

    def test_no_more_than(self):
        self.assertEqual(self.fields("OPEN CUST-FILE HAPPENED NO MORE THAN 3 TIMES"),
                         ("OPEN", "CUST-FILE", "nomore", 3))

    def test_at_most_is_the_same_as_no_more_than(self):
        self.assertEqual(self.fields("CLOSE CUST-FILE HAPPENED AT MOST 1 TIME"), ("CLOSE", "CUST-FILE", "nomore", 1))

    def test_every_documented_kind_is_accepted(self):
        for kind in ("PARAGRAPH", "CALL", "READ", "WRITE", "REWRITE", "DELETE", "START", "OPEN", "CLOSE"):
            with self.subTest(kind=kind):
                self.assertEqual(self.fields(f"{kind} SOME-NAME HAPPENED ONCE"), (kind, "SOME-NAME", "exact", 1))

    def test_sql_clock_and_stop_need_no_name(self):
        self.assertEqual(self.fields("STOP HAPPENED ONCE"), ("STOP", "", "exact", 1))
        self.assertEqual(self.fields("CLOCK HAPPENED 3 TIMES"), ("CLOCK", "", "exact", 3))
        self.assertEqual(self.fields("SQL NEVER HAPPENED"), ("SQL", "", "exact", 0))

    def test_sql_can_name_a_text(self):
        self.assertEqual(self.fields("SQL 'CUSTOMERS' HAPPENED ONCE"), ("SQL", "'CUSTOMERS'", "exact", 1))

    def test_lowercase_is_accepted_and_the_name_keeps_its_case(self):
        self.assertEqual(self.fields("paragraph Calc-Total happened once"), ("PARAGRAPH", "Calc-Total", "exact", 1))

    def test_verify_keeps_its_line_and_text(self):
        v = parse_verify(7, "STOP HAPPENED ONCE")
        self.assertEqual((v.line, v.text), (7, "STOP HAPPENED ONCE"))

    def assert_rejected(self, text):
        with self.assertRaises(DslError) as caught:
            parse_verify(7, text)
        self.assertEqual(caught.exception.kw["line"], 7)
        return caught.exception.kw["detail"]

    def test_unknown_kind_is_rejected(self):
        self.assertIn("VERIFY needs", self.assert_rejected("SCREEN MAIN-MENU HAPPENED ONCE"))

    def test_empty_verify_is_rejected(self):
        self.assert_rejected("")

    def test_kind_that_needs_a_name_without_one_is_rejected(self):
        self.assertIn("needs a name", self.assert_rejected("PARAGRAPH"))

    def test_unknown_count_form_is_rejected(self):
        self.assertIn("expected", self.assert_rejected("PARAGRAPH 2100-CALC HAPPENED TWICE"))

    def test_count_must_be_a_number(self):
        self.assert_rejected("PARAGRAPH 2100-CALC HAPPENED MANY TIMES")


class GenExpectTest(unittest.TestCase):
    """gen_expect(): the COBOL that checks one EXPECT line."""

    ORIGIN = ("tests/RATES.cblt", 31)

    def expect(self, text):
        self.writer = CobolWriter()
        gen_expect(self.writer, self.ORIGIN, text)
        return [ln.strip() for ln in self.writer.lines]

    def check(self, text):
        """The generated lines after the ones that record the message."""
        return [ln for ln in self.expect(text) if "CBLT-MSG" not in ln]

    def message(self, text):
        """The text moved to CBLT-MSG, rebuilt from its chunks."""
        chunks = [re.match(r'MOVE "(.*)" TO CBLT-MSG\(\d+:\d+\)$', ln) for ln in self.expect(text)]
        return "".join(m.group(1) for m in chunks if m)

    def test_alphanumeric_equality(self):
        self.assertEqual(self.check("WS-CATEGORY TO BE 'PREMIUM'"),
                         ["MOVE 'PREMIUM' TO CBLT-EXP", "MOVE WS-CATEGORY TO CBLT-ACT", 'CALL "CBLTEQ" USING CBLT-CTX'])

    def test_equality_with_another_field(self):
        self.assertEqual(self.check("WS-RESULT TO BE WS-EXPECTED")[0], "MOVE WS-EXPECTED TO CBLT-EXP")

    def test_inequality(self):
        self.assertEqual(self.check("WS-CATEGORY NOT TO BE 'PREMIUM'")[-1], 'CALL "CBLTNE" USING CBLT-CTX')

    def test_numeric_equality(self):
        self.assertEqual(self.check("WS-RESULT TO BE NUMERIC 1600"),
                         ["MOVE 1600 TO CBLT-EXP-NUM", "MOVE WS-RESULT TO CBLT-ACT-NUM", 'CALL "CBLTEQN" USING CBLT-CTX'])

    def test_greater_than_takes_an_expression(self):
        self.assertEqual(self.check("WS-RESULT TO BE GREATER THAN WS-BASE * 2"),
                         ["COMPUTE CBLT-EXP-NUM = WS-BASE * 2", "MOVE WS-RESULT TO CBLT-ACT-NUM",
                          'CALL "CBLTGT" USING CBLT-CTX'])

    def test_less_than(self):
        self.assertEqual(self.check("WS-RESULT TO BE LESS THAN 10")[-1], 'CALL "CBLTLT" USING CBLT-CTX')

    def test_between_sets_both_bounds(self):
        self.assertEqual(self.check("WS-RESULT TO BE BETWEEN 10 AND 20"),
                         ["COMPUTE CBLT-EXP-NUM = 10", "COMPUTE CBLT-EXP-NUM2 = 20",
                          "MOVE WS-RESULT TO CBLT-ACT-NUM", 'CALL "CBLTBT" USING CBLT-CTX'])

    def test_condition_true_compares_the_outcome_of_an_if(self):
        lines = self.check("WS-IS-PREMIUM TO BE TRUE")
        self.assertEqual(lines[0], "IF WS-IS-PREMIUM")
        self.assertIn('MOVE "TRUE" TO CBLT-EXP', lines)
        self.assertEqual(lines[-1], 'CALL "CBLTEQ" USING CBLT-CTX')

    def test_condition_false_expects_false(self):
        self.assertIn('MOVE "FALSE" TO CBLT-EXP', self.check("WS-IS-PREMIUM TO BE FALSE"))

    def test_spaces_is_an_alphanumeric_comparison(self):
        self.assertEqual(self.check("WS-CATEGORY TO BE SPACES"),
                         ["MOVE SPACES TO CBLT-EXP", "MOVE WS-CATEGORY TO CBLT-ACT", 'CALL "CBLTEQ" USING CBLT-CTX'])

    def test_zeros_is_a_numeric_comparison(self):
        self.assertEqual(self.check("WS-RESULT TO BE ZEROS"),
                         ["MOVE ZERO TO CBLT-EXP-NUM", "MOVE WS-RESULT TO CBLT-ACT-NUM", 'CALL "CBLTEQN" USING CBLT-CTX'])

    def test_contain(self):
        self.assertEqual(self.check("WS-LINE TO CONTAIN 'BETA'"),
                         ["MOVE 'BETA' TO CBLT-EXP", "MOVE WS-LINE TO CBLT-ACT", 'CALL "CBLTCT" USING CBLT-CTX'])

    def test_keywords_are_case_insensitive(self):
        self.assertEqual(self.check("WS-RESULT to be numeric 5")[-1], 'CALL "CBLTEQN" USING CBLT-CTX')

    def test_the_expect_line_is_recorded_as_the_message(self):
        self.assertEqual(self.message("WS-RESULT TO BE NUMERIC 1600"), "EXPECT WS-RESULT TO BE NUMERIC 1600")

    def test_message_is_cut_at_sixty_characters(self):
        text = "WS-A-RATHER-LONG-RESULT-FIELD TO BE GREATER THAN WS-BASE-AMOUNT * 2"
        self.assertEqual(self.message(text), "EXPECT WS-A-RATHER-LONG-RESULT-FIELD TO BE GREATER THAN WS-B")

    def test_double_quotes_of_the_expect_do_not_break_the_message_literal(self):
        self.assertEqual(self.message('WS-CATEGORY TO BE "GOLD"'), "EXPECT WS-CATEGORY TO BE 'GOLD'")

    def test_every_generated_line_points_at_the_expect_and_fits_in_72_columns(self):
        self.expect("WS-A-RATHER-LONG-RESULT-FIELD TO BE GREATER THAN WS-BASE-AMOUNT * 2")
        self.assertEqual(set(self.writer.origin), {self.ORIGIN})
        self.assertLessEqual(max(len(ln) for ln in self.writer.lines), 72)

    def test_unrecognized_expect_reports_the_line_of_the_suite(self):
        with self.assertRaises(DslError) as caught:
            self.expect("WS-RESULT SHOULD BE 5")
        self.assertEqual(caught.exception.kw["line"], 31)

    def test_not_to_contain_is_rejected(self):
        with self.assertRaises(DslError) as caught:
            self.expect("WS-LINE NOT TO CONTAIN 'BETA'")
        self.assertEqual(caught.exception.kw["line"], 31)

    # A negated form the core cannot check is an error, never the same check as the form without NOT.
    def test_not_is_never_dropped_silently(self):
        for positive in ("WS-A TO BE ZEROS", "WS-A TO BE NUMERIC 5", "WS-A TO BE GREATER THAN 5",
                         "WS-A TO BE LESS THAN 5", "WS-A TO BE BETWEEN 1 AND 5"):
            with self.subTest(expect=positive):
                try:
                    negated = self.check(positive.replace(" TO BE", " NOT TO BE"))
                except DslError:
                    continue
                self.assertNotEqual(negated, self.check(positive))


if __name__ == "__main__":
    unittest.main()
