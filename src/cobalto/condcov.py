#!/usr/bin/env python3
"""condcov - compound-condition coverage for Cobalto (CBLT). Stdlib only.

An IF (or a WHEN of an EVALUATE TRUE) with AND / OR is measured per
operand: each elementary condition counts the times it was true and the
times it was false, only when the program actually evaluated it. To do
that the CLI does not touch the statement: before it, it inserts a tree
of nested IFs that evaluates the condition again in the same order and
with the same short-circuit as the compiler (in "A AND B", B is only
evaluated if A was true; in "A OR B", only if A was false), adds to one
counter per outcome of each operand and discards the result. COBOL
conditions have no side effects, so evaluating them twice gives the
same result (the exception is FUNCTION RANDOM inside a condition).

What is understood: AND, OR, NOT on a parenthesized group, nested
groups, and the abbreviated combined conditions of the standard
("WS-X = 1 OR 2", "WS-X = 1 OR > 5"), which are expanded with the
subject and the operator of the previous relation. A condition name
(level 88) is told apart from an abbreviation by the DATA DIVISION.
When in doubt (an abbreviation with NOT, an operand that is not
recognized, a condition too long for column 72) the statement keeps the
regular branch coverage and is not measured per operand.
"""

REL = {"=", "<", ">", ">=", "<=", "<>", "EQUAL", "EQUALS", "GREATER", "LESS", "EXCEEDS", "UNEQUAL"}
REL_TAIL = REL | {"THAN", "TO", "OR", "NOT", "IS"}
CLASS = {"NUMERIC", "ALPHABETIC", "ALPHABETIC-LOWER", "ALPHABETIC-UPPER", "POSITIVE",
         "NEGATIVE", "ZERO", "ZEROS", "ZEROES", "OMITTED"}
FIGURATIVE = {"ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES", "HIGH-VALUE", "HIGH-VALUES",
              "LOW-VALUE", "LOW-VALUES", "QUOTE", "QUOTES", "NULL", "NULLS", "ALL"}
MAX_OPERANDS = 8


class CondError(Exception):
    """The condition cannot be measured per operand (it is left as is)."""


class Op:
    """Elementary condition: tokens as is, with the 'glued to the
    previous one' flag (no space in the original) to rebuild the text."""
    __slots__ = ("pieces", "idx_true", "idx_false")

    def __init__(self, pieces):
        self.pieces = pieces            # [(text, glued)]
        self.idx_true = self.idx_false = None

    def text(self, limit=None):
        s = "".join(("" if glued else " ") + t for t, glued in self.pieces).strip()
        return s if limit is None or len(s) <= limit else s[:limit - 3] + "..."


def pieces_of(toks):
    out, prev = [], None
    for t in toks:
        glued = prev is not None and prev.end_line == t.line and prev.end_col + 1 == t.col
        out.append((t.text, glued))
        prev = t
    return out


def _is_operator_or(toks, i):
    """The OR in 'GREATER THAN OR EQUAL TO' is not a connective."""
    return (i > 0 and toks[i - 1].up in ("THAN", "GREATER", "LESS")
            and i + 1 < len(toks) and toks[i + 1].up == "EQUAL")


def _matching(toks, i):
    depth = 0
    for k in range(i, len(toks)):
        if toks[k].text == "(":
            depth += 1
        elif toks[k].text == ")":
            depth -= 1
            if depth == 0:
                return k
    raise CondError("unclosed parenthesis")


