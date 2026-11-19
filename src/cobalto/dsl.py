"""The .cblt DSL: parser, and expansion of an external suite to COBOL 85."""
import os
import re
from dataclasses import dataclass, field
from typing import NamedTuple, Optional

from .cobolgen import AREA_B, CobolWriter
from .messages import CobaltoError

KW = re.compile(r"^\s*(TESTSUITE|TESTCASE|BEFORE-EACH|END-BEFORE|AFTER-EACH|END-AFTER|"
                r"IGNORE|EXPECT|WORKING-STORAGE|PROGRAM|MOCK|END-MOCK|VERIFY|RUN|ON)(?![A-Za-z0-9-])(.*)$", re.I)
MOCK_RE = re.compile(r"^(PARAGRAPH|CALL|FILE|SQL|CLOCK)(?:\s+(.+?))?\s*$", re.I)
MOCK_ON_RE = re.compile(r"^(READ|WRITE|REWRITE|DELETE|START|OPEN|CLOSE)(\s+AT\s+END)?\s*$", re.I)
CLOCK_RE = re.compile(r"^\s*(DATE|DAY|TIME|DAY-OF-WEEK)(?:\s+(YYYYMMDD|YYYYDDD))?\s+('[^']*'|\"[^\"]*\")\s*$", re.I)
VERIFY_KINDS = ("PARAGRAPH", "CALL", "READ", "WRITE", "REWRITE", "DELETE", "START", "OPEN", "CLOSE", "SQL", "CLOCK", "STOP")
NO_NAME_KINDS = ("SQL", "CLOCK", "STOP")
COMMENT = re.compile(r"^(\s{6}\*|\s*\*>)")
LIT = r"""('(?:[^']|'')*'|"(?:[^"]|"")*")"""
QUOTED = re.compile(LIT)
EXPECT_RE = re.compile(
    r"^(?P<subj>\S+)\s+(?P<not>NOT\s+)?TO\s+"
    r"(?:(?P<contain>CONTAIN)\s+(?P<cval>.+)"
    r"|BE\s+(?:"
    r"(?P<numeric>NUMERIC)\s+(?P<nval>.+)"
    r"|(?P<gt>GREATER\s+THAN)\s+(?P<gval>.+)"
    r"|(?P<lt>LESS\s+THAN)\s+(?P<lval>.+)"
    r"|(?P<between>BETWEEN)\s+(?P<b1>.+?)\s+AND\s+(?P<b2>.+)"
    r"|(?P<bool>TRUE|FALSE)"
    r"|(?P<fig>SPACES?|ZEROS?|ZEROES)"
    r"|(?P<val>.+)))\s*$", re.I)


class DslError(CobaltoError):
    """A syntax error in a .cblt file (CBLT-E200). The parser knows the line;
    whoever knows the file fills it in before the error leaves."""

    def __init__(self, line, detail, file="?"):
        super().__init__("E200", file=file, line=line, detail=detail)


class Stmt(NamedTuple):
    """One line of a suite: its line number in the .cblt, what it is
    ("COBOL", "EXPECT", "MOCK", "VERIFY" or "RUN") and its content: the text
    of the line, or the Mock or Verify it declares."""
    line: int
    kind: str
    payload: object


@dataclass
class Mock:
    """A MOCK ... END-MOCK block."""
    kind: str                   # PARAGRAPH, CALL, FILE, SQL or CLOCK
    name: str
    line: int
    where: str                  # "case" or "before": where it was declared
    body: list = field(default_factory=list)    # statements of a PARAGRAPH, CALL or SQL mock
    ops: dict = field(default_factory=dict)     # FILE mock: operation -> statements
    clock: dict = field(default_factory=dict)   # CLOCK mock: what is read -> literal
    op: Optional[str] = None    # FILE mock: the ON block being read by the parser
    target: object = None       # set by the in-program generator: what it replaces
    variant: int = 0            # set by the in-program generator: its position on that target


@dataclass
class Verify:
    """A VERIFY ... HAPPENED ... line."""
    kind: str
    name: str
    mode: str                   # "exact", "atleast" or "nomore"
    count: int
    line: int
    text: str
    op: str = ""                # set by the in-program generator: the counted operation
    target: object = None       # set by the in-program generator


@dataclass
class Case:
    """A TESTCASE."""
    name: str
    line: int
    ignored: bool
    stmts: list = field(default_factory=list)       # Stmt
    kind: str = ""              # "interface" or "internal", set when the suite is generated
    reasons: list = field(default_factory=list)     # what makes it internal: {"construct", "line"}


