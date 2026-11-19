"""Unit tests for cobalto.cobparse, the COBOL parser.

The programs are small and synthetic, written inline. No compiler is needed.
"""
import glob
import json
import os
import unittest

import support
from support import TempDirTestCase, fixed, line_of, statement, text_of

from cobalto import cobparse
from cobalto.cobparse import TERMINATORS, VERBS, ParseError, Program, describe, summary


def card(code, indicator=" ", sequence="", identification=""):
    """One fixed-format line from its areas: sequence (columns 1-6),
    indicator (7), code (8-72, given relative to column 8) and
    identification (73-80)."""
    line = sequence.ljust(6)[:6] + indicator + code
    if identification:
        line = line.ljust(72) + identification
    return line


def verbs(prog):
    return [st.verb for st in prog.statements]


def names(paragraphs):
    return [p.name for p in paragraphs]


class FixedFormatTest(TempDirTestCase):
    """Columns 1-6, 7, 8-72 and 73-80 of the fixed format."""

    HEAD = [card("IDENTIFICATION DIVISION."),
            card("PROGRAM-ID. CARDS."),
            card("DATA DIVISION."),
            card("WORKING-STORAGE SECTION."),
            card("01  WS-TOTAL                  PIC 9(3)."),
            card("01  WS-MSG                    PIC X(40)."),
            card("PROCEDURE DIVISION."),
            card("MAIN-PARA.")]

    def parse_cards(self, cards, head=None):
        lines = (self.HEAD if head is None else head) + cards
        return Program(self.write("CARDS.cbl", "\n".join(lines) + "\n"))

    def test_sequence_area_is_not_code(self):
        prog = self.parse_cards([card("IDENTIFICATION DIVISION.", sequence="000100"),
                                 card("PROGRAM-ID. CARDS.", sequence="000200"),
                                 card("PROCEDURE DIVISION.", sequence="MOVE01"),
                                 card("MAIN-PARA.", sequence="STOP02"),
                                 card("    GOBACK.", sequence="000500")], head=[])
        self.assertEqual(prog.fmt, "fixed")
        self.assertEqual(prog.program_id, "CARDS")
        self.assertEqual(names(prog.paragraphs), ["MAIN-PARA"])
        self.assertEqual(verbs(prog), ["GOBACK"])

    def test_identification_area_is_not_code(self):
        prog = self.parse_cards([card("    MOVE 1 TO WS-TOTAL.", identification="GOBACK. "),
                                 card("    STOP RUN.", identification="CARD0002")])
        self.assertEqual(verbs(prog), ["MOVE", "STOP"])

    def test_asterisk_in_column_7_is_a_comment(self):
        prog = self.parse_cards([card("    MOVE 1 TO WS-TOTAL.", indicator="*"),
                                 card("    GOBACK.")])
        self.assertEqual(verbs(prog), ["GOBACK"])

    def test_slash_in_column_7_is_a_comment(self):
        prog = self.parse_cards([card("    MOVE 1 TO WS-TOTAL.", indicator="/"),
                                 card("    GOBACK.")])
        self.assertEqual(verbs(prog), ["GOBACK"])

    def test_debugging_line_is_not_code(self):
        prog = self.parse_cards([card('    DISPLAY "trace".', indicator="D"),
                                 card("    GOBACK.")])
        self.assertEqual(verbs(prog), ["GOBACK"])

    def test_inline_comment_ends_the_code_of_the_line(self):
        prog = self.parse_cards([card("    MOVE 1 TO WS-TOTAL *> MOVE 2 TO WS-TOTAL."),
                                 card("    GOBACK.")])
        self.assertEqual(verbs(prog), ["MOVE", "GOBACK"])
        self.assertEqual(text_of(prog, statement(prog, "MOVE")), "MOVE 1 TO WS-TOTAL")

    def test_literal_continues_with_hyphen_in_column_7(self):
        prog = self.parse_cards([card('    MOVE "first half of the te'),
                                 card('    "xt. second half" TO WS-MSG.', indicator="-"),
                                 card("    GOBACK.")])
        self.assertEqual(verbs(prog), ["MOVE", "GOBACK"])
        literals = [t.text for t in prog.tokens if t.kind == "lit"]
        self.assertEqual(literals, ['"first half of the text. second half"'])

    def test_continued_statement_ends_on_the_continuation_line(self):
        prog = self.parse_cards([card('    MOVE "first half of the te'),
                                 card('    "xt. second half" TO WS-MSG.', indicator="-"),
                                 card("    GOBACK.")])
        move = statement(prog, "MOVE")
        self.assertEqual((move.line, move.end_line), (9, 10))

    def test_word_continues_with_hyphen_in_column_7(self):
        prog = self.parse_cards([card("    MOVE 1 TO WS-TO"),
                                 card("        TAL.", indicator="-"),
                                 card("    GOBACK.")])
        self.assertEqual(text_of(prog, statement(prog, "MOVE")), "MOVE 1 TO WS-TOTAL")

    def test_blank_line_inside_a_statement_does_not_end_it(self):
        prog = self.parse_cards([card("    MOVE 1"), "", "      ", card("        TO WS-TOTAL."),
                                 card("    GOBACK.")])
        self.assertEqual(text_of(prog, statement(prog, "MOVE")), "MOVE 1 TO WS-TOTAL")

    def test_tabs_are_expanded_to_eight_columns(self):
        prog = self.parse_cards(["\tIDENTIFICATION DIVISION.", "\tPROGRAM-ID. TABBED.",
                                 "\tPROCEDURE DIVISION.", "\tMAIN-PARA.", "\t    GOBACK."], head=[])
        self.assertEqual(prog.fmt, "fixed")
        self.assertEqual(prog.program_id, "TABBED")
        self.assertEqual(verbs(prog), ["GOBACK"])

    def test_lowercase_source_gives_uppercase_names_and_verbs(self):
        prog = self.parse_cards([card("identification division."), card("program-id. lower."),
                                 card("procedure division."), card("main-para."),
                                 card("    perform other-para."), card("    goback."),
                                 card("other-para."), card("    exit.")], head=[])
        self.assertEqual(prog.program_id, "LOWER")
        self.assertEqual(names(prog.paragraphs), ["MAIN-PARA", "OTHER-PARA"])
        self.assertEqual(verbs(prog), ["PERFORM", "GOBACK", "EXIT"])

    def test_tokens_carry_their_line_and_column(self):
        prog = self.parse_cards([card("    MOVE 1 TO WS-TOTAL.")])
        move = prog.tokens[statement(prog, "MOVE").start]
        self.assertEqual((move.line, move.col, move.end_col), (9, 12, 15))

    def test_physical_lines_keep_their_number_and_kind(self):
        prog = self.parse_cards([card(" a note", indicator="*"), "",
                                 card('    MOVE "ab'), card('    "cd" TO WS-MSG.', indicator="-")])
        self.assertEqual([(ln.no, ln.kind) for ln in prog.lines[8:]],
                         [(9, "comment"), (10, "blank"), (11, "code"), (12, "cont")])


class ClassifyTest(unittest.TestCase):
    """classify(): what each physical line is."""

    def test_code_area_is_columns_8_to_72(self):
        raw = "000100" + " " + "X" * 65 + "IGNORED!"
        self.assertEqual(cobparse.classify(raw, "fixed"), ("code", "X" * 65, 8))

    def test_line_shorter_than_the_indicator_is_blank(self):
        self.assertEqual(cobparse.classify("00010", "fixed")[0], "blank")

    def test_line_with_only_a_sequence_number_is_blank(self):
        self.assertEqual(cobparse.classify("000100   ", "fixed")[0], "blank")

    def test_compiler_directive_is_not_code(self):
        self.assertEqual(cobparse.classify("       >>SOURCE FORMAT IS FIXED", "fixed")[0], "directive")

    def test_free_format_comment(self):
        self.assertEqual(cobparse.classify("   *> a note", "free")[0], "comment")

    def test_free_format_code_keeps_the_whole_line(self):
        raw = "MOVE 1 TO WS-A" + " " * 70 + "MOVE 2 TO WS-B."
        self.assertEqual(cobparse.classify(raw, "free"), ("code", raw, 1))