def _is_group(toks, i):
    """A '(' opens a logical group if inside it, at level 0, there is a
    connective or a relation or class operator; otherwise it is
    arithmetic or a condition name in parentheses."""
    k = _matching(toks, i)
    depth = 0
    for m in range(i + 1, k):
        u = toks[m].up
        if toks[m].text == "(":
            depth += 1
        elif toks[m].text == ")":
            depth -= 1
        elif depth == 0 and (u in ("AND", "NOT", "IS") or (u == "OR" and not _is_operator_or(toks, m))
                             or u in REL or u in CLASS):
            return True
    return False


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i].up if self.i < len(self.t) else None

    def expr(self):
        terms = [self.term()]
        while self.peek() == "OR" and not _is_operator_or(self.t, self.i):
            self.i += 1
            terms.append(self.term())
        return ("OR", terms) if len(terms) > 1 else terms[0]

    def term(self):
        factors = [self.factor()]
        while self.peek() == "AND":
            self.i += 1
            factors.append(self.factor())
        return ("AND", factors) if len(factors) > 1 else factors[0]

    def factor(self):
        t = self.t
        if self.i >= len(t):
            raise CondError("incomplete condition")
        if t[self.i].up == "NOT" and self.i + 1 < len(t) and t[self.i + 1].text == "(" \
                and _is_group(t, self.i + 1):
            self.i += 1
            return ("NOT", [self.factor()])
        if t[self.i].text == "(" and _is_group(t, self.i):
            self.i += 1
            e = self.expr()
            if self.peek() != ")" or t[self.i].text != ")":
                raise CondError("missing ')'")
            self.i += 1
            return e
        start, depth = self.i, 0
        while self.i < len(t):
            u, x = t[self.i].up, t[self.i].text
            if x == "(":
                depth += 1
            elif x == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and (u == "AND" or (u == "OR" and not _is_operator_or(t, self.i))):
                break
            self.i += 1
        if self.i == start:
            raise CondError("empty operand")
        return ("OP", t[start:self.i])


def parse(toks):
    p = _Parser(toks)
    tree = p.expr()
    if p.i != len(toks):
        raise CondError("leftover text in the condition")
    return tree


def is_compound(toks):
    depth = 0
    for i, t in enumerate(toks):
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif t.up == "AND" or (t.up == "OR" and not _is_operator_or(toks, i)):
            return True
    return False


# ------------------------------------------------------- abbreviations
def _split_relation(toks):
    """(subject, operator, object) of a relation, or None if there is
    no relation operator at level 0."""
    depth, i = 0, None
    for k, t in enumerate(toks):
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif depth == 0 and t.up in REL:
            i = k
            break
    if i is None:
        return None
    i0 = i
    while i0 > 0 and toks[i0 - 1].up in ("IS", "NOT"):
        i0 -= 1
    k = i + 1
    while k < len(toks) and toks[k].up in REL_TAIL and not (toks[k].up == "NOT" and k > i + 1):
        if toks[k].up == "OR" and not _is_operator_or(toks, k):
            break
        k += 1
    return toks[:i0], toks[i0:k], toks[k:]


class _Ctx:
    def __init__(self, cond_names, data_names):
        self.cond_names, self.data_names = cond_names, data_names
        self.last = None            # (subject, operator) of the last complete relation

    def operand(self, toks):
        """Op with the full text of the operand (expanded if it was an
        abbreviated combined condition)."""
        rel = _split_relation(toks)
        if rel is not None:
            subj, oper, obj = rel
            if not obj:
                raise CondError("relation without an object")
            if subj:
                # a NOT before the subject negates this relation only: an
                # abbreviation after it takes the subject without the NOT
                # ("NOT A = 1 OR 2" is (NOT A = 1) OR A = 2)
                self.last = (subj[1:] if subj[0].up == "NOT" and len(subj) > 1 else subj, oper)
                return Op(pieces_of(toks))
            if self.last is None:
                raise CondError("abbreviation without a previous relation")
            # operator and object: the operator is the one the next
            # abbreviation takes ("A = 1 OR > 8 OR 5" ends in A > 5)
            self.last = (self.last[0], oper)
            return Op(pieces_of(self.last[0]) + pieces_of(toks))
        ups = [t.up for t in toks]
        # class or sign condition: a subject and then the class word. ZERO
        # alone is not one: after a relation it is an abbreviated object.
        core = ups[1:] if ups[0] == "NOT" else ups
        if len(core) > 1 and core[-1] in CLASS and core[0] not in FIGURATIVE:
            return Op(pieces_of(toks))
        if ups[0] == "NOT" and len(ups) > 1 and ups[1] in self.cond_names:
            return Op(pieces_of(toks))
        first = toks[0]
        if len(toks) == 1 and first.kind == "word" and first.up in self.cond_names:
            if first.up in self.data_names:
                raise CondError(f"{first.text} is both a condition name and a data name")
            return Op(pieces_of(toks))
        # abbreviation: only the object
        if ups[0] == "NOT":
            raise CondError("abbreviation with NOT")
        if first.kind in ("num", "lit") or first.up in FIGURATIVE or \
                (first.kind == "word" and first.up in self.data_names and first.up not in self.cond_names):
            if self.last is None:
                raise CondError("abbreviation without a previous relation")
            subj, oper = self.last
            return Op(pieces_of(subj) + pieces_of(oper) + pieces_of(toks))
        raise CondError(f"unrecognized operand: {' '.join(t.text for t in toks)}")

    def walk(self, node):
        kind, items = node
        if kind == "OP":
            return ("OP", self.operand(items))
        return (kind, [self.walk(n) for n in items])