@dataclass
class Suite:
    """A parsed .cblt file."""
    file: str
    id: Optional[str] = None
    line: int = 1                                   # line of TESTSUITE
    desc: str = ""
    program: Optional[str] = None                   # in-program mode: PROGRAM name | "path.cbl"
    ws: list = field(default_factory=list)          # Stmt of WORKING-STORAGE
    before: list = field(default_factory=list)      # Stmt of BEFORE-EACH
    after: list = field(default_factory=list)       # Stmt of AFTER-EACH
    cases: list = field(default_factory=list)       # Case
    mocks: list = field(default_factory=list)       # every Mock of the suite, in order
    verifies: list = field(default_factory=list)    # every Verify
    runs: list = field(default_factory=list)        # lines with RUN [USING ...] (in-program only)


def parse_verify(n, rest):
    toks = rest.split()
    if not toks or toks[0].upper() not in VERIFY_KINDS:
        raise DslError(n, "VERIFY needs PARAGRAPH, CALL, READ, WRITE, REWRITE, DELETE, START, OPEN, CLOSE, SQL, CLOCK or STOP")
    kind, i, name = toks[0].upper(), 1, None
    if len(toks) > 1 and not (kind in NO_NAME_KINDS and toks[1].upper() in ("NEVER", "HAPPENED")):
        name, i = toks[1], 2
    if name is None and kind not in NO_NAME_KINDS:
        raise DslError(n, f"VERIFY {kind} needs a name")
    tail = " ".join(toks[i:]).upper()
    pats = [(r"^NEVER HAPPENED$", "exact", 0), (r"^HAPPENED ONCE$", "exact", 1),
            (r"^HAPPENED (\d+) TIMES?$", "exact", None),
            (r"^HAPPENED AT LEAST (\d+) TIMES?$", "atleast", None),
            (r"^HAPPENED (?:NO MORE THAN|AT MOST) (\d+) TIMES?$", "nomore", None)]
    for pat, mode, cnt in pats:
        m = re.match(pat, tail)
        if m:
            return Verify(kind=kind, name=name or "", mode=mode, line=n, text=rest,
                          count=cnt if cnt is not None else int(m.group(1)))
    raise DslError(n, "VERIFY: expected NEVER HAPPENED, HAPPENED ONCE, HAPPENED n TIMES, "
                      "HAPPENED AT LEAST n TIMES or HAPPENED NO MORE THAN n TIMES")