class FormatDetectionTest(TempDirTestCase):
    def test_source_format_free_directive(self):
        self.assertEqual(cobparse.detect_format([">>SOURCE FORMAT IS FREE", "IDENTIFICATION DIVISION."]), "free")

    def test_source_format_fixed_directive_wins_over_the_layout(self):
        self.assertEqual(cobparse.detect_format(["       >>SOURCE FORMAT IS FIXED", "IDENTIFICATION DIVISION."]),
                         "fixed")

    def test_identification_division_in_area_a_means_fixed(self):
        self.assertEqual(cobparse.detect_format(["000100 IDENTIFICATION DIVISION."]), "fixed")

    def test_identification_division_at_the_margin_means_free(self):
        self.assertEqual(cobparse.detect_format(["*> header", "identification division."]), "free")

    def test_source_without_clues_is_fixed(self):
        self.assertEqual(cobparse.detect_format(["       01  WS-A PIC X."]), "fixed")

    def test_free_format_program_is_parsed(self):
        path = self.write("FREE.cbl", "\n".join([
            ">>SOURCE FORMAT IS FREE",
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. FREEFMT.",
            "*> a comment line",
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01 WS-A PIC 9(3). *> trailing comment",
            "PROCEDURE DIVISION.",
            "MAIN-PARA.",
            "    MOVE 1 TO WS-A *> MOVE 2 TO WS-A",
            '    DISPLAY "a line that runs past column seventy-two of the source file" WS-A',
            "    GOBACK."]) + "\n")
        prog = Program(path)
        self.assertEqual(prog.fmt, "free")
        self.assertEqual(prog.program_id, "FREEFMT")
        self.assertEqual(verbs(prog), ["MOVE", "DISPLAY", "GOBACK"])
        self.assertEqual(text_of(prog, statement(prog, "DISPLAY")),
                         'DISPLAY "a line that runs past column seventy-two of the source file" WS-A')


INVENTORY = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. INVENTRY.
    ENVIRONMENT DIVISION.
    CONFIGURATION SECTION.
    INPUT-OUTPUT SECTION.
    FILE-CONTROL.
        SELECT STOCK-FILE ASSIGN TO "stock.dat"
            ORGANIZATION IS INDEXED
            RECORD KEY IS STOCK-KEY
            FILE STATUS IS WS-STOCK-FS.
        SELECT OPTIONAL REPORT-FILE ASSIGN TO "report.txt"
            FILE STATUS WS-REPORT-FS.
        SELECT AUDIT-FILE ASSIGN TO "audit.dat".
    DATA DIVISION.
    FILE SECTION.
    FD  STOCK-FILE.
    01  STOCK-REC.
        05  STOCK-KEY             PIC X(4).
        05  FILLER                PIC X(16).
    01  STOCK-ALT-REC             PIC X(20).
    FD  REPORT-FILE.
    01  REPORT-REC                PIC X(80).
    FD  AUDIT-FILE.
    01  AUDIT-REC                 PIC X(40).
    WORKING-STORAGE SECTION.
    01  WS-STOCK-FS               PIC XX.
    01  WS-REPORT-FS              PIC XX.
    77  WS-COUNT                  PIC 9(3) VALUE ZERO.
    01  WS-FLAG                   PIC X.
        88  WS-DONE               VALUE "Y".
    01  WS-LINE                   PIC X(80).
    01  FILLER                    PIC X.
    01                            PIC X.
    LINKAGE SECTION.
    01  LN-KEY                    PIC X(4).
    01  LN-QTY                    PIC 9(4).
    PROCEDURE DIVISION USING LN-KEY BY REFERENCE LN-QTY.
    MAIN-LOGIC SECTION.
    0000-START.
        OPEN I-O STOCK-FILE OUTPUT REPORT-FILE AUDIT-FILE.
        PERFORM 1000-READ.
        CLOSE STOCK-FILE REPORT-FILE.
        GOBACK.
    FILE-WORK SECTION.
        MOVE ZERO TO WS-COUNT.
    1000-READ.
        READ STOCK-FILE INTO WS-LINE
            INVALID KEY SET WS-DONE TO TRUE
            NOT INVALID KEY ADD 1 TO WS-COUNT
        END-READ.
        WRITE REPORT-REC FROM WS-LINE AFTER ADVANCING 1 LINE.
        REWRITE STOCK-REC.
        START STOCK-FILE KEY IS >= STOCK-KEY.
        DELETE STOCK-FILE RECORD.
        WRITE WS-LINE.
    1000-EXIT.
        EXIT.
    END PROGRAM INVENTRY.
