"""Unit tests for cobalto.condcov, the per-operand coverage of compound conditions.

Conditions are tokenized from one line of text; the COBOL that condcov
generates is checked by executing its nested IFs with a small interpreter
instead of comparing text.
"""
import itertools
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from cobalto import cobparse, condcov
from cobalto.condcov import CondError

COND_NAMES = {"WS-DONE", "WS-OPEN"}
DATA_NAMES = {"WS-A", "WS-B", "WS-C", "WS-TABLE", "WS-TEXT"}


def tokens(text):
    """Tokens of a condition written on one line."""
    line = cobparse.Line(" " * 7 + text, 1, ("condition", 1), "code", text, 8)
    return cobparse.tokenize([line], "fixed")


def shape(tree):
    """A tree as nested tuples with the text of each operand, raw or normalized."""
    kind, items = tree
    if kind == "OP":
        return items.text() if isinstance(items, condcov.Op) else " ".join(t.text for t in items)
    return (kind,) + tuple(shape(node) for node in items)


def measured(text):
    """The tree of a condition with its operands expanded."""
    return condcov.normalize(condcov.parse(tokens(text)), COND_NAMES, DATA_NAMES)


def operands(text):
    return [op.text() for op in condcov.operands(measured(text))]


def number_operands(tree):
    """Gives each operand its two counters, the way build() does: 1 and 2 to
    the first operand (true, false), 3 and 4 to the second, and so on."""
    counter = itertools.count(1)
    for op in condcov.operands(tree):
        op.idx_true, op.idx_false = next(counter), next(counter)


def execute(lines, truth):
    """Runs the nested IFs that condcov generates. truth maps the text of an
    operand to its value. Returns the statements executed, in order."""
    done, stack = [], []        # stack of [enclosing block runs, value of the IF, in its ELSE]

    def running():
        return not stack or (stack[-1][0] and stack[-1][1] != stack[-1][2])

    for raw in lines:
        text = raw.strip()
        if text.startswith("IF "):
            active = running()
            stack.append([active, truth[text[3:]] if active else False, False])
        elif text == "ELSE":
            stack[-1][2] = True
        elif text == "END-IF":
            stack.pop()
        elif running() and text != "CONTINUE":
            done.append(text)
    if stack:
        raise AssertionError("unbalanced IF / END-IF in the generated lines")
    return done


def counters(executed):
    """Counter numbers of the 'ADD 1 TO HIT(n)' statements executed."""
    return [int(x[len("ADD 1 TO HIT("):-1]) for x in executed if x.startswith("ADD 1 TO HIT(")]


def reference(tree, truth):
    """(value, counters) of evaluating tree left to right with short circuit."""
    hits = []

    def value_of(node):
        kind, items = node
        if kind == "OP":
            value = truth[items.text()]
            hits.append(items.idx_true if value else items.idx_false)
            return value
        if kind == "NOT":
            return not value_of(items[0])
        if kind == "AND":
            return all(value_of(n) for n in items)
        return any(value_of(n) for n in items)

    return value_of(tree), hits


class IsCompoundTest(unittest.TestCase):
    def test_and_makes_a_condition_compound(self):
        self.assertTrue(condcov.is_compound(tokens("WS-A = 1 AND WS-B = 2")))

    def test_or_makes_a_condition_compound(self):
        self.assertTrue(condcov.is_compound(tokens("WS-A = 1 OR WS-DONE")))

    def test_single_relation_is_not_compound(self):
        self.assertFalse(condcov.is_compound(tokens("WS-A >= WS-B")))

    def test_negated_relation_is_not_compound(self):
        self.assertFalse(condcov.is_compound(tokens("NOT WS-A = 1")))

    def test_or_of_greater_than_or_equal_to_is_not_a_connective(self):
        self.assertFalse(condcov.is_compound(tokens("WS-A GREATER THAN OR EQUAL TO WS-B")))

    def test_or_of_less_or_equal_is_not_a_connective(self):
        self.assertFalse(condcov.is_compound(tokens("WS-A IS LESS OR EQUAL WS-B")))

    def test_connective_inside_a_literal_does_not_count(self):
        self.assertFalse(condcov.is_compound(tokens('WS-TEXT = "THIS AND THAT OR MORE"')))