def parse_dsl(path):
    s = Suite(path)
    state, cur, mock = "head", None, None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or COMMENT.match(line):
                continue
            m = KW.match(line)
            kw = m.group(1).upper() if m else None
            rest = m.group(2).strip() if m else ""
            if kw == "ON" and (mock is None or mock.kind != "FILE"):
                kw, rest = None, ""          # a bare ON is plain COBOL
            if mock is not None:
                # inside MOCK ... END-MOCK
                if kw == "END-MOCK":
                    mock = None
                elif mock.kind == "FILE" and kw == "ON":
                    mo = MOCK_ON_RE.match(rest)
                    if not mo:
                        raise DslError(n, "inside MOCK FILE: ON READ [AT END], ON WRITE, ON REWRITE, ON DELETE, ON START, ON OPEN or ON CLOSE")
                    mock.op = mo.group(1).upper()
                    body = mock.ops.setdefault(mock.op, [])
                    if mo.group(2):
                        body.append(Stmt(n, "COBOL", AREA_B + "SET CBLT-AT-END TO TRUE"))
                elif mock.kind == "CLOCK":
                    mc = CLOCK_RE.match(line)
                    if not mc:
                        raise DslError(n, "inside MOCK CLOCK: DATE 'yymmdd', DATE YYYYMMDD '...', DAY 'yyddd', DAY YYYYDDD '...', DAY-OF-WEEK 'd' or TIME 'hhmmsscc'")
                    kind = mc.group(1).upper() + (" " + mc.group(2).upper() if mc.group(2) else "")
                    mock.clock[kind] = mc.group(3)
                else:
                    if kw == "EXPECT":
                        item = Stmt(n, "EXPECT", rest)
                    elif kw is not None:
                        raise DslError(n, f"{kw} is not allowed inside a MOCK")
                    else:
                        item = Stmt(n, "COBOL", line)
                    if mock.kind == "FILE":
                        if mock.op is None:
                            raise DslError(n, "inside MOCK FILE the statements go after ON READ, ON WRITE, etc.")
                        mock.ops[mock.op].append(item)
                    else:
                        mock.body.append(item)
                continue
            if kw == "PROGRAM":
                if not rest:
                    raise DslError(n, "PROGRAM needs a program name or a quoted path")
                s.program = rest
                continue
            if kw == "MOCK":
                if state not in ("case", "before"):
                    raise DslError(n, "MOCK can only go inside a TESTCASE or BEFORE-EACH")
                mm = MOCK_RE.match(rest)
                if not mm:
                    raise DslError(n, "MOCK needs PARAGRAPH name, CALL 'PROG', FILE name, SQL ['text'] or CLOCK")
                kind, name = mm.group(1).upper(), (mm.group(2) or "").strip()
                if kind in ("PARAGRAPH", "CALL", "FILE") and not name:
                    raise DslError(n, f"MOCK {kind} needs a name")
                mock = Mock(kind=kind, name=name, line=n, where=state)
                s.mocks.append(mock)
                (cur.stmts if state == "case" else s.before).append(Stmt(n, "MOCK", mock))
                continue
            if kw == "VERIFY":
                if state != "case":
                    raise DslError(n, "VERIFY outside a TESTCASE")
                v = parse_verify(n, rest)
                s.verifies.append(v)
                cur.stmts.append(Stmt(n, "VERIFY", v))
                continue
            if kw == "RUN":
                if state != "case":
                    raise DslError(n, "RUN outside a TESTCASE")
                s.runs.append(n)
                cur.stmts.append(Stmt(n, "RUN", rest))
                continue
            if kw == "TESTSUITE":
                parts = rest.split(None, 1)
                if not parts or not re.match(r"^[A-Za-z][A-Za-z0-9-]{0,29}$", parts[0]):
                    raise DslError(n, "TESTSUITE needs a program identifier (for example TSTDISC)")
                s.id, s.line = parts[0].upper(), n
                s.desc = parts[1].strip("'\"") if len(parts) > 1 else ""
                state = "head"
            elif kw == "WORKING-STORAGE":
                state = "ws"
            elif kw == "BEFORE-EACH":
                state = "before"
            elif kw == "AFTER-EACH":
                state = "after"
            elif kw in ("END-BEFORE", "END-AFTER"):
                state = "head"
            elif kw == "IGNORE":
                state = "ignore"
            elif kw == "TESTCASE":
                name = rest.strip("'\"")
                if not name:
                    raise DslError(n, "TESTCASE needs a quoted description")
                cur = Case(name=name[:60], line=n, ignored=state == "ignore")
                s.cases.append(cur)
                state = "case"
            elif kw == "EXPECT":
                if state != "case":
                    raise DslError(n, "EXPECT outside a TESTCASE")
                cur.stmts.append(Stmt(n, "EXPECT", rest))
            else:
                item = Stmt(n, "COBOL", line)
                if state == "ws":
                    s.ws.append(item)
                elif state == "before":
                    s.before.append(item)
                elif state == "after":
                    s.after.append(item)
                elif state == "case":
                    cur.stmts.append(item)
                else:
                    raise DslError(n, "statement outside WORKING-STORAGE, BEFORE-EACH, AFTER-EACH or TESTCASE")
    if mock is not None:
        raise DslError(mock.line, "MOCK without END-MOCK")
    if not s.id:
        raise DslError(1, "TESTSUITE is missing")
    if not s.program and (s.mocks or s.verifies or s.runs):
        first = min([m.line for m in s.mocks] + [v.line for v in s.verifies] + s.runs)
        raise DslError(first, "MOCK, VERIFY and RUN are only valid in a suite with PROGRAM (in-program mode)")
    return s