"""


class ProgramStructureTest(TempDirTestCase):
    """Divisions, sections, data items, files and the PROCEDURE DIVISION header."""

    def setUp(self):
        super().setUp()
        self.prog, self.src = self.parse(INVENTORY)

    def line(self, fragment):
        return line_of(self.src, fragment)

    def test_program_id(self):
        self.assertEqual(self.prog.program_id, "INVENTRY")

    def test_divisions_with_the_line_of_their_header(self):
        found = {name: self.prog.tokens[i].line for name, i in self.prog.divisions.items()}
        self.assertEqual(found, {"IDENTIFICATION": 1,
                                 "ENVIRONMENT": self.line("ENVIRONMENT DIVISION"),
                                 "DATA": self.line("DATA DIVISION"),
                                 "PROCEDURE": self.line("PROCEDURE DIVISION")})

    def test_sections_of_the_environment_and_data_divisions(self):
        self.assertEqual(list(self.prog.sections),
                         [("ENVIRONMENT", "CONFIGURATION"), ("ENVIRONMENT", "INPUT-OUTPUT"),
                          ("DATA", "FILE"), ("DATA", "WORKING-STORAGE"), ("DATA", "LINKAGE")])

    def test_data_items_have_level_name_and_section(self):
        items = {d.name: (d.level, d.section) for d in self.prog.data_items if d.name}
        self.assertEqual(items["WS-COUNT"], (77, "WORKING-STORAGE"))
        self.assertEqual(items["WS-DONE"], (88, "WORKING-STORAGE"))
        self.assertEqual(items["STOCK-KEY"], (5, "FILE"))
        self.assertEqual(items["LN-QTY"], (1, "LINKAGE"))

    def test_data_item_knows_its_line(self):
        item = next(d for d in self.prog.data_items if d.name == "WS-COUNT")
        self.assertEqual(item.line, self.line("77  WS-COUNT"))

    def test_item_without_a_name_is_kept_with_no_name(self):
        unnamed = [d for d in self.prog.data_items if d.name is None]
        self.assertEqual([(d.level, d.section) for d in unnamed], [(1, "WORKING-STORAGE")])

    def test_select_records_the_file_status_field(self):
        self.assertEqual(self.prog.files["STOCK-FILE"]["status"], "WS-STOCK-FS")

    def test_file_status_without_is(self):
        self.assertEqual(self.prog.files["REPORT-FILE"]["status"], "WS-REPORT-FS")

    def test_select_without_file_status(self):
        self.assertIsNone(self.prog.files["AUDIT-FILE"]["status"])

    def test_select_records_the_organization(self):
        self.assertEqual(self.prog.files["STOCK-FILE"]["org"], "INDEXED")

    def test_select_optional_is_named_after_the_file(self):
        self.assertIn("REPORT-FILE", self.prog.files)
        self.assertNotIn("OPTIONAL", self.prog.files)

    def test_fd_collects_its_level_01_records(self):
        self.assertEqual(self.prog.files["STOCK-FILE"]["records"], ["STOCK-REC", "STOCK-ALT-REC"])
        self.assertEqual(self.prog.files["REPORT-FILE"]["records"], ["REPORT-REC"])

    def test_file_of_record_is_case_insensitive(self):
        self.assertEqual(self.prog.file_of_record("stock-alt-rec"), "STOCK-FILE")

    def test_file_of_record_of_a_working_storage_item_is_none(self):
        self.assertIsNone(self.prog.file_of_record("WS-LINE"))

    def test_procedure_using_lists_only_the_parameters(self):
        using = [self.prog.tokens[i].text for i in self.prog.procedure_using]
        self.assertEqual(using, ["LN-KEY", "LN-QTY"])

    def test_end_program_is_recorded(self):
        self.assertEqual([name for name, _, _ in self.prog.end_programs], ["INVENTRY"])
        self.assertFalse(self.prog.nested)

    def test_end_program_is_not_a_paragraph_or_statement(self):
        self.assertNotIn("END", names(self.prog.paragraphs))
        last = max(self.prog.statements, key=lambda st: st.end)
        self.assertEqual(text_of(self.prog, last), "EXIT")


class ProcedureHeaderTest(TempDirTestCase):
    def test_procedure_division_without_using(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """)
        self.assertEqual(prog.procedure_using, [])

    def test_using_by_value_and_by_content_list_only_the_parameters(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """, using="BY VALUE WS-A BY CONTENT WS-B")
        self.assertEqual([prog.tokens[i].text for i in prog.procedure_using], ["WS-A", "WS-B"])

    def test_program_without_procedure_division(self):
        prog, _ = self.parse("""
            IDENTIFICATION DIVISION.
            PROGRAM-ID. DATAONLY.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A                      PIC 9.
        """)
        self.assertIsNone(prog.procedure_tok)
        self.assertEqual(prog.paragraphs, [])
        self.assertEqual(prog.statements, [])
        self.assertEqual([d.name for d in prog.data_items], ["WS-A"])

    def test_empty_source(self):
        prog = Program(self.write("EMPTY.cbl", ""))
        self.assertIsNone(prog.program_id)
        self.assertEqual(prog.tokens, [])

    def test_second_program_in_the_file_marks_it_as_nested(self):
        prog, _ = self.parse("""
            IDENTIFICATION DIVISION.
            PROGRAM-ID. FIRST.
            PROCEDURE DIVISION.
            FIRST-PARA.
                GOBACK.
            END PROGRAM FIRST.
            IDENTIFICATION DIVISION.
            PROGRAM-ID. SECOND.
            PROCEDURE DIVISION.
            SECOND-PARA.
                STOP RUN.
            END PROGRAM SECOND.
        """)
        self.assertTrue(prog.nested)
        self.assertEqual(prog.program_id, "FIRST")

    def test_body_of_the_first_program_stops_at_its_end_program(self):
        prog, _ = self.parse("""
            IDENTIFICATION DIVISION.
            PROGRAM-ID. FIRST.
            PROCEDURE DIVISION.
            FIRST-PARA.
                GOBACK.
            END PROGRAM FIRST.
            IDENTIFICATION DIVISION.
            PROGRAM-ID. SECOND.
            PROCEDURE DIVISION.
            SECOND-PARA.
                STOP RUN.
            END PROGRAM SECOND.
        """)
        self.assertEqual(names(prog.paragraphs), ["FIRST-PARA"])
        self.assertEqual(verbs(prog), ["GOBACK"])

    def test_declaratives_are_kept_out_of_the_body(self):
        prog, src = self.parse("""
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
        self.assertEqual(names(prog.paragraphs), ["MAIN-PARA"])
        self.assertEqual(verbs(prog), ["GOBACK"])
        first, end = prog.declaratives
        self.assertEqual(prog.tokens[first].line, line_of(src, "       DECLARATIVES."))
        self.assertEqual(end, prog.body_begin)
        self.assertEqual(prog.tokens[prog.body_begin].text, "MAIN-PARA")


class ParagraphTest(TempDirTestCase):
    def test_paragraph_runs_from_its_header_to_its_last_statement(self):
        prog, src = self.parse_body("""
            FIRST-PARA.
                MOVE 1 TO WS-A.
                MOVE 2 TO WS-B.
            * a note between the paragraphs

            SECOND-PARA.
                GOBACK.
        """)
        first = prog.paragraph("FIRST-PARA")
        self.assertEqual((first.line, first.end_line),
                         (line_of(src, "FIRST-PARA."), line_of(src, "MOVE 2 TO WS-B")))

    def test_last_paragraph_ends_with_the_program(self):
        prog, src = self.parse_body("""
            FIRST-PARA.
                MOVE 1 TO WS-A.
            SECOND-PARA.
                MOVE 2 TO WS-B.
                GOBACK.
        """)
        second = prog.paragraph("SECOND-PARA")
        self.assertEqual((second.line, second.end_line),
                         (line_of(src, "SECOND-PARA."), line_of(src, "GOBACK.")))

    def test_paragraph_lookup_ignores_case(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """)
        self.assertIs(prog.paragraph("main-para"), prog.paragraphs[0])

    def test_paragraph_lookup_of_an_unknown_name_is_none(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """)
        self.assertIsNone(prog.paragraph("NO-SUCH-PARA"))

    def test_paragraph_names_can_start_with_digits_or_be_numeric(self):
        prog, _ = self.parse_body("""
            1000-START.
                PERFORM 2000.
                GOBACK.
            2000.
                MOVE 1 TO WS-A.
        """)
        self.assertEqual(names(prog.paragraphs), ["1000-START", "2000"])

    def test_statements_fall_inside_the_token_range_of_their_paragraph(self):
        prog, _ = self.parse_body("""
            FIRST-PARA.
                MOVE 1 TO WS-A.
            SECOND-PARA.
                MOVE 2 TO WS-B.
                GOBACK.
        """)
        second = prog.paragraph("SECOND-PARA")
        inside = prog.statements_in(second.body_start, second.body_end)
        self.assertEqual([text_of(prog, st) for st in inside], ["MOVE 2 TO WS-B", "GOBACK"])

    def test_program_without_sections(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """)
        self.assertFalse(prog.has_sections)
        self.assertIsNone(prog.paragraphs[0].section)

    def test_sections_are_listed_with_their_paragraphs_and_flagged(self):
        prog, _ = self.parse(INVENTORY)
        self.assertTrue(prog.has_sections)
        self.assertEqual([(p.name, bool(p.is_section)) for p in prog.paragraphs],
                         [("MAIN-LOGIC", True), ("0000-START", False), ("FILE-WORK", True),
                          ("1000-READ", False), ("1000-EXIT", False)])

    def test_paragraph_knows_its_section(self):
        prog, _ = self.parse(INVENTORY)
        self.assertEqual(prog.paragraph("0000-START").section, "MAIN-LOGIC")
        self.assertEqual(prog.paragraph("1000-EXIT").section, "FILE-WORK")

    def test_statements_right_after_a_section_header_belong_to_the_section(self):
        prog, src = self.parse(INVENTORY)
        section = prog.paragraph("FILE-WORK")
        inside = prog.statements_in(section.body_start, section.body_end)
        self.assertEqual([text_of(prog, st) for st in inside], ["MOVE ZERO TO WS-COUNT"])
        self.assertEqual((section.line, section.end_line),
                         (line_of(src, "FILE-WORK SECTION."), line_of(src, "MOVE ZERO TO WS-COUNT")))

    def test_statements_before_the_first_paragraph_are_parsed(self):
        prog, _ = self.parse_body("""
                MOVE 1 TO WS-A.
            LATER-PARA.
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["MOVE", "GOBACK"])
        self.assertEqual(names(prog.paragraphs), ["LATER-PARA"])


class StatementTest(TempDirTestCase):
    """Extent of each statement: closed by a period or by END-xxx."""

    def test_each_statement_of_a_sentence_is_recorded(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A
                ADD 1 TO WS-B
                GOBACK.
        """)
        self.assertEqual([text_of(prog, st) for st in prog.statements],
                         ["MOVE 1 TO WS-A", "ADD 1 TO WS-B", "GOBACK"])

    def test_statement_spans_the_lines_it_is_written_on(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                COMPUTE WS-A =
                    WS-B * 2
                    + WS-C.
                GOBACK.
        """)
        compute = statement(prog, "COMPUTE")
        self.assertEqual((compute.line, compute.end_line),
                         (line_of(src, "COMPUTE WS-A"), line_of(src, "+ WS-C.")))

    def test_period_is_not_part_of_the_statement(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
        """)
        move = statement(prog, "MOVE")
        self.assertEqual(prog.tokens[move.end - 1].text, "WS-A")
        self.assertEqual(prog.tokens[move.end].text, ".")

    def test_two_word_statements_keep_their_second_word(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GO TO LAST-PARA.
            LAST-PARA.
                EXIT PROGRAM.
                STOP RUN.
        """)
        self.assertEqual([text_of(prog, st) for st in prog.statements],
                         ["GO TO LAST-PARA", "EXIT PROGRAM", "STOP RUN"])

    def test_if_closed_by_a_period_is_not_terminated(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                ELSE
                    MOVE 2 TO WS-B.
                MOVE 9 TO WS-C.
        """)
        st = statement(prog, "IF")
        self.assertFalse(st.terminated)
        self.assertTrue(st.needs_terminator())
        self.assertEqual((st.line, st.end_line), (line_of(src, "IF WS-A = 1"), line_of(src, "MOVE 2 TO WS-B.")))

    def test_if_closed_by_end_if_is_terminated(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                END-IF
                MOVE 9 TO WS-C.
        """)
        st = statement(prog, "IF")
        self.assertTrue(st.terminated)
        self.assertFalse(st.needs_terminator())
        self.assertEqual(prog.tokens[st.end - 1].text, "END-IF")
        self.assertEqual(st.end_line, line_of(src, "END-IF"))

    def test_statement_after_end_if_is_outside_the_if(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1
                    MOVE 1 TO WS-B
                END-IF
                MOVE 9 TO WS-C.
        """)
        inner = prog.statements_in(statement(prog, "IF").start + 1, statement(prog, "IF").end)
        self.assertEqual([text_of(prog, st) for st in inner], ["MOVE 1 TO WS-B"])

    def test_period_closes_every_open_if(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1
                    IF WS-B = 2
                        MOVE 3 TO WS-C.
                MOVE 9 TO WS-C.
        """)
        outer, inner = statement(prog, "IF", 0), statement(prog, "IF", 1)
        last = line_of(src, "MOVE 3 TO WS-C.")
        self.assertEqual((outer.end_line, inner.end_line), (last, last))
        self.assertEqual(statement(prog, "MOVE", 1).depth, 0)

    def test_else_belongs_to_the_nearest_open_if(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1
                    IF WS-B = 2
                        MOVE 1 TO WS-C
                    ELSE
                        MOVE 2 TO WS-C
                    END-IF
                    MOVE 3 TO WS-C
                END-IF.
        """)
        inner = statement(prog, "IF", 1)
        self.assertEqual(text_of(prog, inner),
                         "IF WS-B = 2 MOVE 1 TO WS-C ELSE MOVE 2 TO WS-C END-IF")

    def test_else_if_chain_closed_by_one_period(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1 MOVE 1 TO WS-B
                ELSE IF WS-A = 2 MOVE 2 TO WS-B
                ELSE MOVE 3 TO WS-B.
                GOBACK.
        """)
        outer, inner = statement(prog, "IF", 0), statement(prog, "IF", 1)
        self.assertEqual(text_of(prog, inner), "IF WS-A = 2 MOVE 2 TO WS-B ELSE MOVE 3 TO WS-B")
        self.assertEqual(outer.end, inner.end)
        self.assertEqual(statement(prog, "GOBACK").depth, 0)

    def test_nesting_depth_of_statements(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1
                    IF WS-B = 2
                        MOVE 3 TO WS-C
                    END-IF
                END-IF
                GOBACK.
        """)
        self.assertEqual([(st.verb, st.depth) for st in prog.statements],
                         [("IF", 0), ("IF", 1), ("MOVE", 2), ("GOBACK", 0)])

    def test_next_sentence_is_part_of_the_if_and_not_a_statement(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                IF WS-A = 1 NEXT SENTENCE ELSE MOVE 2 TO WS-B.
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["IF", "MOVE", "GOBACK"])
        self.assertEqual(text_of(prog, statement(prog, "IF")),
                         "IF WS-A = 1 NEXT SENTENCE ELSE MOVE 2 TO WS-B")

    def test_evaluate_contains_the_statements_of_its_whens(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                EVALUATE WS-A
                    WHEN 1
                        MOVE 1 TO WS-B
                    WHEN 2 THRU 5
                        MOVE 2 TO WS-B
                        ADD 1 TO WS-C
                    WHEN OTHER
                        CONTINUE
                END-EVALUATE
                GOBACK.
        """)
        ev = statement(prog, "EVALUATE")
        self.assertTrue(ev.terminated)
        self.assertEqual((ev.line, ev.end_line), (line_of(src, "EVALUATE WS-A"), line_of(src, "END-EVALUATE")))
        inner = prog.statements_in(ev.start + 1, ev.end)
        self.assertEqual([st.verb for st in inner], ["MOVE", "MOVE", "ADD", "CONTINUE"])

    def test_evaluate_closed_by_a_period_needs_its_terminator(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                EVALUATE TRUE
                    WHEN WS-A = 1 MOVE 1 TO WS-B
                    WHEN OTHER MOVE 2 TO WS-B.
                GOBACK.
        """)
        ev = statement(prog, "EVALUATE")
        self.assertFalse(ev.terminated)
        self.assertTrue(ev.needs_terminator())
        self.assertEqual(ev.terminator(), "END-EVALUATE")

    def test_evaluate_nested_in_evaluate_and_if(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                EVALUATE TRUE
                    WHEN WS-A = 1
                        EVALUATE WS-B
                            WHEN 1 MOVE 1 TO WS-C
                            WHEN OTHER CONTINUE
                        END-EVALUATE
                    WHEN OTHER
                        IF WS-B = 2 MOVE 3 TO WS-C END-IF
                END-EVALUATE.
        """)
        self.assertEqual([(st.verb, st.depth) for st in prog.statements],
                         [("EVALUATE", 0), ("EVALUATE", 1), ("MOVE", 2), ("CONTINUE", 2),
                          ("IF", 1), ("MOVE", 2)])
        self.assertEqual(text_of(prog, statement(prog, "EVALUATE", 1)),
                         "EVALUATE WS-B WHEN 1 MOVE 1 TO WS-C WHEN OTHER CONTINUE END-EVALUATE")

    def test_search_with_at_end_and_when(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                SEARCH WS-ENTRY
                    AT END MOVE 0 TO WS-A
                    WHEN WS-ENTRY(WS-IX) = 1
                        MOVE 1 TO WS-A
                END-SEARCH.
        """, data="""
            01  WS-A                      PIC 9.
            01  WS-TABLE.
                05  WS-ENTRY              PIC 9 OCCURS 5 INDEXED BY WS-IX.
        """)
        search = statement(prog, "SEARCH")
        self.assertTrue(search.terminated)
        self.assertEqual([p[0] for p in search.phrases], ["AT END"])
        self.assertEqual([st.verb for st in prog.statements_in(search.start + 1, search.end)], ["MOVE", "MOVE"])

    def test_inline_perform_contains_its_body(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3
                    ADD 1 TO WS-B
                    PERFORM OTHER-PARA
                END-PERFORM
                GOBACK.
            OTHER-PARA.
                EXIT.
        """)
        loop = statement(prog, "PERFORM", 0)
        self.assertTrue(loop.terminated)
        self.assertEqual((loop.line, loop.end_line), (line_of(src, "PERFORM VARYING"), line_of(src, "END-PERFORM")))
        self.assertEqual([text_of(prog, st) for st in prog.statements_in(loop.start + 1, loop.end)],
                         ["ADD 1 TO WS-B", "PERFORM OTHER-PARA"])

    def test_inline_perform_forms(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                PERFORM UNTIL WS-A > 3
                    ADD 1 TO WS-A
                END-PERFORM
                PERFORM 3 TIMES
                    ADD 1 TO WS-B
                END-PERFORM
                PERFORM WITH TEST AFTER UNTIL WS-C > 3
                    ADD 1 TO WS-C
                END-PERFORM
                GOBACK.
        """)
        loops = [st for st in prog.statements if st.verb == "PERFORM"]
        self.assertEqual(len(loops), 3)
        for loop in loops:
            self.assertEqual([st.verb for st in prog.statements_in(loop.start + 1, loop.end)], ["ADD"])

    def test_out_of_line_perform_is_a_single_statement(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                PERFORM OTHER-PARA
                PERFORM OTHER-PARA THRU LAST-PARA
                PERFORM OTHER-PARA 3 TIMES
                PERFORM OTHER-PARA UNTIL WS-A > 5
                PERFORM OTHER-PARA VARYING WS-B FROM 1 BY 1 UNTIL WS-B > 2
                GOBACK.
            OTHER-PARA.
                ADD 1 TO WS-A.
            LAST-PARA.
                EXIT.
        """)
        performs = [text_of(prog, st) for st in prog.statements if st.verb == "PERFORM"]
        self.assertEqual(performs, ["PERFORM OTHER-PARA",
                                    "PERFORM OTHER-PARA THRU LAST-PARA",
                                    "PERFORM OTHER-PARA 3 TIMES",
                                    "PERFORM OTHER-PARA UNTIL WS-A > 5",
                                    "PERFORM OTHER-PARA VARYING WS-B FROM 1 BY 1 UNTIL WS-B > 2"])

    def test_only_an_inline_perform_without_end_perform_needs_a_terminator(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                PERFORM OTHER-PARA.
                PERFORM UNTIL WS-A > 3 ADD 1 TO WS-A.
                GOBACK.
            OTHER-PARA.
                EXIT.
        """)
        out_of_line, inline = statement(prog, "PERFORM", 0), statement(prog, "PERFORM", 1)
        self.assertFalse(out_of_line.needs_terminator())
        self.assertTrue(inline.needs_terminator())
        self.assertEqual(inline.terminator(), "END-PERFORM")

    def test_exit_perform_is_one_statement(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                PERFORM UNTIL WS-A > 3
                    IF WS-B = 2
                        EXIT PERFORM
                    END-IF
                    ADD 1 TO WS-A
                END-PERFORM
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["PERFORM", "IF", "EXIT", "ADD", "GOBACK"])
        self.assertEqual(text_of(prog, statement(prog, "EXIT")), "EXIT PERFORM")

    def test_simple_statement_does_not_need_a_terminator(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
        """)
        self.assertFalse(statement(prog, "MOVE").needs_terminator())


READER = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. READER.
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
    01  WS-PGM                    PIC X(8).
    01  WS-TEXT                   PIC X(20).
    01  WS-FLAG                   PIC X.
        88  WS-DONE               VALUE "Y".
    PROCEDURE DIVISION.
    MAIN-PARA.
"""


class ConditionalPhraseTest(TempDirTestCase):
    """AT END, INVALID KEY, ON SIZE ERROR, ON EXCEPTION, ON OVERFLOW."""

    def parse_reader(self, statements):
        return self.parse(support.blocks(READER, statements))

    def phrases(self, st):
        return [p[0] for p in st.phrases]

    def test_read_with_at_end_and_not_at_end(self):
        prog, src = self.parse_reader("""
                READ IN-FILE
                    AT END SET WS-DONE TO TRUE
                    NOT AT END ADD 1 TO WS-A
                END-READ
                GOBACK.
        """)
        read = statement(prog, "READ")
        self.assertEqual(self.phrases(read), ["AT END", "NOT AT END"])
        self.assertTrue(read.terminated)
        self.assertEqual((read.line, read.end_line), (line_of(src, "READ IN-FILE"), line_of(src, "END-READ")))

    def test_statements_of_a_phrase_are_nested_in_the_statement(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE
                    AT END SET WS-DONE TO TRUE
                    NOT AT END ADD 1 TO WS-A
                END-READ
                GOBACK.
        """)
        self.assertEqual([(st.verb, st.depth) for st in prog.statements],
                         [("READ", 0), ("SET", 1), ("ADD", 1), ("GOBACK", 0)])

    def test_phrase_body_is_the_token_range_after_the_phrase_words(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE
                    AT END SET WS-DONE TO TRUE
                    NOT AT END ADD 1 TO WS-A
                END-READ.
        """)
        read = statement(prog, "READ")
        bodies = [" ".join(t.text for t in prog.tokens[b0:b1]) for _, _, b0, b1 in read.phrases]
        self.assertEqual(bodies, ["SET WS-DONE TO TRUE", "ADD 1 TO WS-A"])

    def test_main_part_of_the_statement_ends_at_its_first_phrase(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE INTO WS-TEXT
                    AT END SET WS-DONE TO TRUE
                END-READ.
        """)
        read = statement(prog, "READ")
        self.assertEqual(" ".join(t.text for t in prog.tokens[read.start:read.main_end]),
                         "READ IN-FILE INTO WS-TEXT")

    def test_phrase_closed_by_a_period_needs_the_terminator(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE AT END MOVE 1 TO WS-A.
                GOBACK.
        """)
        read = statement(prog, "READ")
        self.assertFalse(read.terminated)
        self.assertTrue(read.needs_terminator())
        self.assertEqual(read.terminator(), "END-READ")
        self.assertEqual(statement(prog, "GOBACK").depth, 0)

    def test_statement_without_phrases_closed_by_a_period_needs_nothing(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE.
        """)
        self.assertFalse(statement(prog, "READ").needs_terminator())

    def test_invalid_key_with_and_without_the_word_key(self):
        prog, _ = self.parse_reader("""
                WRITE IN-REC INVALID KEY MOVE 1 TO WS-A END-WRITE
                REWRITE IN-REC INVALID MOVE 2 TO WS-A END-REWRITE
                DELETE IN-FILE NOT INVALID KEY MOVE 3 TO WS-A END-DELETE.
        """)
        self.assertEqual(self.phrases(statement(prog, "WRITE")), ["INVALID KEY"])
        self.assertEqual(self.phrases(statement(prog, "REWRITE")), ["INVALID KEY"])
        self.assertEqual(self.phrases(statement(prog, "DELETE")), ["NOT INVALID KEY"])

    def test_on_size_error_of_arithmetic_statements(self):
        prog, _ = self.parse_reader("""
                ADD 1 TO WS-A ON SIZE ERROR MOVE 0 TO WS-A.
                COMPUTE WS-A = WS-A * 2
                    SIZE ERROR MOVE 0 TO WS-A
                    NOT ON SIZE ERROR MOVE 1 TO WS-B
                END-COMPUTE.
        """)
        self.assertEqual(self.phrases(statement(prog, "ADD")), ["ON SIZE ERROR"])
        self.assertEqual(self.phrases(statement(prog, "COMPUTE")), ["ON SIZE ERROR", "NOT ON SIZE ERROR"])

    def test_call_on_exception_and_not_on_exception(self):
        prog, _ = self.parse_reader("""
                CALL WS-PGM USING WS-A
                    ON EXCEPTION MOVE 9 TO WS-B
                    NOT ON EXCEPTION ADD 1 TO WS-B
                END-CALL.
        """)
        self.assertEqual(self.phrases(statement(prog, "CALL")), ["ON EXCEPTION", "NOT ON EXCEPTION"])

    def test_not_on_exception_after_a_display_belongs_to_the_call(self):
        # Documented choice: DISPLAY and ACCEPT are verbs without ON EXCEPTION.
        prog, _ = self.parse_reader("""
                CALL WS-PGM USING WS-A ON EXCEPTION
                    DISPLAY "not found" NOT ON EXCEPTION ADD 1 TO WS-B
                END-CALL.
        """)
        self.assertEqual(self.phrases(statement(prog, "CALL")), ["ON EXCEPTION", "NOT ON EXCEPTION"])
        self.assertEqual(text_of(prog, statement(prog, "DISPLAY")), 'DISPLAY "not found"')

    def test_string_on_overflow(self):
        prog, _ = self.parse_reader("""
                STRING WS-PGM DELIMITED BY SIZE INTO WS-TEXT
                    ON OVERFLOW MOVE 1 TO WS-A
                END-STRING.
        """)
        string = statement(prog, "STRING")
        self.assertEqual(self.phrases(string), ["ON OVERFLOW"])
        self.assertEqual(" ".join(t.text for t in prog.tokens[string.start:string.main_end]),
                         "STRING WS-PGM DELIMITED BY SIZE INTO WS-TEXT")

    def test_if_inside_a_phrase_ends_where_the_opposite_phrase_starts(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE
                    INVALID KEY MOVE 1 TO WS-A
                    NOT INVALID KEY IF WS-B = 1 MOVE 2 TO WS-A
                        ELSE MOVE 3 TO WS-A END-IF.
                GOBACK.
        """)
        read = statement(prog, "READ")
        self.assertEqual(self.phrases(read), ["INVALID KEY", "NOT INVALID KEY"])
        self.assertEqual(text_of(prog, statement(prog, "IF")),
                         "IF WS-B = 1 MOVE 2 TO WS-A ELSE MOVE 3 TO WS-A END-IF")

    def test_phrase_of_the_outer_statement_closes_an_inner_if(self):
        prog, _ = self.parse_reader("""
                READ IN-FILE
                    AT END IF WS-A = 1 MOVE 2 TO WS-B
                    NOT AT END MOVE 3 TO WS-B
                END-READ.
        """)
        self.assertEqual(text_of(prog, statement(prog, "IF")), "IF WS-A = 1 MOVE 2 TO WS-B")
        self.assertEqual(self.phrases(statement(prog, "READ")), ["AT END", "NOT AT END"])


class SiteTest(TempDirTestCase):
    """Statements the in-program mode can mock: files, CALL, SQL, clock."""

    def test_file_sites_of_the_program(self):
        prog, _ = self.parse(INVENTORY)
        found = [(op, file) for _, file, op, _ in prog.file_sites()]
        self.assertEqual(found, [("OPEN", None), ("CLOSE", None), ("READ", "STOCK-FILE"),
                                 ("WRITE", "REPORT-FILE"), ("REWRITE", "STOCK-FILE"),
                                 ("START", "STOCK-FILE"), ("DELETE", "STOCK-FILE")])

    def details(self, op):
        prog, _ = self.parse(INVENTORY)
        return next(d for _, _, o, d in prog.file_sites() if o == op)

    def test_open_lists_each_file_with_its_mode(self):
        self.assertEqual(self.details("OPEN")["items"],
                         [("I-O", "STOCK-FILE"), ("OUTPUT", "REPORT-FILE"), ("OUTPUT", "AUDIT-FILE")])

    def test_close_lists_its_files(self):
        self.assertEqual([f for _, f in self.details("CLOSE")["items"]], ["STOCK-FILE", "REPORT-FILE"])

    def test_read_into_names_the_target(self):
        self.assertEqual(self.details("READ"), {"into": "WS-LINE"})

    def test_write_is_matched_to_its_file_by_the_record(self):
        self.assertEqual(self.details("WRITE"), {"record": "REPORT-REC", "from": "WS-LINE"})

    def test_write_without_from(self):
        self.assertEqual(self.details("REWRITE"), {"record": "STOCK-REC", "from": None})

    def test_write_of_something_that_is_not_a_file_record_is_not_a_site(self):
        prog, _ = self.parse(INVENTORY)
        writes = [d["record"] for _, _, op, d in prog.file_sites() if op == "WRITE"]
        self.assertNotIn("WS-LINE", writes)

    def test_call_target_literal_and_identifier(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                CALL "RATES" USING WS-A
                CALL WS-PGM USING WS-A
                GOBACK.
        """, data="""
            01  WS-A                      PIC 9.
            01  WS-PGM                    PIC X(8).
        """)
        self.assertEqual([prog.call_target(st) for st in prog.statements if st.verb == "CALL"],
                         [('"RATES"', True), ("WS-PGM", False)])

    def test_exec_sql_is_one_statement_up_to_end_exec(self):
        prog, src = self.parse_body("""
            MAIN-PARA.
                EXEC SQL
                    DELETE FROM ORDERS
                    WHERE ORDER_ID = :WS-A
                END-EXEC
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["EXEC", "GOBACK"])
        sql = statement(prog, "EXEC")
        self.assertTrue(sql.terminated)
        self.assertEqual((sql.line, sql.end_line), (line_of(src, "EXEC SQL"), line_of(src, "END-EXEC")))

    def test_sql_sites_give_the_text_between_exec_sql_and_end_exec(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                EXEC SQL SELECT NAME FROM CUSTOMERS END-EXEC.
                EXEC CICS RETURN END-EXEC.
        """)
        self.assertEqual([text for _, text in prog.sql_sites()], ["SELECT NAME FROM CUSTOMERS"])

    def test_clock_sites(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                ACCEPT WS-DATE FROM DATE YYYYMMDD
                ACCEPT WS-TIME FROM TIME
                ACCEPT WS-DAY FROM DAY-OF-WEEK
                GOBACK.
        """, data="""
            01  WS-DATE                   PIC 9(8).
            01  WS-TIME                   PIC 9(8).
            01  WS-DAY                    PIC 9.
        """)
        self.assertEqual([(kind, target) for _, kind, target in prog.clock_sites()],
                         [("DATE YYYYMMDD", "WS-DATE"), ("TIME", "WS-TIME"), ("DAY-OF-WEEK", "WS-DAY")])

    def test_accept_from_the_terminal_is_not_a_clock_site(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                ACCEPT WS-A
                ACCEPT WS-B FROM CONSOLE
                GOBACK.
        """)
        self.assertEqual(prog.clock_sites(), [])