class ParseTest(unittest.TestCase):
    """parse(): the tree of AND / OR / NOT over raw operands."""

    def tree(self, text):
        return shape(condcov.parse(tokens(text)))

    def test_single_condition_is_one_operand(self):
        self.assertEqual(self.tree("WS-A = 1"), "WS-A = 1")

    def test_and(self):
        self.assertEqual(self.tree("WS-A = 1 AND WS-B = 2"), ("AND", "WS-A = 1", "WS-B = 2"))

    def test_or(self):
        self.assertEqual(self.tree("WS-A = 1 OR WS-B = 2"), ("OR", "WS-A = 1", "WS-B = 2"))

    def test_chain_of_the_same_connective_is_one_node(self):
        self.assertEqual(self.tree("WS-A = 1 OR WS-B = 2 OR WS-C = 3"),
                         ("OR", "WS-A = 1", "WS-B = 2", "WS-C = 3"))

    def test_and_binds_tighter_than_or(self):
        self.assertEqual(self.tree("WS-A = 1 OR WS-B = 2 AND WS-C = 3"),
                         ("OR", "WS-A = 1", ("AND", "WS-B = 2", "WS-C = 3")))

    def test_and_before_or_keeps_the_same_precedence(self):
        self.assertEqual(self.tree("WS-A = 1 AND WS-B = 2 OR WS-C = 3"),
                         ("OR", ("AND", "WS-A = 1", "WS-B = 2"), "WS-C = 3"))

    def test_parentheses_group_an_or_inside_an_and(self):
        self.assertEqual(self.tree("(WS-A = 1 OR WS-B = 2) AND WS-C = 3"),
                         ("AND", ("OR", "WS-A = 1", "WS-B = 2"), "WS-C = 3"))

    def test_nested_groups(self):
        self.assertEqual(self.tree("WS-A = 1 AND (WS-B = 2 OR (WS-C = 3 AND WS-DONE))"),
                         ("AND", "WS-A = 1", ("OR", "WS-B = 2", ("AND", "WS-C = 3", "WS-DONE"))))

    def test_parentheses_around_one_relation_are_dropped(self):
        self.assertEqual(self.tree("WS-A = 1 OR (WS-B = 2)"), ("OR", "WS-A = 1", "WS-B = 2"))

    def test_not_on_a_group(self):
        self.assertEqual(self.tree("NOT (WS-A = 1 AND WS-B = 2)"), ("NOT", ("AND", "WS-A = 1", "WS-B = 2")))

    def test_not_on_a_group_inside_a_larger_condition(self):
        self.assertEqual(self.tree("WS-C = 3 OR NOT (WS-A = 1 AND WS-B = 2)"),
                         ("OR", "WS-C = 3", ("NOT", ("AND", "WS-A = 1", "WS-B = 2"))))

    def test_not_on_a_simple_condition_stays_in_the_operand(self):
        self.assertEqual(self.tree("NOT WS-A = 1 AND WS-B = 2"), ("AND", "NOT WS-A = 1", "WS-B = 2"))

    def test_not_inside_a_relation_stays_in_the_operand(self):
        self.assertEqual(self.tree("WS-A NOT = 1 OR WS-B IS NOT NUMERIC"),
                         ("OR", "WS-A NOT = 1", "WS-B IS NOT NUMERIC"))

    def test_or_of_a_relational_operator_does_not_split_the_operand(self):
        self.assertEqual(self.tree("WS-A GREATER THAN OR EQUAL TO WS-B AND WS-C = 1"),
                         ("AND", "WS-A GREATER THAN OR EQUAL TO WS-B", "WS-C = 1"))

    def test_arithmetic_parentheses_belong_to_the_operand(self):
        self.assertEqual(self.tree("(WS-A + WS-B) * 2 > 10 AND WS-C = 1"),
                         ("AND", "( WS-A + WS-B ) * 2 > 10", "WS-C = 1"))

    def test_subscript_belongs_to_the_operand(self):
        self.assertEqual(self.tree("WS-TABLE(WS-A) = 1 OR WS-TABLE(1:2) = 5"),
                         ("OR", "WS-TABLE ( WS-A ) = 1", "WS-TABLE ( 1 : 2 ) = 5"))

    def test_function_arguments_belong_to_the_operand(self):
        self.assertEqual(self.tree("WS-A = FUNCTION MAX(WS-B WS-C) AND WS-DONE"),
                         ("AND", "WS-A = FUNCTION MAX ( WS-B WS-C )", "WS-DONE"))

    def test_literal_with_connectives_is_part_of_one_operand(self):
        self.assertEqual(self.tree('WS-A = 1 OR WS-TEXT = "THIS AND THAT"'),
                         ("OR", "WS-A = 1", 'WS-TEXT = "THIS AND THAT"'))

    def test_unclosed_parenthesis_is_not_understood(self):
        with self.assertRaises(CondError):
            condcov.parse(tokens("WS-A = 1 AND (WS-B = 2 OR WS-C = 3"))

    def test_unopened_parenthesis_is_not_understood(self):
        with self.assertRaises(CondError):
            condcov.parse(tokens("WS-A = 1 AND WS-B = 2) OR WS-C = 3"))

    def test_condition_that_ends_in_a_connective_is_not_understood(self):
        with self.assertRaises(CondError):
            condcov.parse(tokens("WS-A = 1 AND"))

    def test_two_connectives_in_a_row_are_not_understood(self):
        with self.assertRaises(CondError):
            condcov.parse(tokens("WS-A = 1 AND OR WS-B = 2"))


