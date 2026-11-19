"""Unit tests for cobalto.coverage: the instrumentation plan, the summary and
the report files (LCOV, Cobertura XML, SonarQube generic coverage).

The plan is built from small synthetic programs; the summary and the report
writers are fed hand-made maps and hit counts. No compiler is needed.
"""
import glob
import json
import os
import unittest
import xml.etree.ElementTree as ET

import support
from support import TempDirTestCase, fixed, line_of

from cobalto import coverage
from cobalto.cobparse import Program
from cobalto.coverage import HIT_ITEM, NO_PARA, Plan
from cobalto.messages import SCHEMA, VERSION


def add_line(idx):
    return f"ADD 1 TO {HIT_ITEM}({idx})"


class PlanTestCase(TempDirTestCase):
    def plan_body(self, procedure, **kw):
        """Plan of a program built around a PROCEDURE DIVISION body."""
        self.prog, self.src = self.parse_body(procedure, **kw)
        self.plan = Plan(self.prog)
        return self.plan

    def plan_program(self, text, **kw):
        self.prog, self.src = self.parse(text, **kw)
        self.plan = Plan(self.prog)
        return self.plan

    def line(self, fragment):
        return line_of(self.src, fragment)

    def unit(self, verb, nth=0):
        return [u for u in self.plan.units if u.verb == verb][nth]

    def inserts_before(self, unit):
        return self.plan.inserts[unit.start]

    def branches(self, unit, kinds=None):
        """(label, line, counter, implicit) of the branches of a statement."""
        return [(b.label, b.line, b.idx, b.implicit) for b in self.plan.branches
                if b.stmt == unit.idx and (kinds is None or b.kind in kinds)]

    def labels(self, unit):
        return [b.label for b in self.plan.branches if b.stmt == unit.idx]


class PlanUnitTest(PlanTestCase):
    """Which statements get a counter."""

    def test_every_statement_gets_a_counter_in_source_order(self):
        plan = self.plan_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A
                ADD 1 TO WS-B.
                GOBACK.
        """)
        self.assertEqual([(u.idx, u.verb) for u in plan.units], [(1, "MOVE"), (2, "ADD"), (3, "GOBACK")])
        self.assertEqual(plan.counters, 3)

    def test_nested_statements_get_their_own_counter(self):
        plan = self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                ELSE
                    PERFORM UNTIL WS-B > 3
                        ADD 1 TO WS-B
                    END-PERFORM
                END-IF
                EVALUATE WS-A
                    WHEN 1 MOVE 2 TO WS-C
                END-EVALUATE
                COMPUTE WS-A = WS-A + 1
                    ON SIZE ERROR MOVE 0 TO WS-A
                END-COMPUTE
                GOBACK.
        """)
        self.assertEqual([u.verb for u in plan.units],
                         ["IF", "MOVE", "PERFORM", "ADD", "EVALUATE", "MOVE", "COMPUTE", "MOVE", "GOBACK"])

    def test_counter_is_added_right_before_its_statement(self):
        plan = self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                END-IF
                GOBACK.
        """)
        move = self.unit("MOVE")
        self.assertEqual(self.prog.tokens[move.start].text, "MOVE")
        self.assertEqual(self.inserts_before(move), [add_line(move.idx)])

    def test_unit_records_where_the_statement_is(self):
        self.plan_body("""
            FIRST-PARA.
                MOVE 1 TO WS-A.
            SECOND-PARA.
                COMPUTE WS-B =
                    WS-A + 1.
                GOBACK.
        """)
        compute = self.unit("COMPUTE")
        self.assertEqual((compute.line, compute.end_line, compute.para, compute.file),
                         (self.line("COMPUTE WS-B"), self.line("WS-A + 1."), "SECOND-PARA", self.prog.path))

    def test_bare_exit_gets_no_counter(self):
        plan = self.plan_body("""
            MAIN-PARA.
                PERFORM LAST-PARA.
                GOBACK.
            LAST-PARA.
                EXIT.
        """)
        self.assertEqual([u.verb for u in plan.units], ["PERFORM", "GOBACK"])

    def test_exit_program_gets_a_counter(self):
        plan = self.plan_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
                EXIT PROGRAM.
        """)
        self.assertEqual([u.verb for u in plan.units], ["MOVE", "EXIT"])

    def test_goback_sends_the_counters_to_the_collector_after_counting_itself(self):
        self.plan_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
                GOBACK.
        """)
        goback = self.unit("GOBACK")
        inserted = self.inserts_before(goback)
        self.assertEqual(inserted[0], add_line(goback.idx))
        self.assertEqual(inserted[1:], coverage.FLUSH_LINES)
        self.assertIn('CALL "CBLTCOV"', inserted[1])

    def test_exit_program_sends_the_counters_to_the_collector(self):
        self.plan_body("""
            MAIN-PARA.
                EXIT PROGRAM.
        """)
        self.assertEqual(self.inserts_before(self.unit("EXIT"))[1:], coverage.FLUSH_LINES)

    def test_other_statements_do_not_call_the_collector(self):
        self.plan_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
                STOP RUN.
        """)
        for verb in ("MOVE", "STOP"):
            self.assertEqual(self.inserts_before(self.unit(verb)), [add_line(self.unit(verb).idx)])

    def test_program_that_ends_in_goback_ends_with_exit(self):
        plan = self.plan_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
                GOBACK.
        """)
        self.assertTrue(plan.ends_with_exit)

    def test_program_whose_last_statement_can_fall_off_the_end(self):
        plan = self.plan_body("""
            MAIN-PARA.
                PERFORM WORK-PARA.
                GOBACK.
            WORK-PARA.
                MOVE 1 TO WS-A.
        """)
        self.assertFalse(plan.ends_with_exit)

    def test_paragraphs_are_listed_with_their_lines(self):
        plan = self.plan_body("""
            FIRST-PARA.
                MOVE 1 TO WS-A.
            SECOND-PARA.
                MOVE 2 TO WS-B.
                GOBACK.
        """)
        self.assertEqual(plan.paragraphs,
                         [("FIRST-PARA", self.line("FIRST-PARA."), self.line("MOVE 1 TO WS-A"), False),
                          ("SECOND-PARA", self.line("SECOND-PARA."), self.line("GOBACK."), False)])

    def test_sections_are_flagged_in_the_paragraph_list(self):
        plan = self.plan_body("""
            MAIN-LOGIC SECTION.
            MAIN-PARA.
                GOBACK.
        """)
        self.assertEqual([(name, bool(is_section)) for name, _, _, is_section in plan.paragraphs],
                         [("MAIN-LOGIC", True), ("MAIN-PARA", False)])

    def test_statements_before_the_first_paragraph_are_grouped_apart(self):
        plan = self.plan_body("""
                MOVE 1 TO WS-A.
            LATER-PARA.
                GOBACK.
        """)
        self.assertEqual([u.para for u in plan.units], [NO_PARA, "LATER-PARA"])
        self.assertEqual([name for name, _, _, _ in plan.paragraphs], [NO_PARA, "LATER-PARA"])

    def test_statement_from_a_copybook_is_reported_in_the_copybook(self):
        copybook = self.write("CHECKS.cpy", fixed("""
            * Synthetic copybook with code.
                IF WS-A = 9
                    MOVE 9 TO WS-B
                END-IF.
        """))
        self.plan_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
                COPY CHECKS.
                GOBACK.
        """)
        copied = self.unit("IF")
        self.assertEqual((copied.file, copied.line, copied.end_line, copied.para), (copybook, 2, 4, "MAIN-PARA"))
        self.assertEqual((self.unit("GOBACK").file, self.unit("GOBACK").line), (self.prog.path, self.line("GOBACK.")))

    def test_paragraph_lines_refer_to_the_source_when_a_copybook_is_expanded(self):
        self.write("CHECKS.cpy", fixed("""
            MOVE 9 TO WS-B.
            MOVE 8 TO WS-C.
            MOVE 7 TO WS-A.
        """))
        plan = self.plan_body("""
            MAIN-PARA.
                COPY CHECKS.
            LAST-PARA.
                GOBACK.
        """)
        self.assertEqual(plan.paragraphs[1], ("LAST-PARA", self.line("LAST-PARA."), self.line("GOBACK."), False))

    def test_declaratives_are_not_instrumented(self):
        plan = self.plan_program("""
            IDENTIFICATION DIVISION.
            PROGRAM-ID. DECL.
            ENVIRONMENT DIVISION.
            INPUT-OUTPUT SECTION.
            FILE-CONTROL.
                SELECT IN-FILE ASSIGN TO "in.dat".
            DATA DIVISION.
            FILE SECTION.
            FD  IN-FILE.
            01  IN-REC                    PIC X(20).
            PROCEDURE DIVISION.
            DECLARATIVES.
            IO-ERROR SECTION.
                USE AFTER STANDARD ERROR PROCEDURE ON IN-FILE.
            IO-ERROR-PARA.
                DISPLAY "input error".
            END DECLARATIVES.
            MAIN-PARA.
                GOBACK.
        """)
        self.assertEqual([u.verb for u in plan.units], ["GOBACK"])

    def test_program_without_statements_still_declares_one_counter(self):
        plan = self.plan_program("""
            IDENTIFICATION DIVISION.
            PROGRAM-ID. DATAONLY.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A                      PIC 9.
        """)
        self.assertEqual((plan.units, plan.counters, plan.n), ([], 0, 1))

    def test_plan_is_named_after_the_program(self):
        plan = self.plan_body("""
            MAIN-PARA.
                GOBACK.
        """, program_id="PAYROLL")
        self.assertEqual(plan.name, "PAYROLL")