class TokenTest(TempDirTestCase):
    def kinds(self, prog, st):
        return [(t.kind, t.text) for t in prog.tokens[st.start:st.end]]

    def test_decimal_point_is_part_of_the_number(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                COMPUTE WS-A = WS-B * 12.5 + .25 - 3.
                GOBACK.
        """)
        compute = statement(prog, "COMPUTE")
        self.assertEqual([t.text for t in prog.tokens[compute.start:compute.end] if t.kind == "num"],
                         ["12.5", ".25", "3"])
        self.assertEqual(verbs(prog), ["COMPUTE", "GOBACK"])

    def test_signed_number_is_one_token(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                MOVE -5 TO WS-A.
        """)
        self.assertEqual(self.kinds(prog, statement(prog, "MOVE"))[1], ("num", "-5"))

    def test_minus_between_operands_is_an_operator(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                COMPUTE WS-A = WS-B - 5.
        """)
        self.assertEqual(self.kinds(prog, statement(prog, "COMPUTE"))[-2:], [("sep", "-"), ("num", "5")])

    def test_period_and_keywords_inside_a_literal_are_text(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                DISPLAY "END-IF. GOBACK. ELSE"
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["DISPLAY", "GOBACK"])
        self.assertEqual(self.kinds(prog, statement(prog, "DISPLAY"))[1], ("lit", '"END-IF. GOBACK. ELSE"'))

    def test_apostrophe_literal_can_hold_a_quote(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                DISPLAY 'say "hello"'.
        """)
        self.assertEqual(self.kinds(prog, statement(prog, "DISPLAY"))[1], ("lit", "'say \"hello\"'"))

    def test_doubled_quote_inside_a_literal_is_kept(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                DISPLAY 'it''s done'.
        """)
        self.assertEqual(self.kinds(prog, statement(prog, "DISPLAY"))[1], ("lit", "'it''s done'"))

    def test_literal_with_a_doubled_quote_is_one_token(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                DISPLAY 'it''s done' WS-A.
        """)
        self.assertEqual([t.kind for t in prog.tokens[statement(prog, "DISPLAY").start:statement(prog, "DISPLAY").end]],
                         ["word", "lit", "word"])

    def test_hexadecimal_literal_is_one_token(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                MOVE X"0A" TO WS-FLAG.
        """)
        self.assertEqual(self.kinds(prog, statement(prog, "MOVE"))[1], ("lit", 'X"0A"'))

    def test_commas_and_semicolons_are_separators_without_meaning(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A, WS-B; WS-C.
        """)
        self.assertEqual(text_of(prog, statement(prog, "MOVE")), "MOVE 1 TO WS-A WS-B WS-C")

    def test_picture_string_with_periods_and_commas_is_one_token(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """, data="""
            01  WS-EDITED                 PIC ZZ,ZZ9.99.
            01  WS-AFTER                  PIC X.
        """)
        self.assertIn(("pic", "ZZ,ZZ9.99"), [(t.kind, t.text) for t in prog.tokens])
        self.assertEqual([d.name for d in prog.data_items], ["WS-EDITED", "WS-AFTER"])

    def test_relational_operators_of_two_characters(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                IF WS-A >= 1 AND WS-B <= 2 MOVE 1 TO WS-C.
        """)
        ops = [t.text for t in prog.tokens[statement(prog, "IF").start:statement(prog, "IF").end]
               if t.kind == "sep"]
        self.assertEqual(ops, [">=", "<="])

    def test_value_literal_that_looks_like_code_does_not_create_items(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                GOBACK.
        """, data="""
            01  WS-NOTE     PIC X(30) VALUE "01 FAKE-ITEM PIC X.".
        """)
        self.assertEqual([d.name for d in prog.data_items], ["WS-NOTE"])


class CopyTest(TempDirTestCase):
    """COPY: finding the copybook, expanding it and remembering origins."""

    ITEMS = """
        * Synthetic copybook.
            05  :TAG:-CODE            PIC X(4).
            05  :TAG:-QTY             PIC 9(3).
    """

    def program_with(self, copy_line, more_data=""):
        return support.program_text("""
            MAIN-PARA.
                GOBACK.
        """, data="01  WS-ITEM.\n" + copy_line + "\n01  WS-LAST                   PIC X.\n" + more_data)

    def item_names(self, prog):
        return [d.name for d in prog.data_items]

    def test_copybook_next_to_the_source_is_expanded(self):
        self.write("ITEMS.cpy", fixed("""
            05  ITEM-CODE             PIC X(4).
            05  ITEM-QTY              PIC 9(3).
        """))
        prog, _ = self.parse(self.program_with("    COPY ITEMS."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "ITEM-CODE", "ITEM-QTY", "WS-LAST"])

    def test_copybook_is_searched_in_the_copy_dirs(self):
        self.write("copylib/ITEMS.cpy", fixed("""
            05  ITEM-CODE             PIC X(4).
        """))
        prog, _ = self.parse(self.program_with("    COPY ITEMS."), copy_dirs=[os.path.join(self.tmp, "copylib")])
        self.assertIn("ITEM-CODE", self.item_names(prog))

    def test_folder_of_the_source_is_searched_before_the_copy_dirs(self):
        self.write("ITEMS.cpy", fixed("""
            05  LOCAL-CODE            PIC X(4).
        """))
        self.write("copylib/ITEMS.cpy", fixed("""
            05  SHARED-CODE           PIC X(4).
        """))
        prog, _ = self.parse(self.program_with("    COPY ITEMS."), copy_dirs=[os.path.join(self.tmp, "copylib")])
        self.assertIn("LOCAL-CODE", self.item_names(prog))
        self.assertNotIn("SHARED-CODE", self.item_names(prog))

    def test_copybook_extensions(self):
        for ext in (".cpy", ".CPY", ".cob", ".cbl", ".copy", ""):
            with self.subTest(ext=ext):
                folder = "ext" + (ext.replace(".", "-") or "-none")
                self.write(os.path.join(folder, "ITEMS" + ext), fixed("""
                    05  ITEM-CODE             PIC X(4).
                """))
                path = self.write(os.path.join(folder, "PROG.cbl"), fixed(self.program_with("    COPY ITEMS.")))
                self.assertIn("ITEM-CODE", self.item_names(Program(path)))

    def test_copybook_file_in_lowercase_is_found(self):
        self.write("items.cpy", fixed("""
            05  ITEM-CODE             PIC X(4).
        """))
        prog, _ = self.parse(self.program_with("    COPY ITEMS."))
        self.assertIn("ITEM-CODE", self.item_names(prog))

    def test_quoted_copybook_name(self):
        self.write("ITEMS.cpy", fixed("""
            05  ITEM-CODE             PIC X(4).
        """))
        prog, _ = self.parse(self.program_with('    COPY "ITEMS.cpy".'))
        self.assertIn("ITEM-CODE", self.item_names(prog))

    def test_library_name_after_of_is_accepted(self):
        self.write("ITEMS.cpy", fixed("""
            05  ITEM-CODE             PIC X(4).
        """))
        prog, _ = self.parse(self.program_with("    COPY ITEMS OF SHARDLIB."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "ITEM-CODE", "WS-LAST"])

    def test_replacing_pseudo_text(self):
        self.write("ITEMS.cpy", fixed(self.ITEMS))
        prog, _ = self.parse(self.program_with("    COPY ITEMS REPLACING ==:TAG:== BY ==WS==."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "WS-CODE", "WS-QTY", "WS-LAST"])

    def test_same_copybook_twice_with_different_replacing(self):
        self.write("ITEMS.cpy", fixed(self.ITEMS))
        prog, _ = self.parse(self.program_with("    COPY ITEMS REPLACING ==:TAG:== BY ==OLD==.",
                                               "01  WS-NEW.\n    COPY ITEMS REPLACING ==:TAG:== BY ==NEW==.\n"))
        self.assertEqual(self.item_names(prog),
                         ["WS-ITEM", "OLD-CODE", "OLD-QTY", "WS-LAST", "WS-NEW", "NEW-CODE", "NEW-QTY"])

    def test_replacing_a_word_leaves_longer_words_alone(self):
        self.write("ITEMS.cpy", fixed("""
            05  OLD-NAME              PIC X(4).
            05  OLD-NAME-EXTRA        PIC X(4).
        """))
        prog, _ = self.parse(self.program_with("    COPY ITEMS REPLACING OLD-NAME BY NEW-NAME."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "NEW-NAME", "OLD-NAME-EXTRA", "WS-LAST"])

    def test_several_replacing_pairs(self):
        self.write("ITEMS.cpy", fixed("""
            05  :TAG:-CODE            PIC X(4).
            05  OLD-NAME              PIC X(4).
        """))
        prog, _ = self.parse(self.program_with(
            "    COPY ITEMS REPLACING ==:TAG:== BY ==WS==\n        OLD-NAME BY NEW-NAME."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "WS-CODE", "NEW-NAME", "WS-LAST"])

    def test_copy_statement_written_on_several_lines(self):
        self.write("ITEMS.cpy", fixed(self.ITEMS))
        prog, _ = self.parse(self.program_with("    COPY ITEMS\n        REPLACING ==:TAG:==\n        BY ==WS==."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "WS-CODE", "WS-QTY", "WS-LAST"])

    def test_text_before_copy_on_the_same_line_is_kept(self):
        self.write("ITEMS.cpy", fixed("""
            05  ITEM-CODE             PIC X(4).
        """))
        prog, _ = self.parse(support.program_text("""
            MAIN-PARA.
                GOBACK.
        """, data="01  WS-ITEM. COPY ITEMS.\n01  WS-LAST                   PIC X.\n"))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "ITEM-CODE", "WS-LAST"])

    def test_copybook_that_copies_another(self):
        self.write("OUTER.cpy", fixed("""
            05  OUTER-FIELD           PIC X.
            COPY INNER.
        """))
        self.write("INNER.cpy", fixed("""
            05  INNER-FIELD           PIC X.
        """))
        prog, _ = self.parse(self.program_with("    COPY OUTER."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "OUTER-FIELD", "INNER-FIELD", "WS-LAST"])

    def test_expanded_lines_remember_their_file_and_line(self):
        copybook = self.write("ITEMS.cpy", fixed(self.ITEMS))
        prog, src = self.parse(self.program_with("    COPY ITEMS REPLACING ==:TAG:== BY ==WS==."))
        qty = next(d for d in prog.data_items if d.name == "WS-QTY")
        self.assertEqual(prog.origin_of_line(qty.line), (copybook, 3))
        last = next(d for d in prog.data_items if d.name == "WS-LAST")
        self.assertEqual(prog.origin_of_line(last.line), (prog.path, line_of(src, "WS-LAST")))

    def test_expanded_lines_are_numbered_consecutively(self):
        self.write("ITEMS.cpy", fixed(self.ITEMS))
        prog, _ = self.parse(self.program_with("    COPY ITEMS REPLACING ==:TAG:== BY ==WS==."))
        self.assertEqual([ln.no for ln in prog.lines], list(range(1, len(prog.lines) + 1)))

    def test_copy_in_the_procedure_division(self):
        copybook = self.write("CHECKS.cpy", fixed("""
            IF WS-A = 9
                MOVE 9 TO WS-B
            END-IF.
        """))
        prog, src = self.parse_body("""
            MAIN-PARA.
                MOVE 1 TO WS-A.
                COPY CHECKS.
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["MOVE", "IF", "MOVE", "GOBACK"])
        self.assertEqual(prog.origin_of_line(statement(prog, "IF").line), (copybook, 1))
        self.assertEqual(prog.origin_of_line(statement(prog, "GOBACK").line), (prog.path, line_of(src, "GOBACK.")))

    def test_copy_in_a_comment_is_not_expanded(self):
        prog, _ = self.parse(self.program_with("*    COPY NOWHERE."))
        self.assertEqual(self.item_names(prog), ["WS-ITEM", "WS-LAST"])

    def test_missing_copybook_is_a_parse_error_that_names_it_and_the_reference(self):
        text = self.program_with("    COPY NOWHERE.")
        with self.assertRaises(ParseError) as caught:
            self.parse(text)
        message = str(caught.exception)
        self.assertIn("'NOWHERE'", message)
        self.assertIn(f"PROG.cbl:{line_of(fixed(text), 'COPY NOWHERE')}", message)

    def test_copy_without_a_name_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            self.parse(self.program_with("    COPY ."))

    def test_copybook_that_copies_itself_is_a_parse_error(self):
        self.write("LOOPING.cpy", fixed("""
            COPY LOOPING.
        """))
        with self.assertRaises(ParseError):
            self.parse(self.program_with("    COPY LOOPING."))

    def test_paragraph_whose_name_starts_with_copy_is_not_a_copy_statement(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                PERFORM COPY-RECORD.
                GOBACK.
            COPY-RECORD.
                MOVE 1 TO WS-A.
        """)
        self.assertEqual(names(prog.paragraphs), ["MAIN-PARA", "COPY-RECORD"])

    def test_the_word_copy_inside_a_literal_is_not_a_copy_statement(self):
        prog, _ = self.parse_body("""
            MAIN-PARA.
                DISPLAY "SAVED. COPY IT".
                GOBACK.
        """)
        self.assertEqual(verbs(prog), ["DISPLAY", "GOBACK"])


class VerbTableTest(unittest.TestCase):
    def test_common_verbs_are_known(self):
        for verb in ("MOVE", "IF", "EVALUATE", "PERFORM", "READ", "WRITE", "CALL", "COMPUTE",
                     "GO", "STOP", "GOBACK", "EXIT", "EXEC", "ACCEPT", "DISPLAY", "CONTINUE"):
            self.assertIn(verb, VERBS)

    def test_clause_words_are_not_verbs(self):
        for word in ("ELSE", "WHEN", "THEN", "END-IF", "TO", "USING", "NEXT", "UNTIL", "VARYING"):
            self.assertNotIn(word, VERBS)

    def test_every_scope_terminator_closes_a_known_verb(self):
        self.assertEqual({t for t in TERMINATORS if t[len("END-"):] not in VERBS}, set())


class DescribeTest(TempDirTestCase):
    """describe(): the data behind 'cobalto parse --json'."""

    def setUp(self):
        super().setUp()
        self.prog, self.src = self.parse(INVENTORY)
        self.data = describe(self.prog)

    def line(self, fragment):
        return line_of(self.src, fragment)

    def test_is_json_serializable(self):
        self.assertEqual(json.loads(json.dumps(self.data)), self.data)

    def test_header_fields(self):
        self.assertEqual(self.data["file"], self.prog.path)
        self.assertEqual(self.data["format"], "fixed")
        self.assertEqual(self.data["lines"], len(self.src.splitlines()))
        self.assertEqual(self.data["program_ids"], ["INVENTRY"])

    def test_divisions_in_source_order(self):
        self.assertEqual(self.data["divisions"],
                         [{"name": "IDENTIFICATION", "line": 1},
                          {"name": "ENVIRONMENT", "line": self.line("ENVIRONMENT DIVISION")},
                          {"name": "DATA", "line": self.line("DATA DIVISION")},
                          {"name": "PROCEDURE", "line": self.line("PROCEDURE DIVISION")}])

    def test_sections(self):
        self.assertIn({"division": "DATA", "name": "LINKAGE", "line": self.line("LINKAGE SECTION")},
                      self.data["sections"])

    def test_files_with_status_and_records(self):
        self.assertEqual(self.data["files"],
                         [{"name": "STOCK-FILE", "status": "WS-STOCK-FS", "records": ["STOCK-REC", "STOCK-ALT-REC"]},
                          {"name": "REPORT-FILE", "status": "WS-REPORT-FS", "records": ["REPORT-REC"]},
                          {"name": "AUDIT-FILE", "status": None, "records": ["AUDIT-REC"]}])

    def test_data_items(self):
        self.assertIn({"level": 88, "name": "WS-DONE", "section": "WORKING-STORAGE"}, self.data["data_items"])
        self.assertIn({"level": 1, "name": "LN-KEY", "section": "LINKAGE"}, self.data["data_items"])

    def test_procedure_using(self):
        self.assertEqual(self.data["procedure_using"], ["LN-KEY", "LN-QTY"])

    def test_paragraphs_with_line_range_and_section_flag(self):
        self.assertIn({"name": "0000-START", "section": False,
                       "line": self.line("0000-START."), "end_line": self.line("GOBACK.")},
                      self.data["paragraphs"])
        self.assertIn("FILE-WORK", [p["name"] for p in self.data["paragraphs"] if p["section"]])

    def test_statements_list_only_the_mockable_sites(self):
        self.assertEqual([s["verb"] for s in self.data["statements"]],
                         ["OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "START", "DELETE", "WRITE"])

    def test_statement_entry_has_lines_phrases_and_terminator_flag(self):
        read = next(s for s in self.data["statements"] if s["verb"] == "READ")
        self.assertEqual(read, {"verb": "READ", "line": self.line("READ STOCK-FILE"),
                                "end_line": self.line("END-READ"),
                                "phrases": ["INVALID KEY", "NOT INVALID KEY"], "terminated": True})

    def test_program_without_procedure_division(self):
        prog, _ = self.parse("""
            IDENTIFICATION DIVISION.
            PROGRAM-ID. DATAONLY.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A                      PIC 9.
        """, name="DATAONLY.cbl")
        data = describe(prog)
        self.assertEqual((data["procedure_using"], data["paragraphs"], data["statements"]), ([], [], []))


class SummaryTest(TempDirTestCase):
    """summary(): the readable output of 'cobalto parse FILE'."""

    def setUp(self):
        super().setUp()
        self.prog, self.src = self.parse(INVENTORY)
        self.text = summary(self.prog)

    def test_names_the_program(self):
        self.assertIn("PROGRAM-ID: INVENTRY", self.text.splitlines())

    def test_lists_files_with_status_and_records(self):
        self.assertIn("STOCK-FILE (status WS-STOCK-FS, rec STOCK-REC,STOCK-ALT-REC)", self.text)

    def test_lists_the_using_parameters(self):
        self.assertIn("PROCEDURE DIVISION USING: LN-KEY LN-QTY", self.text.splitlines())

    def test_lists_each_paragraph_with_its_lines(self):
        first, last = line_of(self.src, "0000-START."), line_of(self.src, "GOBACK.")
        rows = [ln.split() for ln in self.text.splitlines() if "0000-START" in ln]
        self.assertEqual(rows, [["paragraph", "0000-START", "lines", f"{first}-{last}"]])

    def test_tells_sections_from_paragraphs(self):
        rows = [ln.split()[0] for ln in self.text.splitlines() if "MAIN-LOGIC" in ln]
        self.assertEqual(rows, ["SECTION"])

    def test_lists_site_statements_with_their_phrases(self):
        row = next(ln for ln in self.text.splitlines() if ln.split()[:1] == ["READ"])
        self.assertIn("phrases: INVALID KEY NOT INVALID KEY", row)
        self.assertIn("[END-x]", row)


class ExampleProgramsTest(unittest.TestCase):
    """A few realistic checks on the programs of examples/src."""

    SOURCES = sorted(glob.glob(os.path.join(support.EXAMPLES, "src", "*.cbl")))

    def test_every_example_parses_and_is_named_after_its_file(self):
        self.assertTrue(self.SOURCES)
        for path in self.SOURCES:
            with self.subTest(source=os.path.basename(path)):
                prog = Program(path, [os.path.dirname(path)])
                self.assertEqual(prog.program_id, os.path.splitext(os.path.basename(path))[0])
                self.assertTrue(prog.paragraphs)
                self.assertFalse(prog.nested)

    def test_statements_of_every_example_are_properly_nested(self):
        for path in self.SOURCES:
            with self.subTest(source=os.path.basename(path)):
                prog = Program(path, [os.path.dirname(path)])
                stack = []
                for st in prog.statements:
                    self.assertLess(st.start, st.end)
                    while stack and stack[-1].end <= st.start:
                        stack.pop()
                    if stack:
                        self.assertLessEqual(st.end, stack[-1].end, f"{st.verb} at line {st.line} overlaps")
                    stack.append(st)

    def test_legacy_example_copy_replacing_and_file(self):
        prog = Program(os.path.join(support.EXAMPLES, "src", "LEGACY.cbl"))
        item_names = [d.name for d in prog.data_items]
        self.assertIn("M-KEY", item_names)
        self.assertIn("WS-KEY", item_names)
        self.assertEqual(prog.files["MASTER-FILE"]["status"], "WS-FS")
        self.assertEqual(prog.files["MASTER-FILE"]["records"], ["M-REC"])

    def test_legacy_example_statements_closed_only_by_the_period(self):
        prog = Program(os.path.join(support.EXAMPLES, "src", "LEGACY.cbl"))
        read = statement(prog, "READ")
        self.assertEqual([p[0] for p in read.phrases], ["INVALID KEY", "NOT INVALID KEY"])
        self.assertTrue(read.needs_terminator())
        self.assertEqual(prog.call_target(statement(prog, "CALL")), ("WS-PROG", False))
        self.assertEqual([kind for _, kind, _ in prog.clock_sites()], ["TIME"])

    def test_legacy_example_continued_literal(self):
        prog = Program(os.path.join(support.EXAMPLES, "src", "LEGACY.cbl"))
        self.assertIn('"hello, world. this is not a final period"', [t.text for t in prog.tokens if t.kind == "lit"])


if __name__ == "__main__":
    unittest.main()