def gen_expect(w, origin, text):
    m = EXPECT_RE.match(text.strip())
    if not m:
        raise DslError(origin[1], f"unrecognized EXPECT: {text}")
    subj = m.group("subj")
    neg = bool(m.group("not"))
    fig = (m.group("fig") or "").upper()
    if neg and (m.group("contain") or m.group("numeric") or m.group("gt") or m.group("lt")
                or m.group("between") or fig.startswith("ZERO")):
        # the core has no negated form of these checks: saying so is better
        # than a check that passes whatever the value is
        raise DslError(origin[1], "NOT is only supported with 'text', SPACES, TRUE or FALSE; "
                                  "for a number, write the opposite check (for example LESS THAN)")
    w.move_literal(("EXPECT " + text.strip())[:60], "CBLT-MSG", origin)
    if m.group("contain"):
        w.b(f"MOVE {m.group('cval').strip()} TO CBLT-EXP", origin)
        w.b(f"MOVE {subj} TO CBLT-ACT", origin)
        w.b('CALL "CBLTCT" USING CBLT-CTX', origin)
    elif m.group("numeric"):
        w.b(f"MOVE {m.group('nval').strip()} TO CBLT-EXP-NUM", origin)
        w.b(f"MOVE {subj} TO CBLT-ACT-NUM", origin)
        w.b('CALL "CBLTEQN" USING CBLT-CTX', origin)
    elif m.group("gt") or m.group("lt"):
        val = (m.group("gval") or m.group("lval")).strip()
        w.b(f"COMPUTE CBLT-EXP-NUM = {val}", origin)
        w.b(f"MOVE {subj} TO CBLT-ACT-NUM", origin)
        prog = "CBLTGT" if m.group("gt") else "CBLTLT"
        w.b(f'CALL "{prog}" USING CBLT-CTX', origin)
    elif m.group("between"):
        w.b(f"COMPUTE CBLT-EXP-NUM = {m.group('b1').strip()}", origin)
        w.b(f"COMPUTE CBLT-EXP-NUM2 = {m.group('b2').strip()}", origin)
        w.b(f"MOVE {subj} TO CBLT-ACT-NUM", origin)
        w.b('CALL "CBLTBT" USING CBLT-CTX', origin)
    elif m.group("bool"):
        want = m.group("bool").upper()
        w.b(f"IF {subj}", origin)
        w.b('MOVE "TRUE" TO CBLT-ACT', origin, 4)
        w.b("ELSE", origin)
        w.b('MOVE "FALSE" TO CBLT-ACT', origin, 4)
        w.b("END-IF", origin)
        w.b(f'MOVE "{want}" TO CBLT-EXP', origin)
        w.b(f'CALL "{"CBLTNE" if neg else "CBLTEQ"}" USING CBLT-CTX', origin)
    elif fig:
        if fig.startswith("SPACE"):
            w.b("MOVE SPACES TO CBLT-EXP", origin)
            w.b(f"MOVE {subj} TO CBLT-ACT", origin)
            w.b(f'CALL "{"CBLTNE" if neg else "CBLTEQ"}" USING CBLT-CTX', origin)
        else:
            w.b("MOVE ZERO TO CBLT-EXP-NUM", origin)
            w.b(f"MOVE {subj} TO CBLT-ACT-NUM", origin)
            w.b('CALL "CBLTEQN" USING CBLT-CTX', origin)
    else:
        val = m.group("val").strip()
        w.b(f"MOVE {val} TO CBLT-EXP", origin)
        w.b(f"MOVE {subj} TO CBLT-ACT", origin)
        w.b(f'CALL "{"CBLTNE" if neg else "CBLTEQ"}" USING CBLT-CTX', origin)


def gen_suite(s):
    w = CobolWriter()
    f = s.file
    w.a("IDENTIFICATION DIVISION.")
    w.a(f"PROGRAM-ID. {s.id}.")
    w.comment(f"GENERATED BY CBLT from {os.path.basename(f)}. DO NOT EDIT.")
    w.a("DATA DIVISION.")
    w.a("WORKING-STORAGE SECTION.")
    w.a("01  CBLT-CASE-NAME            PIC X(60).")
    w.a("01  CBLT-CASE-STAT            PIC X.")
    for n, _, text in s.ws:
        w.raw(text, (f, n))
    w.a("LINKAGE SECTION.")
    w.a("01  CBLT-CTX.")
    w.b("COPY CBLTCTX.")
    w.a("PROCEDURE DIVISION USING CBLT-CTX.")
    w.a("CBLT-MAIN.")
    for i, _ in enumerate(s.cases, 1):
        w.b(f"PERFORM CBLT-CASE-{i}")
    w.b("EXIT PROGRAM.")
    w.a("CBLT-BEFORE.")
    for n, _, text in s.before:
        w.raw(text, (f, n))
    w.b("CONTINUE.")
    w.a("CBLT-AFTER.")
    for n, _, text in s.after:
        w.raw(text, (f, n))
    w.b("CONTINUE.")
    for i, c in enumerate(s.cases, 1):
        o = (f, c.line)
        c.kind, c.reasons = "interface", []     # external mode: always through CALL
        w.a(f"CBLT-CASE-{i}.")
        w.move_literal(c.name, "CBLT-CASE-NAME", o)
        w.b(f'MOVE "{"I" if c.ignored else "C"}" TO CBLT-CASE-STAT', o)
        w.b('CALL "CBLTCAS" USING CBLT-CTX CBLT-CASE-NAME', o)
        w.b("CBLT-CASE-STAT", o, 16)
        w.b('DISPLAY "CBLT-C|" CBLT-CASE-NAME', o)
        if not c.ignored:
            w.b("PERFORM CBLT-BEFORE", o)
            for n, kind, text in c.stmts:
                if kind == "EXPECT":
                    gen_expect(w, (f, n), text)
                else:
                    w.raw(text, (f, n))
            w.b("PERFORM CBLT-AFTER", o)
        w.b("CONTINUE.")
    w.a(f"END PROGRAM {s.id}.")
    return w