class OperandTest(unittest.TestCase):
    """normalize(): what counts as an operand and how abbreviations expand."""

    def test_relations_are_operands_in_source_order(self):
        self.assertEqual(operands("WS-A = 1 AND (WS-B > 2 OR WS-C NOT < 3)"),
                         ["WS-A = 1", "WS-B > 2", "WS-C NOT < 3"])

    def test_operand_text_keeps_the_spacing_of_the_source(self):
        self.assertEqual(operands("WS-TABLE(WS-A) = 1 AND WS-TEXT(1:2)=\"AB\""),
                         ["WS-TABLE(WS-A) = 1", 'WS-TEXT(1:2)="AB"'])

    def test_condition_name_is_an_operand(self):
        self.assertEqual(operands("WS-DONE OR WS-OPEN"), ["WS-DONE", "WS-OPEN"])

    def test_negated_condition_name_is_an_operand(self):
        self.assertEqual(operands("WS-A = 1 AND NOT WS-DONE"), ["WS-A = 1", "NOT WS-DONE"])

    def test_class_condition_is_an_operand(self):
        self.assertEqual(operands("WS-A IS NUMERIC AND WS-TEXT IS NOT ALPHABETIC"),
                         ["WS-A IS NUMERIC", "WS-TEXT IS NOT ALPHABETIC"])

    def test_sign_condition_is_an_operand(self):
        self.assertEqual(operands("WS-A IS POSITIVE OR WS-B IS ZERO"), ["WS-A IS POSITIVE", "WS-B IS ZERO"])

    def test_not_on_a_group_adds_no_operand(self):
        self.assertEqual(operands("NOT (WS-A = 1 AND WS-DONE)"), ["WS-A = 1", "WS-DONE"])

    def test_abbreviation_with_only_the_object(self):
        self.assertEqual(operands("WS-A = 1 OR 2"), ["WS-A = 1", "WS-A = 2"])

    def test_abbreviation_with_operator_and_object(self):
        self.assertEqual(operands("WS-A = 1 OR > 5"), ["WS-A = 1", "WS-A > 5"])

    def test_abbreviation_chain_from_the_reference(self):
        self.assertEqual(operands("WS-A = 1 OR 2 OR > 8"), ["WS-A = 1", "WS-A = 2", "WS-A > 8"])

    # An object alone takes the last operator written: GnuCOBOL reads "WS-A = 1 OR > 8 OR 5" as
    # ... OR WS-A > 5.
    def test_abbreviation_takes_the_operator_of_a_previous_abbreviation(self):
        self.assertEqual(operands("WS-A = 1 OR > 8 OR 5"), ["WS-A = 1", "WS-A > 8", "WS-A > 5"])

    def test_abbreviation_with_and(self):
        self.assertEqual(operands("WS-A > 1 AND < 5"), ["WS-A > 1", "WS-A < 5"])

    def test_abbreviation_keeps_a_negated_operator(self):
        self.assertEqual(operands("WS-A NOT = 1 AND 2"), ["WS-A NOT = 1", "WS-A NOT = 2"])

    def test_abbreviation_keeps_a_worded_operator(self):
        self.assertEqual(operands("WS-A IS EQUAL TO 1 OR 2"), ["WS-A IS EQUAL TO 1", "WS-A IS EQUAL TO 2"])

    def test_abbreviation_takes_the_subject_of_the_nearest_previous_relation(self):
        self.assertEqual(operands("WS-A = 1 OR WS-B = 2 OR 3"), ["WS-A = 1", "WS-B = 2", "WS-B = 3"])

    def test_abbreviation_inside_a_group(self):
        self.assertEqual(operands("WS-A = 1 AND (WS-B = 2 OR 3)"), ["WS-A = 1", "WS-B = 2", "WS-B = 3"])

    def test_abbreviation_with_a_literal_object(self):
        self.assertEqual(operands('WS-TEXT = "A" OR "B"'), ['WS-TEXT = "A"', 'WS-TEXT = "B"'])

    def test_abbreviation_with_a_figurative_constant(self):
        self.assertEqual(operands("WS-TEXT = SPACES OR LOW-VALUES"), ["WS-TEXT = SPACES", "WS-TEXT = LOW-VALUES"])

    def test_data_name_alone_is_an_abbreviated_object(self):
        self.assertEqual(operands("WS-A = WS-B OR WS-C"), ["WS-A = WS-B", "WS-A = WS-C"])

    def test_condition_name_after_a_relation_is_not_an_abbreviation(self):
        self.assertEqual(operands("WS-A = 1 OR WS-DONE"), ["WS-A = 1", "WS-DONE"])

    # After "WS-A = 1 OR", ZERO is the abbreviated object (WS-A = ZERO), not a sign condition.
    def test_abbreviation_with_zero_as_the_object(self):
        self.assertEqual(operands("WS-A = 1 OR ZERO"), ["WS-A = 1", "WS-A = ZERO"])

    # "NOT WS-A = 1 OR 2" means (NOT WS-A = 1) OR WS-A = 2. Leaving it unmeasured would also be right.
    def test_leading_not_is_not_copied_to_an_abbreviated_operand(self):
        try:
            found = operands("NOT WS-A = 1 OR 2")
        except CondError:
            return
        self.assertEqual(found, ["NOT WS-A = 1", "WS-A = 2"])

    def test_abbreviation_with_not_is_not_measured(self):
        with self.assertRaises(CondError):
            measured("WS-A = 1 OR NOT 2")

    def test_abbreviation_without_a_previous_relation_is_not_measured(self):
        with self.assertRaises(CondError):
            measured("WS-DONE OR 2")

    def test_unknown_name_is_not_measured(self):
        with self.assertRaises(CondError):
            measured("WS-A = 1 OR NO-SUCH-NAME")

    def test_name_that_is_both_condition_and_data_is_not_measured(self):
        tree = condcov.parse(tokens("WS-A = 1 OR WS-BOTH"))
        with self.assertRaises(CondError):
            condcov.normalize(tree, COND_NAMES | {"WS-BOTH"}, DATA_NAMES | {"WS-BOTH"})

    def test_relation_without_an_object_is_not_measured(self):
        with self.assertRaises(CondError):
            measured("WS-A = AND WS-B = 1")