def normalize(tree, cond_names, data_names):
    return _Ctx(cond_names, data_names).walk(tree)


def operands(tree):
    kind, items = tree
    if kind == "OP":
        return [items]
    out = []
    for n in items:
        out.extend(operands(n))
    return out


# ---------------------------------------------------------- COBOL
def _wrap(prefix, op, budget):
    """'IF <operand>' lines that stay within the column budget."""
    lines, cur = [], prefix
    for text, glued in op.pieces:
        sep = "" if glued and cur != prefix else " " if cur != prefix else ""
        if len(cur) + len(sep) + len(text) <= budget or cur == prefix:
            cur += sep + text
        else:
            lines.append(cur)
            cur = "    " + text
        if len(cur) > budget:
            raise CondError("condition too long for column 72")
    lines.append(cur)
    return lines


def gen(tree, on_true, on_false, hit_item, depth=0, budget=44):
    """COBOL lines that evaluate tree the way the compiler does and add
    to the counters of each operand; on_true / on_false are the lines to
    execute depending on the result. depth: levels of IF that wrap these
    lines (each one adds two columns of indentation to them)."""
    kind, items = tree
    if kind == "OP":
        op = items
        body_t = ([f"ADD 1 TO {hit_item}({op.idx_true})"] if op.idx_true else []) + on_true
        body_f = ([f"ADD 1 TO {hit_item}({op.idx_false})"] if op.idx_false else []) + on_false
        lines = _wrap("IF ", op, budget - 2 * depth)
        lines += ["  " + l for l in body_t] or ["  CONTINUE"]
        if body_f:
            lines.append("ELSE")
            lines += ["  " + l for l in body_f]
        lines.append("END-IF")
        return lines
    if kind == "NOT":
        return gen(items[0], on_false, on_true, hit_item, depth, budget)
    if kind == "AND":
        rest = on_true
        for n in reversed(items[1:]):
            rest = gen(n, rest, on_false, hit_item, depth + 1, budget)
        return gen(items[0], rest, on_false, hit_item, depth, budget)
    rest = on_false
    for n in reversed(items[1:]):
        rest = gen(n, on_true, rest, hit_item, depth + 1, budget)
    return gen(items[0], on_true, rest, hit_item, depth, budget)


def build(cond_list, cond_names, data_names, new_counter, hit_item):
    """cond_list: list of token lists (an IF: one; EVALUATE TRUE: one
    WHEN per element, in order). Returns (COBOL lines, [[Op per
    operand] per condition]). Only compound conditions get counters;
    simple ones act as a gate for the ones that follow. Raises
    CondError if something is not understood."""
    trees, ops_by_cond = [], []
    for toks in cond_list:
        tree = normalize(parse(toks), cond_names, data_names)
        ops = operands(tree)
        if len(ops) > MAX_OPERANDS:
            raise CondError("too many operands")
        if len(ops) > 1:
            for op in ops:
                op.idx_true, op.idx_false = new_counter(), new_counter()
            ops_by_cond.append(ops)
        else:
            ops_by_cond.append([])
        trees.append(tree)
    lines = []
    for k, tree in reversed(list(enumerate(trees))):
        lines = gen(tree, [], lines, hit_item, depth=k)
    if len(lines) > 400:
        raise CondError("condition tree too large")
    return lines, ops_by_cond