class PlanIfBranchTest(PlanTestCase):
    def test_then_and_else_use_the_counter_of_the_first_statement_of_each_body(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                    MOVE 2 TO WS-C
                ELSE
                    MOVE 3 TO WS-B
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.branches(self.unit("IF")),
                         [("THEN", self.line("IF WS-A = 1"), self.unit("MOVE", 0).idx, False),
                          ("ELSE", self.line("ELSE"), self.unit("MOVE", 2).idx, False)])

    def test_branches_need_no_counters_of_their_own(self):
        plan = self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                ELSE
                    MOVE 3 TO WS-B
                END-IF
                GOBACK.
        """)
        self.assertEqual(plan.counters, len(plan.units))

    def test_if_without_else_has_an_implicit_else(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.branches(self.unit("IF")),
                         [("THEN", self.line("IF WS-A = 1"), self.unit("MOVE").idx, False),
                          ("ELSE", self.line("IF WS-A = 1"), None, True)])

    def test_branch_knows_its_statement_kind_paragraph_and_file(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                END-IF
                GOBACK.
        """)
        then = self.plan.branches[0]
        self.assertEqual((then.stmt, then.kind, then.para, then.file),
                         (self.unit("IF").idx, "IF", "MAIN-PARA", self.prog.path))

    def test_nested_if_has_its_own_branches(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    IF WS-B = 2
                        MOVE 1 TO WS-C
                    ELSE
                        MOVE 2 TO WS-C
                    END-IF
                END-IF
                GOBACK.
        """)
        outer, inner = self.unit("IF", 0), self.unit("IF", 1)
        self.assertEqual(self.branches(outer)[0][2], inner.idx)
        self.assertEqual([b[2] for b in self.branches(inner)], [self.unit("MOVE", 0).idx, self.unit("MOVE", 1).idx])

    def test_next_sentence_body_gets_a_counter_of_its_own(self):
        plan = self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 NEXT SENTENCE ELSE MOVE 2 TO WS-B.
                GOBACK.
        """)
        (_, _, then_idx, _), (_, _, else_idx, _) = self.branches(self.unit("IF"))
        self.assertEqual(else_idx, self.unit("MOVE").idx)
        self.assertEqual(then_idx, len(plan.units) + 1)
        self.assertEqual(plan.counters, len(plan.units) + 1)
        next_tok = next(i for i, t in enumerate(self.prog.tokens) if t.up == "NEXT")
        self.assertEqual(plan.inserts[next_tok], [add_line(then_idx)])

    def test_compound_condition_adds_two_outcomes_per_operand(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 AND WS-B = 2 OR WS-DONE
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.labels(self.unit("IF")),
                         ["WS-A = 1 true", "WS-A = 1 false", "WS-B = 2 true", "WS-B = 2 false",
                          "WS-DONE true", "WS-DONE false", "THEN", "ELSE"])

    def test_operand_outcomes_have_counters_after_those_of_the_statements(self):
        plan = self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 AND WS-B = 2
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        n = len(plan.units)
        self.assertEqual([idx for _, _, idx, _ in self.branches(self.unit("IF"), kinds=("COND",))],
                         [n + 1, n + 2, n + 3, n + 4])
        self.assertEqual(plan.counters, n + 4)

    def test_operand_outcomes_are_reported_on_the_line_of_the_if(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                   AND WS-B = 2
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        self.assertEqual({line for _, line, _, _ in self.branches(self.unit("IF"), kinds=("COND",))},
                         {self.line("IF WS-A = 1")})

    def test_evaluation_tree_is_inserted_before_the_if_after_its_counter(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 AND WS-B = 2
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        inserted = self.inserts_before(self.unit("IF"))
        self.assertEqual(inserted[0], add_line(self.unit("IF").idx))
        self.assertEqual([ln.strip() for ln in inserted if ln.strip().startswith("IF ")],
                         ["IF WS-A = 1", "IF WS-B = 2"])
        self.assertEqual(inserted[-1], "END-IF")

    def test_simple_condition_has_no_operand_outcomes(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A NOT = 1
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.labels(self.unit("IF")), ["THEN", "ELSE"])
        self.assertEqual(self.inserts_before(self.unit("IF")), [add_line(self.unit("IF").idx)])

    def test_then_word_is_not_part_of_the_condition(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 AND WS-B = 2 THEN
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.labels(self.unit("IF"))[2:4], ["WS-B = 2 true", "WS-B = 2 false"])

    def test_level_88_name_is_an_operand_and_a_data_name_an_abbreviation(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 OR WS-DONE
                    MOVE 4 TO WS-C
                END-IF
                IF WS-A = 1 OR WS-B
                    MOVE 5 TO WS-C
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.labels(self.unit("IF", 0))[2], "WS-DONE true")
        self.assertEqual(self.labels(self.unit("IF", 1))[2], "WS-A = WS-B true")

    def test_long_operand_is_cut_in_the_label(self):
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                   AND WS-LONG-FIELD-NAME-ONE = WS-LONG-FIELD-NAME-TWO
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """, data="""
            01  WS-A                      PIC 9.
            01  WS-C                      PIC 9.
            01  WS-LONG-FIELD-NAME-ONE    PIC 9.
            01  WS-LONG-FIELD-NAME-TWO    PIC 9.
        """)
        self.assertEqual(self.labels(self.unit("IF"))[2], "WS-LONG-FIELD-NAME-ONE = ... true")

    def test_condition_that_is_not_understood_keeps_only_then_and_else(self):
        plan = self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 OR NOT 2
                    MOVE 4 TO WS-C
                END-IF
                GOBACK.
        """)
        self.assertEqual(self.labels(self.unit("IF")), ["THEN", "ELSE"])
        self.assertEqual(plan.counters, len(plan.units))
        self.assertEqual(self.inserts_before(self.unit("IF")), [add_line(self.unit("IF").idx)])


class PlanEvaluateBranchTest(PlanTestCase):
    def test_each_when_group_and_when_other_is_a_branch(self):
        self.plan_body("""
            MAIN-PARA.
                EVALUATE WS-A
                    WHEN 1
                    WHEN 2
                        MOVE 1 TO WS-B
                    WHEN 3 THRU 5
                        MOVE 2 TO WS-B
                    WHEN OTHER
                        MOVE 3 TO WS-B
                END-EVALUATE
                GOBACK.
        """)
        self.assertEqual(self.branches(self.unit("EVALUATE")),
                         [("WHEN 1", self.line("WHEN 1"), self.unit("MOVE", 0).idx, False),
                          ("WHEN 3 THRU 5", self.line("WHEN 3 THRU 5"), self.unit("MOVE", 1).idx, False),
                          ("WHEN OTHER", self.line("WHEN OTHER"), self.unit("MOVE", 2).idx, False)])

    def test_evaluate_without_when_other_has_an_implicit_one(self):
        self.plan_body("""
            MAIN-PARA.
                EVALUATE WS-A
                    WHEN 1
                        MOVE 1 TO WS-B
                END-EVALUATE
                GOBACK.
        """)
        self.assertEqual(self.branches(self.unit("EVALUATE"))[-1],
                         ("WHEN OTHER", self.line("EVALUATE WS-A"), None, True))

    def test_whens_on_one_line_are_separate_branches(self):
        self.plan_body("""
            MAIN-PARA.
                EVALUATE WS-A WHEN 1 MOVE 1 TO WS-B WHEN 2 MOVE 2 TO WS-B
                END-EVALUATE
                GOBACK.
        """)
        self.assertEqual([(label, idx) for label, _, idx, _ in self.branches(self.unit("EVALUATE"))],
                         [("WHEN 1", self.unit("MOVE", 0).idx), ("WHEN 2", self.unit("MOVE", 1).idx),
                          ("WHEN OTHER", None)])

    def test_long_when_is_cut_in_the_label(self):
        self.plan_body("""
            MAIN-PARA.
                EVALUATE TRUE
                    WHEN WS-A GREATER THAN OR EQUAL TO WS-B
                        MOVE 1 TO WS-C
                END-EVALUATE
                GOBACK.
        """)
        label = self.labels(self.unit("EVALUATE"))[0]
        self.assertEqual(label, "WHEN WS-A GREATER THAN OR ...")

    def test_compound_when_of_evaluate_true_adds_operand_outcomes_on_its_line(self):
        self.plan_body("""
            MAIN-PARA.
                EVALUATE TRUE
                    WHEN WS-A = 1 AND WS-B = 1
                        MOVE 1 TO WS-C
                    WHEN WS-DONE
                        MOVE 2 TO WS-C
                END-EVALUATE
                GOBACK.
        """)
        ev = self.unit("EVALUATE")
        self.assertEqual(self.labels(ev),
                         ["WHEN WS-A = 1 AND WS-B = 1", "WS-A = 1 true", "WS-A = 1 false",
                          "WS-B = 1 true", "WS-B = 1 false", "WHEN WS-DONE", "WHEN OTHER"])
        self.assertEqual({line for _, line, _, _ in self.branches(ev, kinds=("COND",))},
                         {self.line("WHEN WS-A = 1 AND WS-B = 1")})

    def test_evaluate_on_a_subject_does_not_measure_operands(self):
        plan = self.plan_body("""
            MAIN-PARA.
                EVALUATE WS-A ALSO WS-B
                    WHEN 1 ALSO 2
                        MOVE 1 TO WS-C
                END-EVALUATE
                GOBACK.
        """)
        self.assertEqual(plan.counters, len(plan.units))

    def test_search_branches_with_and_without_at_end(self):
        self.plan_body("""
            MAIN-PARA.
                SEARCH WS-ENTRY
                    WHEN WS-ENTRY(WS-IX) = 1
                        MOVE 1 TO WS-A
                END-SEARCH
                SEARCH WS-ENTRY
                    AT END MOVE 0 TO WS-A
                    WHEN WS-ENTRY(WS-IX) = 2
                        MOVE 2 TO WS-A
                END-SEARCH
                GOBACK.
        """, data="""
            01  WS-A                      PIC 9.
            01  WS-TABLE.
                05  WS-ENTRY              PIC 9 OCCURS 5 INDEXED BY WS-IX.
        """)
        first, second = self.unit("SEARCH", 0), self.unit("SEARCH", 1)
        self.assertEqual([(label.split()[0], idx, implicit) for label, _, idx, implicit in self.branches(first)],
                         [("WHEN", self.unit("MOVE", 0).idx, False), ("AT", None, True)])
        self.assertEqual([(label, idx, implicit) for label, _, idx, implicit in self.branches(second)][0],
                         ("AT END", self.unit("MOVE", 1).idx, False))
        self.assertEqual(len(self.branches(second)), 2)


FILE_PROGRAM_HEAD = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. FILES.
    ENVIRONMENT DIVISION.
    INPUT-OUTPUT SECTION.
    FILE-CONTROL.
        SELECT IN-FILE ASSIGN TO "in.dat"
            ORGANIZATION IS INDEXED RECORD KEY IS IN-KEY.
    DATA DIVISION.
    FILE SECTION.
    FD  IN-FILE.
    01  IN-REC.
        05  IN-KEY                PIC X(4).
    WORKING-STORAGE SECTION.
    01  WS-A                      PIC 9(3).
    01  WS-B                      PIC 9(3).
    01  WS-FLAG                   PIC X.
        88  WS-DONE               VALUE "Y".
    PROCEDURE DIVISION.
    MAIN-PARA.
"""


class PlanPhraseBranchTest(PlanTestCase):
    def plan_statements(self, statements):
        return self.plan_program(support.blocks(FILE_PROGRAM_HEAD, statements))

    def test_at_end_alone_has_an_implicit_not_at_end(self):
        self.plan_statements("""
                READ IN-FILE
                    AT END SET WS-DONE TO TRUE
                END-READ
                GOBACK.
        """)
        self.assertEqual(self.branches(self.unit("READ")),
                         [("AT END", self.line("AT END"), self.unit("SET").idx, False),
                          ("NOT AT END", self.line("READ IN-FILE"), None, True)])

    def test_both_phrases_written_are_two_explicit_branches(self):
        self.plan_statements("""
                READ IN-FILE
                    INVALID KEY MOVE 1 TO WS-B
                    NOT INVALID KEY MOVE 2 TO WS-B
                END-READ
                GOBACK.
        """)
        self.assertEqual(self.branches(self.unit("READ")),
                         [("INVALID KEY", self.line("MOVE 1 TO WS-B"), self.unit("MOVE", 0).idx, False),
                          ("NOT INVALID KEY", self.line("MOVE 2 TO WS-B"), self.unit("MOVE", 1).idx, False)])

    def test_only_the_negative_phrase_written_makes_the_positive_one_implicit(self):
        self.plan_statements("""
                READ IN-FILE
                    NOT AT END ADD 1 TO WS-A
                END-READ
                GOBACK.
        """)
        self.assertEqual([(label, implicit) for label, _, _, implicit in self.branches(self.unit("READ"))],
                         [("AT END", True), ("NOT AT END", False)])

    def test_on_size_error(self):
        self.plan_statements("""
                ADD 1 TO WS-A ON SIZE ERROR MOVE 0 TO WS-A.
                GOBACK.
        """)
        self.assertEqual([(label, idx, implicit) for label, _, idx, implicit in self.branches(self.unit("ADD"))],
                         [("ON SIZE ERROR", self.unit("MOVE").idx, False), ("NOT ON SIZE ERROR", None, True)])

    def test_call_on_exception(self):
        self.plan_statements("""
                CALL "RATES" USING WS-A
                    ON EXCEPTION MOVE 9 TO WS-B
                END-CALL
                GOBACK.
        """)
        self.assertEqual([label for label, _, _, _ in self.branches(self.unit("CALL"))],
                         ["ON EXCEPTION", "NOT ON EXCEPTION"])

    def test_statement_without_phrases_has_no_branches(self):
        plan = self.plan_statements("""
                READ IN-FILE.
                CALL "RATES" USING WS-A.
                GO TO MAIN-PARA.
        """)
        self.assertEqual(plan.branches, [])

    def test_go_to_depending_has_a_branch_per_target_and_an_implicit_fall_through(self):
        plan = self.plan_statements("""
                GO TO FIRST-PARA SECOND-PARA DEPENDING ON WS-A.
                GOBACK.
            FIRST-PARA.
                GOBACK.
            SECOND-PARA.
                GOBACK.
        """)
        n = len(plan.units)
        at = self.line("GO TO FIRST-PARA")
        self.assertEqual(self.branches(self.unit("GO")),
                         [("GO TO FIRST-PARA", at, n + 1, False), ("GO TO SECOND-PARA", at, n + 2, False),
                          ("no jump", at, None, True)])

    def test_go_to_depending_counts_the_target_with_an_evaluate_before_the_jump(self):
        plan = self.plan_statements("""
                GO TO FIRST-PARA SECOND-PARA DEPENDING ON WS-A.
                GOBACK.
            FIRST-PARA.
                GOBACK.
            SECOND-PARA.
                GOBACK.
        """)
        n = len(plan.units)
        self.assertEqual([ln.strip() for ln in self.inserts_before(self.unit("GO"))],
                         [add_line(self.unit("GO").idx), "EVALUATE WS-A", "WHEN 1", add_line(n + 1),
                          "WHEN 2", add_line(n + 2), "END-EVALUATE"])


class PlanToJsonTest(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                END-IF
                GOBACK.
        """, program_id="MAPPED")
        self.map = self.plan.to_json("src/MAPPED.cbl")

    def test_is_json_serializable(self):
        self.assertEqual(json.loads(json.dumps(self.map)), self.map)

    def test_header(self):
        self.assertEqual((self.map["program"], self.map["file"], self.map["counters"]),
                         ("MAPPED", "src/MAPPED.cbl", 3))

    def test_paragraph_entry(self):
        self.assertEqual(self.map["paragraphs"],
                         [{"name": "MAIN-PARA", "line": self.line("MAIN-PARA."),
                           "end_line": self.line("GOBACK."), "section": False}])

    def test_unit_entry(self):
        self.assertEqual(self.map["units"][0],
                         {"idx": 1, "verb": "IF", "line": self.line("IF WS-A = 1"), "end_line": self.line("END-IF"),
                          "file": self.prog.path, "paragraph": "MAIN-PARA"})

    def test_branch_entries(self):
        at = self.line("IF WS-A = 1")
        common = {"stmt": 1, "kind": "IF", "line": at, "file": self.prog.path, "paragraph": "MAIN-PARA"}
        self.assertEqual(self.map["branches"],
                         [dict(common, label="THEN", idx=2, implicit=False),
                          dict(common, label="ELSE", idx=None, implicit=True)])

    def test_map_survives_saving_and_loading(self):
        path = os.path.join(self.tmp, "map.json")
        coverage.save_map({"MAPPED": self.map}, path)
        self.assertEqual(coverage.load_map(path), {"MAPPED": self.map})

    def test_saved_map_carries_the_schema_and_the_version_of_the_cli(self):
        path = os.path.join(self.tmp, "map.json")
        coverage.save_map({"MAPPED": self.map}, path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual((data["schema"], data["cobalto"], list(data["programs"])),
                         (SCHEMA, VERSION, ["MAPPED"]))

    def test_map_from_before_the_schema_field_is_still_read(self):
        path = os.path.join(self.tmp, "map.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"MAPPED": self.map}, fh)
        self.assertEqual(coverage.load_map(path), {"MAPPED": self.map})


# ----------------------------------------------------------------- reports
def unit(idx, verb, line, para, end_line=None, file="src/DEMO.cbl"):
    return {"idx": idx, "verb": verb, "line": line, "end_line": end_line or line, "file": file, "paragraph": para}


def branch(stmt, label, line, para, idx=None, kind="IF", file="src/DEMO.cbl"):
    return {"stmt": stmt, "kind": kind, "label": label, "line": line, "file": file,
            "paragraph": para, "idx": idx, "implicit": idx is None}


def paragraph(name, line, end_line, section=False):
    return {"name": name, "line": line, "end_line": end_line, "section": section}


def program_map(name, file, paragraphs, units, branches=()):
    counters = max([u["idx"] for u in units] + [b["idx"] for b in branches if b["idx"]] + [0])
    return {"program": name, "file": file, "counters": counters, "paragraphs": list(paragraphs),
            "units": list(units), "branches": list(branches)}


# A program with an IF / ELSE in MAIN (lines 11-15), a compound IF without
# ELSE in CALC (line 18), two statements on line 21, a paragraph with nothing
# to instrument (DONE) and a paragraph that the tests below never execute.
DEMO = program_map(
    "DEMO", "src/DEMO.cbl",
    [paragraph("MAIN", 10, 16), paragraph("CALC", 17, 21), paragraph("DONE", 22, 23), paragraph("NEVER", 24, 25)],
    [unit(1, "IF", 11, "MAIN", 15), unit(2, "MOVE", 12, "MAIN"), unit(3, "MOVE", 14, "MAIN"),
     unit(4, "PERFORM", 16, "MAIN"),
     unit(5, "IF", 18, "CALC", 20), unit(6, "MOVE", 19, "CALC"),
     unit(7, "ADD", 21, "CALC"), unit(8, "MOVE", 21, "CALC"),
     unit(9, "DISPLAY", 25, "NEVER")],
    [branch(1, "THEN", 11, "MAIN", 2), branch(1, "ELSE", 13, "MAIN", 3),
     branch(5, "WS-A = 1 true", 18, "CALC", 10, "COND"), branch(5, "WS-A = 1 false", 18, "CALC", 11, "COND"),
     branch(5, "THEN", 18, "CALC", 6), branch(5, "ELSE", 18, "CALC")])
DEMO_MAP = {"DEMO": DEMO}
# MAIN ran three times and always took THEN; CALC ran three times, its IF was
# true once; the MOVE on line 21 and the paragraph NEVER did not run.
DEMO_HITS = {"DEMO": {1: 3, 2: 3, 4: 3, 5: 3, 6: 1, 7: 3, 10: 1, 11: 2}}

# The MAIN paragraph alone, for the checks that compare a whole report.
SMALL_MAP = {"SMALL": program_map(
    "SMALL", "src/SMALL.cbl", [paragraph("MAIN", 10, 16)],
    [unit(1, "IF", 11, "MAIN", 15, "src/SMALL.cbl"), unit(2, "MOVE", 12, "MAIN", file="src/SMALL.cbl"),
     unit(3, "MOVE", 14, "MAIN", file="src/SMALL.cbl"), unit(4, "PERFORM", 16, "MAIN", file="src/SMALL.cbl")],
    [branch(1, "THEN", 11, "MAIN", 2, file="src/SMALL.cbl"), branch(1, "ELSE", 13, "MAIN", 3, file="src/SMALL.cbl")])}
SMALL_HITS = {"SMALL": {1: 3, 2: 3, 4: 3}}


class ParseRecordsTest(unittest.TestCase):
    def test_coverage_records_become_counts_by_program_and_index(self):
        hits = coverage.parse_records(["C|DEMO|1|3", "C|DEMO|2|1", "C|OTHER|1|7"])
        self.assertEqual(hits, {"DEMO": {1: 3, 2: 1}, "OTHER": {1: 7}})

    def test_padded_program_name_and_zero_filled_numbers(self):
        hits = coverage.parse_records(["C|DEMO                          |00012|000000345"])
        self.assertEqual(hits, {"DEMO": {12: 345}})

    def test_records_of_other_kinds_are_ignored(self):
        records = ["T|TSTDEMO", "A|P|00001|EQ      |a|a|m", "E|TSTDEMO", "C|DEMO|1|3", "S|1|1|0"]
        self.assertEqual(coverage.parse_records(records), {"DEMO": {1: 3}})

    def test_incomplete_or_non_numeric_records_are_skipped(self):
        self.assertEqual(coverage.parse_records(["C|DEMO|1", "C|DEMO|x|3", "C|DEMO|2|many", "C|DEMO|4|1"]),
                         {"DEMO": {4: 1}})


class BranchCountsTest(unittest.TestCase):
    def counts(self, hits):
        return {(b["stmt"], b["label"]): c for b, c in coverage.branch_counts(DEMO, hits)}

    def test_explicit_branch_has_the_count_of_its_counter(self):
        counts = self.counts(DEMO_HITS["DEMO"])
        self.assertEqual((counts[(1, "THEN")], counts[(1, "ELSE")]), (3, 0))

    def test_implicit_branch_is_entries_minus_explicit_branches(self):
        self.assertEqual(self.counts(DEMO_HITS["DEMO"])[(5, "ELSE")], 2)

    def test_operand_outcomes_are_not_subtracted_from_the_implicit_branch(self):
        counts = self.counts(DEMO_HITS["DEMO"])
        self.assertEqual((counts[(5, "WS-A = 1 true")], counts[(5, "WS-A = 1 false")]), (1, 2))

    def test_implicit_branch_is_never_negative(self):
        self.assertEqual(self.counts({5: 1, 6: 4})[(5, "ELSE")], 0)

    def test_without_hits_every_branch_is_zero(self):
        self.assertEqual(set(self.counts({}).values()), {0})

    def test_branches_keep_the_order_of_the_map(self):
        self.assertEqual([b["label"] for b, _ in coverage.branch_counts(DEMO, {})],
                         [b["label"] for b in DEMO["branches"]])


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.summary = coverage.summarize(DEMO_MAP, DEMO_HITS)
        self.rows = {row["name"]: row for row in self.summary[0]["rows"]}

    def test_one_entry_per_program_with_its_file(self):
        self.assertEqual([(s["program"], s["file"]) for s in self.summary], [("DEMO", "src/DEMO.cbl")])

    def test_statement_totals(self):
        self.assertEqual(self.summary[0]["statements"], {"hit": 6, "total": 9})

    def test_branch_totals_include_operand_outcomes_and_implicit_branches(self):
        self.assertEqual(self.summary[0]["branches"], {"hit": 5, "total": 6})

    def test_paragraph_totals_leave_out_paragraphs_without_statements(self):
        self.assertEqual(self.summary[0]["paragraphs"], {"hit": 2, "total": 3})

    def test_rows_follow_the_order_of_the_paragraphs(self):
        self.assertEqual([row["name"] for row in self.summary[0]["rows"]], ["MAIN", "CALC", "DONE", "NEVER"])

    def test_entries_of_a_paragraph_are_the_count_of_its_first_statement(self):
        self.assertEqual(self.rows["MAIN"]["entries"], 3)

    def test_row_counts_statements_and_lists_the_lines_not_executed(self):
        self.assertEqual(self.rows["MAIN"]["statements"], {"hit": 3, "total": 4})
        self.assertEqual(self.rows["MAIN"]["missed_lines"], [14])

    def test_line_with_one_statement_not_executed_is_listed(self):
        self.assertEqual(self.rows["CALC"]["missed_lines"], [21])

    def test_row_counts_branches_and_lists_the_ones_not_executed(self):
        self.assertEqual(self.rows["MAIN"]["branches"], {"hit": 1, "total": 2})
        self.assertEqual(self.rows["MAIN"]["missed_branches"], ["13 ELSE"])

    def test_row_with_every_branch_executed(self):
        self.assertEqual(self.rows["CALC"]["branches"], {"hit": 4, "total": 4})
        self.assertEqual(self.rows["CALC"]["missed_branches"], [])

    def test_paragraph_without_statements_has_no_entries(self):
        self.assertEqual(self.rows["DONE"], {"name": "DONE", "section": False, "entries": None,
                                             "statements": {"hit": 0, "total": 0}, "missed_lines": [],
                                             "branches": {"hit": 0, "total": 0}, "missed_branches": []})

    def test_paragraph_never_executed_has_zero_entries(self):
        self.assertEqual((self.rows["NEVER"]["entries"], self.rows["NEVER"]["statements"]),
                         (0, {"hit": 0, "total": 1}))

    def test_missed_implicit_branch_is_marked_as_implicit(self):
        hits = {"DEMO": {5: 2, 6: 2, 10: 2}}
        rows = {row["name"]: row for row in coverage.summarize(DEMO_MAP, hits)[0]["rows"]}
        self.assertEqual(rows["CALC"]["missed_branches"], ["18 WS-A = 1 false", "18 ELSE implicit"])

    def test_program_without_any_record_counts_nothing_as_executed(self):
        summary = coverage.summarize(DEMO_MAP, {})[0]
        self.assertEqual((summary["paragraphs"], summary["statements"], summary["branches"]),
                         ({"hit": 0, "total": 3}, {"hit": 0, "total": 9}, {"hit": 0, "total": 6}))

    def test_missed_lines_are_sorted_and_not_repeated(self):
        rows = {row["name"]: row for row in coverage.summarize(DEMO_MAP, {"DEMO": {5: 1}})[0]["rows"]}
        self.assertEqual(rows["CALC"]["missed_lines"], [19, 21])

    def test_section_rows_are_flagged(self):
        sectioned = {"SECT": program_map("SECT", "src/SECT.cbl",
                                         [paragraph("MAIN-LOGIC", 5, 5, section=True), paragraph("MAIN", 6, 7)],
                                         [unit(1, "GOBACK", 7, "MAIN", file="src/SECT.cbl")])}
        rows = coverage.summarize(sectioned, {})[0]["rows"]
        self.assertEqual([(row["name"], row["section"]) for row in rows], [("MAIN-LOGIC", True), ("MAIN", False)])

    def test_summary_is_json_serializable(self):
        self.assertEqual(json.loads(json.dumps(self.summary)), self.summary)

    def test_several_programs_are_summarized_separately(self):
        both = dict(DEMO_MAP, **SMALL_MAP)
        summary = coverage.summarize(both, dict(DEMO_HITS, **SMALL_HITS))
        self.assertEqual([(s["program"], s["statements"]) for s in summary],
                         [("DEMO", {"hit": 6, "total": 9}), ("SMALL", {"hit": 3, "total": 4})])


class PrintReportTest(unittest.TestCase):
    def report(self, cov_map, hits):
        lines = []
        coverage.print_report(coverage.summarize(cov_map, hits), out=lines.append)
        return lines

    def row(self, lines, name):
        return next(ln for ln in lines if ln.split()[:1] == [name])

    def test_empty_summary_prints_nothing(self):
        self.assertEqual(self.report({}, {}), [])

    def test_program_line_has_totals_and_percentages(self):
        line = next(ln for ln in self.report(DEMO_MAP, DEMO_HITS) if "(DEMO)" in ln)
        self.assertEqual(line.split(), ["src/DEMO.cbl", "(DEMO)", "paragraphs", "2/3", "statements", "6/9", "66%",
                                        "branches", "5/6", "83%"])

    def test_paragraph_row_has_entries_statements_and_branches(self):
        row = self.row(self.report(DEMO_MAP, DEMO_HITS), "MAIN")
        self.assertEqual(row.split()[:6], ["MAIN", "3x", "3/4", "75%", "branches", "1/2"])

    def test_paragraph_row_lists_what_was_not_executed(self):
        row = self.row(self.report(DEMO_MAP, DEMO_HITS), "MAIN")
        self.assertIn("statements not executed on lines 14", row)
        self.assertIn("branches not executed: 13 ELSE", row)

    def test_paragraph_that_did_not_run_is_marked(self):
        row = self.row(self.report(DEMO_MAP, DEMO_HITS), "NEVER")
        self.assertTrue(row.endswith("NOT EXECUTED"))

    def test_paragraph_without_statements_is_marked(self):
        row = self.row(self.report(DEMO_MAP, DEMO_HITS), "DONE")
        self.assertIn("(no instrumentable statements)", row)

    def test_section_rows_say_section(self):
        sectioned = {"SECT": program_map("SECT", "src/SECT.cbl", [paragraph("MAIN-LOGIC", 5, 6, section=True)],
                                         [unit(1, "GOBACK", 6, "MAIN-LOGIC", file="src/SECT.cbl")])}
        row = self.row(self.report(sectioned, {"SECT": {1: 1}}), "MAIN-LOGIC")
        self.assertEqual(row.split()[:2], ["MAIN-LOGIC", "SECTION"])

    def test_single_program_has_no_total_line(self):
        self.assertEqual([ln for ln in self.report(DEMO_MAP, DEMO_HITS) if ln.split()[:1] == ["TOTAL"]], [])

    def test_several_programs_get_a_total_line(self):
        lines = self.report(dict(DEMO_MAP, **SMALL_MAP), dict(DEMO_HITS, **SMALL_HITS))
        total = next(ln for ln in lines if ln.split()[:1] == ["TOTAL"])
        self.assertEqual(total.split(), ["TOTAL", "paragraphs", "3/4", "statements", "9/13", "69%",
                                         "branches", "6/8", "75%"])


class ReportFileTestCase(TempDirTestCase):
    writer = None

    def written(self, cov_map, hits):
        path = os.path.join(self.tmp, "report.out")
        type(self).writer(cov_map, hits, path)
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()


class LcovTest(ReportFileTestCase):
    writer = staticmethod(coverage.write_lcov)

    def records(self, cov_map, hits):
        return self.written(cov_map, hits).splitlines()

    def test_whole_record_of_a_small_program(self):
        self.assertEqual(self.records(SMALL_MAP, SMALL_HITS),
                         ["TN:",
                          "SF:src/SMALL.cbl",
                          "FN:10,MAIN",
                          "FNDA:3,MAIN",
                          "FNF:1",
                          "FNH:1",
                          "BRDA:11,1,0,3",
                          "BRDA:11,1,1,0",
                          "BRF:2",
                          "BRH:1",
                          "DA:11,3",
                          "DA:12,3",
                          "DA:14,0",
                          "DA:16,3",
                          "LF:4",
                          "LH:3",
                          "end_of_record"])

    def test_file_ends_with_a_newline_and_uses_unix_line_ends(self):
        text = self.written(SMALL_MAP, SMALL_HITS)
        self.assertTrue(text.endswith("end_of_record\n"))
        self.assertNotIn("\r", text)

    def test_functions_are_the_paragraphs_that_have_statements(self):
        records = self.records(DEMO_MAP, DEMO_HITS)
        self.assertEqual([r for r in records if r.startswith("FN:")], ["FN:10,MAIN", "FN:17,CALC", "FN:24,NEVER"])
        self.assertEqual([r for r in records if r.startswith("FNDA:")], ["FNDA:3,MAIN", "FNDA:3,CALC", "FNDA:0,NEVER"])
        self.assertIn("FNF:3", records)
        self.assertIn("FNH:2", records)

    def test_line_with_two_statements_reports_the_highest_count(self):
        self.assertIn("DA:21,3", self.records(DEMO_MAP, DEMO_HITS))

    def test_line_totals(self):
        records = self.records(DEMO_MAP, DEMO_HITS)
        self.assertIn("LF:8", records)
        self.assertIn("LH:6", records)

    def test_branches_are_numbered_per_statement_on_the_line_of_the_statement(self):
        records = self.records(DEMO_MAP, DEMO_HITS)
        self.assertEqual([r for r in records if r.startswith("BRDA:18,")],
                         ["BRDA:18,5,0,1", "BRDA:18,5,1,2", "BRDA:18,5,2,1", "BRDA:18,5,3,2"])
        self.assertIn("BRDA:11,1,1,0", records)     # the ELSE written on line 13 belongs to the IF of line 11

    def test_branch_totals(self):
        records = self.records(DEMO_MAP, DEMO_HITS)
        self.assertIn("BRF:6", records)
        self.assertIn("BRH:5", records)

    def test_one_record_per_source_file(self):
        with_copybook = {"COPIED": program_map(
            "COPIED", "src/COPIED.cbl", [paragraph("MAIN", 10, 12)],
            [unit(1, "MOVE", 11, "MAIN", file="src/COPIED.cbl"), unit(2, "MOVE", 3, "MAIN", file="src/SHARED.cpy")])}
        records = self.records(with_copybook, {"COPIED": {1: 1}})
        self.assertEqual([r for r in records if r.startswith(("SF:", "DA:", "end_of"))],
                         ["SF:src/COPIED.cbl", "DA:11,1", "end_of_record",
                          "SF:src/SHARED.cpy", "DA:3,0", "end_of_record"])

    def test_one_record_per_program(self):
        records = self.records(dict(DEMO_MAP, **SMALL_MAP), {})
        self.assertEqual([r for r in records if r.startswith("SF:")], ["SF:src/DEMO.cbl", "SF:src/SMALL.cbl"])
        self.assertEqual(records.count("end_of_record"), 2)

    def test_program_without_records_reports_zero_counts(self):
        records = self.records(SMALL_MAP, {})
        self.assertEqual([r for r in records if r.startswith("DA:")], ["DA:11,0", "DA:12,0", "DA:14,0", "DA:16,0"])
        self.assertIn("LH:0", records)

    def test_empty_map_writes_an_empty_file(self):
        self.assertEqual(self.written({}, {}), "")


class CoberturaTest(ReportFileTestCase):
    writer = staticmethod(coverage.write_cobertura)

    def root(self, cov_map=None, hits=None):
        return ET.fromstring(self.written(DEMO_MAP if cov_map is None else cov_map,
                                          DEMO_HITS if hits is None else hits).encode("utf-8"))

    def test_starts_with_the_xml_declaration(self):
        self.assertTrue(self.written(DEMO_MAP, DEMO_HITS).startswith('<?xml version="1.0" encoding="UTF-8"?>\n'))

    def test_root_has_line_and_branch_totals(self):
        root = self.root()
        self.assertEqual(root.tag, "coverage")
        self.assertEqual({k: root.get(k) for k in ("lines-covered", "lines-valid", "branches-covered",
                                                    "branches-valid", "line-rate", "branch-rate")},
                         {"lines-covered": "6", "lines-valid": "8", "branches-covered": "5",
                          "branches-valid": "6", "line-rate": "0.7500", "branch-rate": "0.8333"})

    def test_root_has_a_numeric_timestamp(self):
        self.assertTrue(self.root().get("timestamp").isdigit())

    def test_sources_and_package_wrap_the_classes(self):
        root = self.root()
        self.assertEqual([s.text for s in root.findall("sources/source")], ["."])
        self.assertEqual(len(root.findall("packages/package/classes/class")), 1)

    def test_class_is_the_program_with_its_file_and_rates(self):
        cls = self.root().find("packages/package/classes/class")
        self.assertEqual((cls.get("name"), cls.get("filename"), cls.get("line-rate"), cls.get("branch-rate")),
                         ("DEMO", "src/DEMO.cbl", "0.7500", "0.8333"))

    def test_methods_are_the_paragraphs_with_statements(self):
        methods = self.root().findall("packages/package/classes/class/methods/method")
        self.assertEqual([(m.get("name"), m.get("line-rate")) for m in methods],
                         [("MAIN", "0.7500"), ("CALC", "0.7500"), ("NEVER", "0.0000")])

    def test_method_points_at_the_paragraph_line_with_its_entries(self):
        method = self.root().find("packages/package/classes/class/methods/method")
        self.assertEqual([(ln.get("number"), ln.get("hits")) for ln in method.findall("lines/line")], [("10", "3")])

    def test_lines_have_number_and_hits(self):
        lines = self.root().findall("packages/package/classes/class/lines/line")
        self.assertEqual([(ln.get("number"), ln.get("hits")) for ln in lines],
                         [("11", "3"), ("12", "3"), ("14", "0"), ("16", "3"), ("18", "3"), ("19", "1"),
                          ("21", "3"), ("25", "0")])

    def test_line_of_a_statement_with_branches_has_condition_coverage(self):
        lines = {ln.get("number"): ln for ln in self.root().findall("packages/package/classes/class/lines/line")}
        self.assertEqual((lines["11"].get("branch"), lines["11"].get("condition-coverage")), ("true", "50% (1/2)"))
        self.assertEqual(lines["18"].get("condition-coverage"), "100% (4/4)")
        self.assertEqual(lines["11"].find("conditions/condition").get("coverage"), "50%")

    def test_line_without_branches_says_so(self):
        lines = {ln.get("number"): ln for ln in self.root().findall("packages/package/classes/class/lines/line")}
        self.assertEqual(lines["12"].get("branch"), "false")
        self.assertIsNone(lines["12"].get("condition-coverage"))

    def test_names_with_xml_characters_are_escaped(self):
        odd = {"R&D": program_map("R&D", "src/R&D<1>.cbl", [paragraph("A&B", 1, 2)],
                                  [unit(1, "GOBACK", 2, "A&B", file="src/R&D<1>.cbl")])}
        cls = self.root(odd, {}).find("packages/package/classes/class")
        self.assertEqual((cls.get("name"), cls.get("filename")), ("R&D", "src/R&D<1>.cbl"))
        self.assertEqual(cls.find("methods/method").get("name"), "A&B")

    def test_empty_map_is_still_a_valid_report(self):
        root = self.root({}, {})
        self.assertEqual((root.get("lines-valid"), root.get("line-rate")), ("0", "0.0000"))
        self.assertEqual(root.findall("packages/package/classes/class"), [])


class SonarTest(ReportFileTestCase):
    writer = staticmethod(coverage.write_sonar)

    def root(self, cov_map=None, hits=None):
        return ET.fromstring(self.written(DEMO_MAP if cov_map is None else cov_map,
                                          DEMO_HITS if hits is None else hits).encode("utf-8"))

    def lines(self, **kw):
        return {ln.get("lineNumber"): dict(ln.attrib) for ln in self.root(**kw).findall("file/lineToCover")}

    def test_whole_report_of_a_small_program(self):
        self.assertEqual(self.written(SMALL_MAP, SMALL_HITS).splitlines(),
                         ['<?xml version="1.0" encoding="UTF-8"?>',
                          '<coverage version="1">',
                          '  <file path="src/SMALL.cbl">',
                          '    <lineToCover lineNumber="11" covered="true" branchesToCover="2" coveredBranches="1"/>',
                          '    <lineToCover lineNumber="12" covered="true"/>',
                          '    <lineToCover lineNumber="14" covered="false"/>',
                          '    <lineToCover lineNumber="16" covered="true"/>',
                          '  </file>',
                          '</coverage>'])

    def test_root_is_generic_coverage_version_1(self):
        root = self.root()
        self.assertEqual((root.tag, root.attrib), ("coverage", {"version": "1"}))

    def test_one_file_element_per_source_file(self):
        self.assertEqual([f.get("path") for f in self.root().findall("file")], ["src/DEMO.cbl"])

    def test_one_line_to_cover_per_line_with_statements_in_order(self):
        numbers = [ln.get("lineNumber") for ln in self.root().findall("file/lineToCover")]
        self.assertEqual(numbers, ["11", "12", "14", "16", "18", "19", "21", "25"])

    def test_plain_line_only_says_whether_it_was_covered(self):
        lines = self.lines()
        self.assertEqual(lines["12"], {"lineNumber": "12", "covered": "true"})
        self.assertEqual(lines["25"], {"lineNumber": "25", "covered": "false"})

    def test_line_of_a_statement_with_branches_declares_them(self):
        self.assertEqual(self.lines()["11"], {"lineNumber": "11", "covered": "true",
                                              "branchesToCover": "2", "coveredBranches": "1"})

    def test_operand_outcomes_and_the_implicit_branch_count_as_branches(self):
        line = self.lines()["18"]
        self.assertEqual((line["branchesToCover"], line["coveredBranches"]), ("4", "4"))

    def test_line_with_several_statements_is_declared_as_branches(self):
        self.assertEqual(self.lines()["21"], {"lineNumber": "21", "covered": "true",
                                              "branchesToCover": "2", "coveredBranches": "1"})

    def test_statements_from_a_copybook_go_to_its_own_file_element(self):
        with_copybook = {"COPIED": program_map(
            "COPIED", "src/COPIED.cbl", [paragraph("MAIN", 10, 12)],
            [unit(1, "MOVE", 11, "MAIN", file="src/COPIED.cbl"), unit(2, "MOVE", 3, "MAIN", file="src/SHARED.cpy")])}
        root = self.root(with_copybook, {"COPIED": {2: 1}})
        self.assertEqual([(f.get("path"), [ln.attrib for ln in f]) for f in root.findall("file")],
                         [("src/COPIED.cbl", [{"lineNumber": "11", "covered": "false"}]),
                          ("src/SHARED.cpy", [{"lineNumber": "3", "covered": "true"}])])

    def test_path_with_xml_characters_is_escaped(self):
        odd = {"ODD": program_map("ODD", 'src/R&D "v2".cbl', [paragraph("MAIN", 1, 2)],
                                  [unit(1, "GOBACK", 2, "MAIN", file='src/R&D "v2".cbl')])}
        self.assertEqual([f.get("path") for f in self.root(odd, {}).findall("file")], ['src/R&D "v2".cbl'])

    def test_empty_map_is_still_a_valid_report(self):
        self.assertEqual(list(self.root({}, {})), [])


class PlanToReportTest(PlanTestCase):
    """The map of a real plan feeds the summary without any adaptation."""

    def setUp(self):
        super().setUp()
        self.plan_body("""
            MAIN-PARA.
                IF WS-A = 1 AND WS-B = 2
                    MOVE 1 TO WS-C
                END-IF
                GOBACK.
        """, program_id="FLOW")
        self.cov_map = {"FLOW": self.plan.to_json("src/FLOW.cbl")}

    def summary(self, counts):
        return coverage.summarize(self.cov_map, {"FLOW": counts})[0]

    def test_all_counters_hit_cover_every_statement(self):
        counts = {i: 1 for i in range(1, self.plan.counters + 1)}
        self.assertEqual(self.summary(counts)["statements"], {"hit": 3, "total": 3})

    def test_if_never_true_leaves_then_and_the_true_outcomes_uncovered(self):
        if_idx, move_idx, goback_idx = (u.idx for u in self.plan.units)
        first_false = next(b.idx for b in self.plan.branches if b.label == "WS-A = 1 false")
        summary = self.summary({if_idx: 2, goback_idx: 2, first_false: 2})
        at = self.line("IF WS-A = 1")
        self.assertEqual(summary["branches"], {"hit": 2, "total": 6})
        self.assertEqual(summary["rows"][0]["missed_branches"],
                         [f"{at} WS-A = 1 true", f"{at} WS-B = 2 true", f"{at} WS-B = 2 false", f"{at} THEN"])
        self.assertEqual(summary["rows"][0]["missed_lines"], [self.line("MOVE 1 TO WS-C")])


class ExampleProgramsTest(unittest.TestCase):
    """Consistency of the plan on the programs of examples/src."""

    SOURCES = sorted(glob.glob(os.path.join(support.EXAMPLES, "src", "*.cbl")))

    def plans(self):
        self.assertTrue(self.SOURCES)
        for path in self.SOURCES:
            with self.subTest(source=os.path.basename(path)):
                yield Plan(Program(path, [os.path.dirname(path)]))

    def test_statement_counters_are_numbered_from_one_without_gaps(self):
        for plan in self.plans():
            self.assertEqual([u.idx for u in plan.units], list(range(1, len(plan.units) + 1)))

    def test_every_counter_of_the_table_is_added_somewhere(self):
        for plan in self.plans():
            added = set()
            for lines in plan.inserts.values():
                for ln in lines:
                    text = ln.strip()
                    if text.startswith(f"ADD 1 TO {HIT_ITEM}("):
                        added.add(int(text[len(f"ADD 1 TO {HIT_ITEM}("):-1]))
            self.assertEqual(added, set(range(1, plan.counters + 1)))

    def test_branches_refer_to_statements_and_counters_of_the_plan(self):
        for plan in self.plans():
            for b in plan.branches:
                self.assertIn(b.stmt, range(1, len(plan.units) + 1))
                self.assertEqual(b.implicit, b.idx is None)
                if b.idx is not None:
                    self.assertIn(b.idx, range(1, plan.counters + 1))

    def test_every_statement_belongs_to_a_listed_paragraph(self):
        for plan in self.plans():
            listed = {name for name, _, _, _ in plan.paragraphs}
            self.assertLessEqual({u.para for u in plan.units}, listed)

    def test_leap_year_if_of_loancalc_has_eight_branches(self):
        # docs/reference.md: the three-operand IF of 1300-LEAP-YEAR is declared with branchesToCover="8".
        plan = Plan(Program(os.path.join(support.EXAMPLES, "src", "LOANCALC.cbl")))
        leap_if = next(u for u in plan.units if u.para == "1300-LEAP-YEAR" and u.verb == "IF")
        labels = [b.label for b in plan.branches if b.stmt == leap_if.idx]
        self.assertEqual(len(labels), 8)
        self.assertIn("WS-REM-100 NOT = ZERO false", labels)
        self.assertIn("WS-REM-400 = ZERO true", labels)


if __name__ == "__main__":
    unittest.main()