class OpTextTest(unittest.TestCase):
    def op(self, text):
        return condcov.Op(condcov.pieces_of(tokens(text)))

    def test_text_rebuilds_the_operand(self):
        self.assertEqual(self.op("WS-TABLE(WS-A)   =   1").text(), "WS-TABLE(WS-A) = 1")

    def test_text_shorter_than_the_limit_is_left_alone(self):
        self.assertEqual(self.op("WS-A = 1").text(28), "WS-A = 1")

    def test_text_longer_than_the_limit_is_cut_with_an_ellipsis(self):
        cut = self.op("WS-A-RATHER-LONG-FIELD-NAME = WS-ANOTHER-LONG-NAME").text(28)
        self.assertEqual(cut, "WS-A-RATHER-LONG-FIELD-NA...")
        self.assertEqual(len(cut), 28)


class GeneratedTreeTest(unittest.TestCase):
    """gen(): the nested IFs evaluate like the compiler and count each operand."""

    def run_condition(self, text, truth):
        tree = measured(text)
        number_operands(tree)
        executed = execute(condcov.gen(tree, ["REACH-TRUE"], ["REACH-FALSE"], "HIT"), truth)
        return tree, executed

    def test_and_counts_both_operands_when_the_first_is_true(self):
        _, executed = self.run_condition("WS-A = 1 AND WS-B = 2", {"WS-A = 1": True, "WS-B = 2": False})
        self.assertEqual(counters(executed), [1, 4])

    def test_and_does_not_evaluate_the_second_operand_when_the_first_is_false(self):
        _, executed = self.run_condition("WS-A = 1 AND WS-B = 2", {"WS-A = 1": False, "WS-B = 2": True})
        self.assertEqual(counters(executed), [2])

    def test_or_does_not_evaluate_the_second_operand_when_the_first_is_true(self):
        _, executed = self.run_condition("WS-A = 1 OR WS-B = 2", {"WS-A = 1": True, "WS-B = 2": False})
        self.assertEqual(counters(executed), [1])

    def test_or_counts_both_operands_when_the_first_is_false(self):
        _, executed = self.run_condition("WS-A = 1 OR WS-B = 2", {"WS-A = 1": False, "WS-B = 2": True})
        self.assertEqual(counters(executed), [2, 3])

    def test_not_on_a_group_counts_the_operands_as_evaluated_and_inverts_the_result(self):
        _, executed = self.run_condition("NOT (WS-A = 1 AND WS-B = 2)", {"WS-A = 1": True, "WS-B = 2": False})
        self.assertEqual(executed, ["ADD 1 TO HIT(1)", "ADD 1 TO HIT(4)", "REACH-TRUE"])

    def test_true_condition_runs_only_the_true_lines(self):
        _, executed = self.run_condition("WS-A = 1 OR WS-B = 2", {"WS-A = 1": False, "WS-B = 2": True})
        self.assertEqual([x for x in executed if x.startswith("REACH")], ["REACH-TRUE"])

    def test_false_condition_runs_only_the_false_lines(self):
        _, executed = self.run_condition("WS-A = 1 OR WS-B = 2", {"WS-A = 1": False, "WS-B = 2": False})
        self.assertEqual([x for x in executed if x.startswith("REACH")], ["REACH-FALSE"])

    def test_every_combination_matches_short_circuit_evaluation(self):
        conditions = ["WS-A = 1 AND WS-B = 2 AND WS-C = 3",
                      "WS-A = 1 OR WS-B = 2 OR WS-C = 3",
                      "WS-A = 1 OR WS-B = 2 AND WS-C = 3",
                      "WS-A = 1 AND WS-B = 2 OR WS-C = 3",
                      "(WS-A = 1 OR WS-B = 2) AND WS-C = 3",
                      "WS-A = 1 AND (WS-B = 2 OR NOT (WS-C = 3 AND WS-DONE))",
                      "NOT (WS-A = 1 OR WS-B = 2) AND NOT WS-DONE",
                      "(WS-A = 1 AND WS-DONE) OR (WS-B = 2 AND WS-OPEN) OR WS-C = 3",
                      "WS-A = 1 OR 2 OR > 8"]
        for text in conditions:
            tree = measured(text)
            number_operands(tree)
            lines = condcov.gen(tree, ["REACH-TRUE"], ["REACH-FALSE"], "HIT")
            names = [op.text() for op in condcov.operands(tree)]
            for values in itertools.product([True, False], repeat=len(names)):
                truth = dict(zip(names, values))
                with self.subTest(condition=text, truth=truth):
                    value, hits = reference(tree, truth)
                    executed = execute(lines, truth)
                    self.assertEqual(counters(executed), hits)
                    self.assertEqual([x for x in executed if x.startswith("REACH")],
                                     ["REACH-TRUE" if value else "REACH-FALSE"])

    def test_operand_without_counters_only_steers_the_evaluation(self):
        tree = measured("WS-A = 1")
        lines = condcov.gen(tree, ["REACH-TRUE"], ["REACH-FALSE"], "HIT")
        self.assertEqual(execute(lines, {"WS-A = 1": True}), ["REACH-TRUE"])
        self.assertEqual(execute(lines, {"WS-A = 1": False}), ["REACH-FALSE"])

    def test_if_with_nothing_to_do_gets_a_continue(self):
        lines = condcov.gen(measured("WS-A = 1"), [], [], "HIT")
        self.assertEqual(lines, ["IF WS-A = 1", "  CONTINUE", "END-IF"])


class BuildTest(unittest.TestCase):
    """build(): counters and COBOL for an IF or for the WHENs of an EVALUATE TRUE."""

    def build(self, *conditions):
        counter = itertools.count(1)
        self.given = []

        def new_counter():
            self.given.append(next(counter))
            return self.given[-1]

        return condcov.build([tokens(c) for c in conditions], COND_NAMES, DATA_NAMES, new_counter, "HIT")

    def test_each_operand_gets_a_true_and_a_false_counter_in_order(self):
        _, ops = self.build("WS-A = 1 AND (WS-B = 2 OR WS-DONE)")
        self.assertEqual([(op.text(), op.idx_true, op.idx_false) for op in ops[0]],
                         [("WS-A = 1", 1, 2), ("WS-B = 2", 3, 4), ("WS-DONE", 5, 6)])

    def test_counters_are_taken_from_the_callback(self):
        self.build("WS-A = 1 AND WS-B = 2")
        self.assertEqual(self.given, [1, 2, 3, 4])

    def test_generated_lines_add_to_the_counters_of_the_operands_evaluated(self):
        lines, _ = self.build("WS-A = 1 AND WS-B = 2")
        self.assertEqual(counters(execute(lines, {"WS-A = 1": True, "WS-B = 2": True})), [1, 3])

    def test_generated_lines_use_the_given_counter_table(self):
        lines, _ = self.build("WS-A = 1 AND WS-B = 2")
        adds = [ln.strip() for ln in lines if "ADD" in ln]
        self.assertEqual(sorted(adds), ["ADD 1 TO HIT(1)", "ADD 1 TO HIT(2)", "ADD 1 TO HIT(3)", "ADD 1 TO HIT(4)"])

    def test_simple_condition_gets_no_counters(self):
        _, ops = self.build("WS-A = 1")
        self.assertEqual(ops, [[]])
        self.assertEqual(self.given, [])

    def test_abbreviated_operands_are_expanded_in_the_generated_lines(self):
        lines, _ = self.build("WS-A = 1 OR 2")
        self.assertEqual([ln.strip() for ln in lines if ln.strip().startswith("IF ")],
                         ["IF WS-A = 1", "IF WS-A = 2"])

    def test_eight_operands_are_measured(self):
        _, ops = self.build(" OR ".join(f"WS-A = {n}" for n in range(1, 9)))
        self.assertEqual(len(ops[0]), 8)

    def test_more_than_eight_operands_are_not_measured(self):
        with self.assertRaises(CondError):
            self.build(" OR ".join(f"WS-A = {n}" for n in range(1, 10)))

    def test_condition_that_is_not_understood_raises(self):
        with self.assertRaises(CondError):
            self.build("WS-A = 1 OR NOT 2")

    def test_long_operand_is_wrapped_within_the_column_budget(self):
        lines, _ = self.build("WS-A = 1 AND WS-TABLE-ENTRY-WITH-A-LONG-NAME(WS-A) = WS-ANOTHER-RATHER-LONG-NAME")
        self.assertLessEqual(max(len(ln) for ln in lines), 44)
        joined = " ".join(ln.strip() for ln in lines)
        self.assertIn("IF WS-TABLE-ENTRY-WITH-A-LONG-NAME(WS-A) = WS-ANOTHER-RATHER-LONG-NAME", joined)

    def test_operand_too_long_to_wrap_is_not_measured(self):
        with self.assertRaises(CondError):
            self.build("WS-A = 1 AND WS-A-FIELD-NAME-THAT-IS-FAR-TOO-LONG-FOR-THE-COLUMN-BUDGET = 2")

    def test_each_when_of_an_evaluate_true_gets_its_own_operands(self):
        _, ops = self.build("WS-A = 1 AND WS-B = 1", "WS-DONE", "WS-B = 2 OR WS-C = 3")
        self.assertEqual([[op.text() for op in group] for group in ops],
                         [["WS-A = 1", "WS-B = 1"], [], ["WS-B = 2", "WS-C = 3"]])

    def test_later_when_is_evaluated_only_if_the_earlier_ones_were_false(self):
        lines, ops = self.build("WS-A = 1 AND WS-B = 1", "WS-DONE", "WS-B = 2 OR WS-C = 3")
        first, _, third = ops
        truth = {"WS-A = 1": True, "WS-B = 1": True, "WS-DONE": False, "WS-B = 2": True, "WS-C = 3": True}
        self.assertEqual(counters(execute(lines, truth)), [first[0].idx_true, first[1].idx_true])
        truth.update({"WS-B = 1": False})
        self.assertEqual(counters(execute(lines, truth)),
                         [first[0].idx_true, first[1].idx_false, third[0].idx_true])

    def test_simple_when_that_is_true_stops_the_chain(self):
        lines, _ = self.build("WS-DONE", "WS-B = 2 OR WS-C = 3")
        self.assertEqual(counters(execute(lines, {"WS-DONE": True, "WS-B = 2": True, "WS-C = 3": True})), [])


if __name__ == "__main__":
    unittest.main()
