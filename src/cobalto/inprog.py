#!/usr/bin/env python3
"""inprog - in-program mode of Cobalto (CBLT).

Generates a copy of the program under test with the tests injected:

  - PROGRAM-ID renamed to the suite id (the original is still compiled
    separately for the suites that do not use in-program mode)
  - the LINKAGE items of the original move to WORKING-STORAGE, so the
    tests can set them; the only LINKAGE is CBLT-CTX
  - at the start of PROCEDURE DIVISION go CBLT-MAIN (which runs the
    cases and does EXIT PROGRAM without touching the original flow),
    CBLT-RESET, CBLT-BEFORE, CBLT-AFTER and one paragraph per case
  - each mockable point (paragraph, CALL, file statement, EXEC SQL,
    ACCEPT FROM DATE/TIME) is rewritten as
        ADD 1 TO CBLT-HIT(c)
        EVALUATE CBLT-MODE(m)
            WHEN v  <mock v>
            WHEN OTHER <original statement>
        END-EVALUATE
    with one mode per target, which each case sets and CBLT-RESET
    clears, and one counter per target and operation for VERIFY.

The body of a mocked paragraph goes into the WHEN OTHER without its
periods; the statements that relied on the period to close get their
END-xxx added. Everything else in the program is copied line by line
as is, with the source map for compilation errors.

Portable coverage: if the generator receives a coverage.Plan, it
merges its inserts (ADD 1 TO CBLT-COV-HIT(n) before each statement and
the CALL to the collector before each EXIT PROGRAM / GOBACK) into every
rewrite, adds the counter table to WORKING-STORAGE and flushes before
the EXIT PROGRAM of CBLT-MAIN. generate_coverage_copy() does the same
on a program without a suite (external mode): the copy keeps the
original PROGRAM-ID and LINKAGE.
"""
import os
import re

from . import coverage as covmod
from .cobolgen import CobolWriter
from .cobparse import Program, ParseError, VERBS
from .dsl import DslError, gen_expect
from .messages import CobaltoError, warn

FILE_OPS = ("READ", "WRITE", "REWRITE", "DELETE", "START", "OPEN", "CLOSE")
CLOCK_KINDS = ("DATE", "DATE YYYYMMDD", "DAY", "DAY YYYYDDD", "DAY-OF-WEEK", "TIME")


class Target:
    def __init__(self, key):
        self.key = key              # ("PARAGRAPH", N) ("CALL", N) ("FILE", N) ("SQL", txt) ("CLOCK", "")
        self.mocks = []             # declared mocks, in order (variant = position + 1)
        self.mode = None            # index into CBLT-MODE if there are mocks
        self.counters = {}          # op -> index into CBLT-HIT ("" for paragraph/CALL/SQL/CLOCK)
        self.sites = []

    @property
    def kind(self):
        return self.key[0]

    @property
    def name(self):
        return self.key[1]


class Site:
    def __init__(self, target, stmt, op, details):
        self.target, self.stmt, self.op, self.details = target, stmt, op, details


class InProgramError(CobaltoError):
    """An error found while rewriting a program for in-program mode or for
    coverage."""


def target_key(kind, name):
    kind = kind.upper()
    if kind == "PARAGRAPH":
        return ("PARAGRAPH", name.upper())
    if kind == "CALL":
        return ("CALL", name.strip("'\"").upper())
    if kind == "FILE" or kind in FILE_OPS:
        return ("FILE", name.upper())
    if kind == "SQL":
        return ("SQL", re.sub(r"\s+", " ", (name or "").strip("'\"")).upper())
    if kind == "STOP":
        return ("STOP", "")
    return ("CLOCK", "")


def counter_op(kind):
    return "" if kind in ("PARAGRAPH", "CALL", "SQL", "CLOCK", "STOP") else None


def is_stop(p, st):
    """STOP RUN, GOBACK or EXIT PROGRAM: in the in-program copy they end
    the case, not the process (part of interface testing)."""
    if st.verb == "GOBACK":
        return True
    if st.verb == "STOP":
        return p.up(st.start + 1) == "RUN"
    return st.verb == "EXIT" and p.up(st.start + 1) == "PROGRAM"


def entry_name(p):
    """Paragraph or section where the original flow enters; it is what
    RUN executes and what the classification considers 'the entry'."""
    T = p.tokens
    b = p.body_begin
    if b is None or p.procedure_end is None or b >= p.procedure_end:
        return None
    starts_with_header = (T[b].kind in ("word", "num") and (p.up(b + 1) == "." or p.up(b + 1) == "SECTION")
                          and p.up(b) not in VERBS)
    if starts_with_header:
        return T[b].up
    return "CBLT-ORIGINAL" if p.has_sections else "CBLT-ORIGINAL-MAIN"


def words_of(text):
    """COBOL words of a line, without literals, in uppercase."""
    text = re.sub(r"""'(?:[^']|'')*'|"(?:[^"]|"")*\"""", " ", text)
    return [w.upper() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", text)]


def classify_cases(suite, prog, entry):
    """What each case looks at. "interface" if it only touches the boundary of
    the program (LINKAGE, file records, CALL, clock, STOP, its own fields);
    "internal" if it executes a paragraph that is not the entry, mocks a
    paragraph, counts a paragraph, or uses a field of the program's
    WORKING-STORAGE outside a MOCK. BEFORE-EACH and AFTER-EACH do not count.
    Sets on each case c.kind and c.reasons: up to four
    {"construct", "line"} that make it internal."""
    ws = {it.name.upper() for it in prog.data_items if it.section == "WORKING-STORAGE"}
    ws -= {it.name.upper() for it in prog.data_items if it.section != "WORKING-STORAGE"}
    paras = {pg.name for pg in prog.paragraphs}
    for c in suite.cases:
        reasons = []

        def because(construct, line):
            reasons.append({"construct": construct, "line": line})

        for n, kind, text in c.stmts:
            if kind == "MOCK":
                if text.kind == "PARAGRAPH":
                    because(f"MOCK PARAGRAPH {text.name}", n)
            elif kind == "VERIFY":
                if text.kind.upper() == "PARAGRAPH":
                    because(f"VERIFY PARAGRAPH {text.name}", n)
            elif kind == "RUN":
                continue
            else:
                words = words_of(text)
                if kind == "COBOL":
                    for i, w in enumerate(words):
                        if w == "PERFORM" and i + 1 < len(words) and words[i + 1] in paras \
                                and words[i + 1] != entry:
                            because(f"PERFORM {words[i + 1]}", n)
                        elif w == "THRU" and i + 1 < len(words) and words[i + 1] in paras:
                            because(f"PERFORM THRU {words[i + 1]}", n)
                hit = [w for w in words if w in ws]
                if hit:
                    because(f"{'EXPECT' if kind == 'EXPECT' else words[0] if words else '?'} {hit[0]}", n)
        c.kind = "internal" if reasons else "interface"
        c.reasons = reasons[:4]


# ---------------------------------------------------------------- generator
class Generator:
    def __init__(self, suite, prog):
        self.s, self.p = suite, prog
        self.w = CobolWriter(limit=72 if prog.fmt == "fixed" else 250)
        self.targets = {}
        self.sites_by_start = {}
        self.mocked_ranges = []     # (start, end) of statements rewritten with EVALUATE
        self.para_sites = {}        # header token idx -> Target
        self.nmodes = self.ncounters = 0
        self.last_line = 0
        self.cov = None             # coverage.Plan (portable coverage) or None
        self.guard_open = {}        # token idx -> ["IF CBLT-NOT-STOPPED"]: statements that follow a STOP
        self.guard_close = {}       # token idx (the period or the next statement) -> ["END-IF"]
        self.entry = None           # name of the entry paragraph or section of the original flow

    # ------------------------------------------------------ targets
    def target(self, key):
        if key not in self.targets:
            self.targets[key] = Target(key)
        return self.targets[key]

    def collect(self):
        s, p = self.s, self.p
        for m in s.mocks:
            t = self.target(target_key(m.kind, m.name))
            t.mocks.append(m)
            m.variant = len(t.mocks)
            m.target = t
        for v in s.verifies:
            t = self.target(target_key(v.kind, v.name))
            v.target = t
            v.op = "" if t.kind in ("PARAGRAPH", "CALL", "SQL", "CLOCK", "STOP") else v.kind.upper()
        # STOP RUN / GOBACK / EXIT PROGRAM of the original flow: always
        # rewritten (they end the case), whether or not there is a VERIFY STOP
        stops = [st for st in p.statements if p.body_begin is not None
                 and p.body_begin <= st.start < p.procedure_end and is_stop(p, st)]
        if stops:
            self.target(("STOP", ""))
        # sites per target
        for t in self.targets.values():
            if t.kind == "PARAGRAPH":
                para = p.paragraph(t.name)
                if para is None or para.is_section:
                    raise InProgramError("E401", name=t.name, program=p.program_id)
                for st in p.statements_in(para.body_start, para.body_end):
                    if st.verb == "NEXT" or any(p.up(j) == "NEXT" and p.up(j + 1) == "SENTENCE"
                                                for j in range(st.start, st.end)):
                        if t.mocks:
                            raise InProgramError("E405", name=t.name, program=p.program_id)
                t.sites.append(Site(t, para, "", {}))
                self.para_sites[para.header] = t
            elif t.kind == "CALL":
                for st in p.statements:
                    if st.verb == "CALL":
                        txt, lit = p.call_target(st)
                        if txt.strip("'\"").upper() == t.name:
                            t.sites.append(Site(t, st, "", {"literal": lit}))
                if not t.sites:
                    raise InProgramError("E402", name=t.name, program=p.program_id)
            elif t.kind == "FILE":
                if t.name not in p.files:
                    raise InProgramError("E403", name=t.name, program=p.program_id)
                for st, f, op, det in p.file_sites():
                    if op in ("OPEN", "CLOSE"):
                        if any(fn == t.name for _, fn in det["items"]):
                            t.sites.append(Site(t, st, op, det))
                    elif f == t.name:
                        t.sites.append(Site(t, st, op, det))
            elif t.kind == "SQL":
                want = re.sub(r"\s+", "", t.name)
                for st, text in p.sql_sites():
                    if not want or want in re.sub(r"\s+", "", text).upper():
                        t.sites.append(Site(t, st, "", {"text": text}))
                if not t.sites:
                    warn("W304", kind="EXEC SQL", program=p.program_id)
            elif t.kind == "CLOCK":
                for st, kind, tgt in p.clock_sites():
                    t.sites.append(Site(t, st, kind, {"target": tgt}))
                if not t.sites:
                    warn("W304", kind="ACCEPT FROM DATE/TIME/DAY", program=p.program_id)
            elif t.kind == "STOP":
                for st in stops:
                    t.sites.append(Site(t, st, "", {}))
                if not t.sites:
                    warn("W304", kind="STOP RUN / GOBACK / EXIT PROGRAM", program=p.program_id)
        self.collect_guards(stops)
        # modes and counters
        for t in self.targets.values():
            if t.mocks:
                self.nmodes += 1
                t.mode = self.nmodes
            ops = {s.op for s in t.sites} if t.kind == "FILE" else {""}
            for v in self.s.verifies:
                if v.target is t and v.op not in ops:
                    raise InProgramError("E403", name=f"{v.kind} {t.name}", program=p.program_id)
            for op in sorted(ops):
                self.ncounters += 1
                t.counters[op] = self.ncounters
            for site in t.sites:
                if t.kind != "PARAGRAPH":
                    self.sites_by_start.setdefault(site.stmt.start, []).append(site)
                    if t.mocks:
                        self.mocked_ranges.append((site.stmt.start, site.stmt.end))

    def collect_guards(self, stops):
        """After a rewritten STOP, the top-level statements that follow
        in the same paragraph run only if it did not stop:
        IF CBLT-NOT-STOPPED ... END-IF. What follows in the paragraphs
        that did the PERFORM is not guarded (documented limit)."""
        p = self.p
        for para in p.paragraphs:
            inside = [st for st in stops if para.body_start <= st.start < para.body_end]
            if not inside:
                continue
            top, last_end = [], -1
            for st in sorted(p.statements_in(para.body_start, para.body_end), key=lambda s: s.start):
                if st.start >= last_end:
                    top.append(st)
                    last_end = st.end
            first_stop = min(st.start for st in inside)
            holder = next((st for st in top if st.start <= first_stop < st.end), None)
            if holder is None:
                continue
            for st in top:
                if st.start >= holder.end:
                    self.guard_open.setdefault(st.start, []).append("IF CBLT-NOT-STOPPED")
                    self.guard_close.setdefault(st.end, []).append("END-IF")

    def entry_name(self):
        return entry_name(self.p)

    # ------------------------------------------------------ utilities
    def origin(self, no):
        return self.p.origin_of_line(no)

    def emit_line(self, no):
        ln = self.p.line_by_no[no]
        text = ln.text
        if self.p.fmt == "fixed" and len(text) > 72:
            text = text[:72].rstrip()
        self.w.raw(text, ln.origin)

    def emit_noncode(self, upto):
        for no in range(self.last_line + 1, upto):
            ln = self.p.line_by_no.get(no)
            if ln is not None and ln.kind in ("comment", "blank", "directive"):
                self.emit_line(no)
        self.last_line = max(self.last_line, upto - 1)

    def indent_of(self, tok, mid=False):
        col = tok.col
        first = self.p.first_tok_of_line.get(tok.line)
        if first is not None:
            col = self.p.tokens[first].col
        if self.p.fmt == "fixed":
            col = max(col, 8)
        return " " * (col - 1 + (4 if mid else 0))

    @staticmethod
    def glue(pieces):
        """Glues parentheses and colons to their neighbors so that
        splitting by token does not leave 'X( 1 : 2 )' or ': HOST-VAR'."""
        out = []
        glue_next = False
        for pc in pieces:
            if out and (pc in (")", ":") or glue_next):
                out[-1] += pc
            else:
                out.append(pc)
            glue_next = pc in ("(", ":")
        return out

    def emit_pieces(self, indent, pieces, origin):
        limit = self.w.limit
        cont = indent + "    "
        line = indent
        for pc in self.glue(pieces):
            sep = "" if line in (indent, cont) else " "
            if len(line) + len(sep) + len(pc) <= limit:
                line += sep + pc
                continue
            if line not in (indent, cont):
                self.w.raw(line, origin)
            line = cont
            if len(line) + len(pc) <= limit:
                line += pc
                continue
            if pc[0] in "\"'" or (len(pc) > 1 and pc[1] in "\"'"):
                q = pc[0] if pc[0] in "\"'" else pc[1]
                room = limit - len(line)
                chunk = pc[:room]
                if chunk.endswith(q) and len(pc) > room and pc[room] == q:
                    chunk = chunk[:-1]
                self.w.raw(line + chunk, origin)
                rest = pc[len(chunk):]
                while rest:
                    pre = "      -    " + q
                    room = limit - len(pre)
                    chunk = rest[:room]
                    if chunk.endswith(q) and len(rest) > room and rest[room] == q:
                        chunk = chunk[:-1]
                    rest = rest[len(chunk):]
                    self.w.raw(pre + chunk, origin)
                line = cont
                continue
            raise DslError(origin[1] if origin else "?", f"does not fit in {limit} columns: {pc[:40]}...")
        if line not in (indent, cont):
            self.w.raw(line, origin)

    def emit_fragment(self, indent, k, m, drop_periods, origin):
        """Re-emits the tokens [k, m) of a single line keeping the original
        spacing (it matters in EXEC SQL, :HOST-VAR, X(1:2)). If it does not
        fit in the width, falls back to emit_pieces, which splits by token."""
        T = self.p.tokens
        ln = self.p.line_by_no[T[k].line]
        if all(T[x].end_line == T[x].line for x in range(k, m)):
            out, prev = "", None
            for x in range(k, m):
                if prev is not None:
                    out += ln.text[prev:T[x].col - 1]
                out += "" if (drop_periods and T[x].up == ".") else T[x].text
                prev = T[x].end_col
            out = out.strip()
            if not out:
                return
            base = indent if len(indent) < 11 else indent[:11]
            for ind in (indent, self.indent_of(T[k]), base):
                if len(ind) + len(out) <= self.w.limit:
                    self.w.raw(ind + out, origin)
                    return
        pieces = [T[x].text for x in range(k, m) if not (drop_periods and T[x].up == ".")]
        if pieces:
            self.emit_pieces(indent, pieces, origin)

    def terminator_inserts(self, start, end):
        """idx -> [END-xxx] to insert before that token, for the
        statements of [start, end) that rely on the period. Those that
        live inside a mocked statement are skipped (its WHEN OTHER
        rewrites them on its own), except [start, end) itself."""
        ins = {}
        inner = [(a, b) for a, b in self.mocked_ranges if start <= a and b <= end and (a, b) != (start, end)]
        for st in sorted(self.p.statements_in(start, end), key=lambda s: -s.start):
            if any(a <= st.start and st.end <= b for a, b in inner):
                continue
            if st.needs_terminator():
                ins.setdefault(st.end, []).append(st.terminator())
        return ins

    def merge_inserts(self, inserts, i, j, skip):
        """Terminators requested by the caller + STOP guards + coverage
        counters of the range [i, j), in that order at each index (the
        END-IF of a statement goes before the IF and the counter of the
        next one). At skip (the original statement inside its own WHEN
        OTHER) the guard and the counter were already emitted before the
        EVALUATE."""
        out = {k: list(v) for k, v in (inserts or {}).items()}
        for src in (self.guard_close, self.guard_open, self.cov.inserts if self.cov is not None else {}):
            for k, v in src.items():
                if i <= k < j and k != skip:
                    out.setdefault(k, []).extend(v)
        return out

    # ------------------------------------------------------ rewriting
    def emit_range(self, i, j, drop_periods=False, inserts=None, indent=0, skip=None):
        """Copies the tokens [i, j), rewriting mocked paragraphs and
        statements. skip: index of a site that must not be rewritten (the
        original statement inside its own WHEN OTHER)."""
        T = self.p.tokens
        inserts = self.merge_inserts(inserts, i, j, skip)
        k = i
        while k < j:
            t = T[k]
            self.emit_noncode(t.line)
            if k in inserts:
                for txt in inserts[k]:
                    self.w.b(txt, self.origin(t.line), indent)
                if t.up == "." and not drop_periods:
                    # the period of the statement also closes what was inserted (guard END-IF)
                    self.w.lines[-1] += "."
                    k += 1
                    self.last_line = t.end_line
                    continue
            tgt = self.para_sites.get(k)
            if tgt is not None:
                para = tgt.sites[0].stmt
                if para.body_end <= j:
                    self.emit_para(tgt, para, indent)
                    k = para.body_end
                    self.last_line = T[k - 1].end_line
                    continue
            sites = self.sites_by_start.get(k) if k != skip else None
            if sites and sites[0].stmt.end <= j:
                self.emit_site(sites, indent)
                k = sites[0].stmt.end
                if k < j and k in inserts and T[k].up == ".":
                    # guards that close on the period of the rewritten statement
                    for txt in inserts.pop(k):
                        self.w.b(txt, self.origin(T[k].line), indent)
                if k < j and T[k].up == ".":
                    if not drop_periods:
                        self.w.lines[-1] += "."
                    k += 1
                self.last_line = T[k - 1].end_line
                continue
            first = self.p.first_tok_of_line.get(t.line)
            m, L = k, t.line
            while m < j and T[m].line <= L:
                if m > k and ((m in self.sites_by_start and m != skip) or m in self.para_sites or m in inserts):
                    break
                L = max(L, T[m].end_line)
                m += 1
            whole = m >= len(T) or T[m].line > L
            has_period = any(T[x].up == "." for x in range(k, m))
            if first == k and whole and indent == 0 and not (drop_periods and has_period):
                for no in range(t.line, L + 1):
                    self.emit_line(no)
            elif m > k:
                self.emit_fragment(self.indent_of(t, mid=(first != k)) + " " * indent, k, m,
                                   drop_periods, self.origin(t.line))
            k = m
            self.last_line = L

    def emit_para(self, tgt, para, indent):
        p, w = self.p, self.w
        o = self.origin(para.line)
        w.a(f"{para.name}.", o)
        c = tgt.counters[""]
        w.b(f"ADD 1 TO CBLT-HIT({c})", o)
        self.last_line = p.tokens[para.header + 1].end_line
        if not tgt.mocks:
            # VERIFY only: count and leave the body as is
            w.lines[-1] += "."
            self.emit_range(para.body_start, para.body_end)
            return
        w.b(f"EVALUATE CBLT-MODE({tgt.mode})", o)
        for m in tgt.mocks:
            w.b(f"WHEN {m.variant}", o)
            self.emit_dsl_body(m.body, m.line, 4)
        w.b("WHEN OTHER", o)
        stmts = p.statements_in(para.body_start, para.body_end)
        if not stmts or (len(stmts) == 1 and stmts[0].verb == "EXIT" and stmts[0].end - stmts[0].start == 1):
            w.b("CONTINUE", o, 4)
        else:
            self.emit_range(para.body_start, para.body_end, drop_periods=True,
                            inserts=self.terminator_inserts(para.body_start, para.body_end), indent=4)
        w.b("END-EVALUATE.", o)

    def emit_dsl_body(self, body, line, indent):
        """COBOL/EXPECT lines of a MOCK, without periods (they go inside
        an EVALUATE)."""
        f = self.s.file
        if not body:
            self.w.b("CONTINUE", (f, line), indent)
            return
        for n, kind, text in body:
            if kind == "EXPECT":
                gen_expect(self.w, (f, n), text)
            else:
                t = text.rstrip()
                if t.endswith(".") and t.count('"') % 2 == 0 and t.count("'") % 2 == 0:
                    t = t[:-1]
                self.w.raw(t, (f, n))

    def phrase_body(self, st, names):
        """Range (start, end) of the body of the first phrase with that name."""
        for name, _, b0, b1 in st.phrases:
            if name in names:
                return b0, b1
        return None

    def emit_phrase_body(self, st, names, indent):
        rng = self.phrase_body(st, names)
        if rng and rng[1] > rng[0]:
            self.emit_range(rng[0], rng[1], drop_periods=True,
                            inserts=self.terminator_inserts(rng[0], rng[1]), indent=indent)
            return True
        return False

    def emit_original(self, st, indent):
        """The original statement inside its WHEN OTHER: without the
        period and with the END-xxx it was missing."""
        ins = self.terminator_inserts(st.start, st.end)
        self.emit_range(st.start, st.end, drop_periods=True, inserts=ins, indent=indent, skip=st.start)
        if st.end in ins:
            for txt in ins[st.end]:
                self.w.b(txt, self.origin(st.end_line), indent)

    def emit_site(self, sites, indent):
        p, w = self.p, self.w
        st = sites[0].stmt
        o = self.origin(st.line)
        if st.verb in ("OPEN", "CLOSE"):
            self.emit_open_close(sites, st, indent)
            return
        site = sites[0]
        tgt = site.target
        c = tgt.counters[site.op if tgt.kind == "FILE" else ""]
        w.b(f"ADD 1 TO CBLT-HIT({c})", o, indent)
        if tgt.kind == "STOP":
            # STOP RUN / GOBACK / EXIT PROGRAM of the original: ends the case, not the process
            w.b("SET CBLT-STOPPED TO TRUE", o, indent)
            return
        if not tgt.mocks:
            # VERIFY only: count and copy the statement as is
            self.emit_range(st.start, st.end, indent=indent, skip=st.start)
            return
        w.b(f"EVALUATE CBLT-MODE({tgt.mode})", o, indent)
        for m in tgt.mocks:
            if tgt.kind == "CLOCK" and site.op not in m.clock:
                continue
            w.b(f"WHEN {m.variant}", o, indent)
            self.emit_variant(m, site, st, c, indent + 4)
        w.b("WHEN OTHER", o, indent)
        self.emit_original(st, indent + 4)
        w.b("END-EVALUATE", o, indent)

    def emit_variant(self, m, site, st, counter, ind):
        p, w = self.p, self.w
        tgt = site.target
        o = (self.s.file, m.line)
        kind = tgt.kind
        if kind == "CALL":
            w.b(f"MOVE CBLT-HIT({counter}) TO CBLT-CALL-COUNT", o, ind)
            self.emit_dsl_body(m.body, m.line, ind)
            self.emit_phrase_body(st, ("NOT ON EXCEPTION", "NOT ON OVERFLOW"), ind)
            return
        if kind == "SQL":
            self.emit_dsl_body(m.body, m.line, ind)
            return
        if kind == "CLOCK":
            w.b(f"MOVE {m.clock[site.op]} TO {site.details['target']}", o, ind)
            return
        # FILE
        info = p.files[tgt.name]
        status = info["status"]
        op = site.op
        body = m.ops.get(op)

        def set_status(val, extra=0):
            if status:
                w.b(f'MOVE "{val}" TO {status}', o, ind + extra)

        if op == "READ":
            rec = info["records"][0] if info["records"] else None
            w.b(f"MOVE CBLT-HIT({counter}) TO CBLT-READ-COUNT", o, ind)
            w.b("SET CBLT-NOT-AT-END TO TRUE", o, ind)
            if body is None:
                w.b("SET CBLT-AT-END TO TRUE", o, ind)
            else:
                self.emit_dsl_body(body, m.line, ind)
            w.b("IF CBLT-AT-END", o, ind)
            uses_invalid = self.phrase_body(st, ("INVALID KEY",)) is not None
            set_status("23" if uses_invalid else "10", 4)
            # a branch with no statements does not compile: without FILE STATUS and
            # without the matching phrase in the original READ, the branch gets CONTINUE
            done = self.emit_phrase_body(st, ("AT END", "INVALID KEY"), ind + 4)
            if not status and not done:
                w.b("CONTINUE", o, ind + 4)
            w.b("ELSE", o, ind)
            set_status("00", 4)
            into = bool(site.details.get("into") and rec)
            if into:
                w.b(f"MOVE {rec} TO {site.details['into']}", o, ind + 4)
            done = self.emit_phrase_body(st, ("NOT AT END", "NOT INVALID KEY"), ind + 4)
            if not status and not into and not done:
                w.b("CONTINUE", o, ind + 4)
            w.b("END-IF", o, ind)
            return
        if op in ("WRITE", "REWRITE"):
            if site.details.get("from"):
                w.b(f"MOVE {site.details['from']} TO {site.details['record']}", o, ind)
            w.b(f"MOVE CBLT-HIT({counter}) TO CBLT-WRITE-COUNT", o, ind)
            set_status("00")
            if body:
                self.emit_dsl_body(body, m.line, ind)
            self.emit_phrase_body(st, ("NOT INVALID KEY", "NOT AT EOP"), ind)
            if not status and not body and not self.phrase_body(st, ("NOT INVALID KEY", "NOT AT EOP")) \
                    and not site.details.get("from"):
                w.b("CONTINUE", o, ind)
            return
        # DELETE / START
        set_status("00")
        if body:
            self.emit_dsl_body(body, m.line, ind)
        done = self.emit_phrase_body(st, ("NOT INVALID KEY",), ind)
        if not status and not body and not done:
            w.b("CONTINUE", o, ind)

    def emit_open_close(self, sites, st, indent):
        p, w = self.p, self.w
        o = self.origin(st.line)
        verb = st.verb
        by_file = {s.target.name: s for s in sites}
        for mode, fname in sites[0].details["items"]:
            plain = f"OPEN {mode} {fname}" if verb == "OPEN" else f"CLOSE {fname}"
            site = by_file.get(fname)
            if site is None:
                w.b(plain, o, indent)
                continue
            tgt = site.target
            c = tgt.counters[verb]
            w.b(f"ADD 1 TO CBLT-HIT({c})", o, indent)
            if not tgt.mocks:
                w.b(plain, o, indent)
                continue
            status = p.files[fname]["status"]
            w.b(f"EVALUATE CBLT-MODE({tgt.mode})", o, indent)
            for m in tgt.mocks:
                w.b(f"WHEN {m.variant}", o, indent)
                if status:
                    w.b(f'MOVE "00" TO {status}', (self.s.file, m.line), indent + 4)
                body = m.ops.get(verb)
                if body:
                    self.emit_dsl_body(body, m.line, indent + 4)
                elif not status:
                    w.b("CONTINUE", (self.s.file, m.line), indent + 4)
            w.b("WHEN OTHER", o, indent)
            w.b(plain, o, indent + 4)
            w.b("END-EVALUATE", o, indent)

    # ------------------------------------------------------ tests
    def emit_mock_activation(self, m, origin):
        self.w.b(f"MOVE {m.variant} TO CBLT-MODE({m.target.mode})", origin)

    def emit_verify(self, v, origin, text):
        w = self.w
        t = v.target
        c = t.counters[v.op]
        w.move_literal(("VERIFY " + text.strip())[:60], "CBLT-MSG", origin)
        n = v.count
        if v.mode == "exact":
            w.b(f"MOVE {n} TO CBLT-EXP-NUM", origin)
            w.b(f"MOVE CBLT-HIT({c}) TO CBLT-ACT-NUM", origin)
            w.b('CALL "CBLTEQN" USING CBLT-CTX', origin)
        elif v.mode == "atleast":
            w.b(f"COMPUTE CBLT-EXP-NUM = {n} - 1", origin)
            w.b(f"MOVE CBLT-HIT({c}) TO CBLT-ACT-NUM", origin)
            w.b('CALL "CBLTGT" USING CBLT-CTX', origin)
        else:
            w.b(f"COMPUTE CBLT-EXP-NUM = {n} + 1", origin)
            w.b(f"MOVE CBLT-HIT({c}) TO CBLT-ACT-NUM", origin)
            w.b('CALL "CBLTLT" USING CBLT-CTX', origin)

    def emit_run(self, text, origin):
        """RUN [USING a b c]: executes the original flow through its entry.
        The arguments are moved to the PROCEDURE DIVISION USING items
        (which live in WORKING-STORAGE in the copy) by position, and on
        return they are copied back to those that are fields (CALL BY
        REFERENCE semantics); a literal or figurative constant only goes in."""
        p, w = self.p, self.w
        if self.entry is None:
            raise DslError(origin[1], "RUN: the program has no PROCEDURE DIVISION with a body")
        args = text.split()
        if args and args[0].upper() == "USING":
            args = args[1:]
        params = [p.tokens[j].text for j in p.procedure_using]
        if len(args) != len(params):
            raise DslError(origin[1], f"RUN USING: the program takes {len(params)} parameter(s) "
                                               f"({' '.join(params) or 'none'}) and {len(args)} were passed")
        back = []
        for arg, prm in zip(args, params):
            w.b(f"MOVE {arg} TO {prm}", origin)
            u = arg.upper()
            if not (arg[0] in "'\"" or re.match(r"^[+-]?\d", arg) or u in
                    ("ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES", "LOW-VALUE", "LOW-VALUES",
                     "HIGH-VALUE", "HIGH-VALUES", "QUOTE", "QUOTES", "NULL")):
                back.append((arg, prm))
        w.b(f"PERFORM {self.entry}", origin)
        for arg, prm in back:
            w.b(f"MOVE {prm} TO {arg}", origin)

    def emit_stmts(self, items):
        f = self.s.file
        for n, kind, text in items:
            if kind == "EXPECT":
                gen_expect(self.w, (f, n), text)
            elif kind == "MOCK":
                self.emit_mock_activation(text, (f, n))
            elif kind == "VERIFY":
                self.emit_verify(text, (f, n), text.text)
            elif kind == "RUN":
                self.emit_run(text, (f, n))
            else:
                self.w.raw(text, (f, n))

    def emit_tests(self):
        s, w = self.s, self.w
        f = s.file
        if self.p.has_sections:
            w.a("CBLT-TESTS SECTION.")
        # The cases are not executed with PERFORM but dispatched with GO TO:
        # if the original flow falls off the end of the program inside a
        # case (a GO TO out of the executed paragraph), CBLT-FELL-OFF
        # records the break as a failure and dispatches the next case,
        # which would not be possible with a pending PERFORM.
        w.a("CBLT-MAIN.")
        w.b("MOVE 1 TO CBLT-CASE-NR.")
        w.a("CBLT-DISPATCH.")
        self.emit_dispatch()
        w.a("CBLT-DONE.")
        if self.cov is not None:
            self.cov.emit_flush(w)
        w.b("EXIT PROGRAM.")
        w.a("CBLT-RESET.")
        w.b(f"PERFORM VARYING CBLT-I FROM 1 BY 1 UNTIL CBLT-I > {max(1, self.nmodes)}")
        w.b("MOVE ZERO TO CBLT-MODE(CBLT-I)", None, 4)
        w.b("END-PERFORM")
        w.b(f"PERFORM VARYING CBLT-I FROM 1 BY 1 UNTIL CBLT-I > {max(1, self.ncounters)}")
        w.b("MOVE ZERO TO CBLT-HIT(CBLT-I)", None, 4)
        w.b("END-PERFORM")
        w.b("MOVE ZERO TO CBLT-READ-COUNT CBLT-WRITE-COUNT CBLT-CALL-COUNT")
        w.b("SET CBLT-NOT-AT-END TO TRUE")
        w.b("SET CBLT-NOT-STOPPED TO TRUE.")
        w.a("CBLT-BEFORE.")
        self.emit_stmts(s.before)
        w.b("CONTINUE.")
        w.a("CBLT-AFTER.")
        self.emit_stmts(s.after)
        w.b("CONTINUE.")
        for i, c in enumerate(s.cases, 1):
            o = (f, c.line)
            w.a(f"CBLT-CASE-{i}.")
            w.move_literal(c.name, "CBLT-CASE-NAME", o)
            w.b(f'MOVE "{"I" if c.ignored else "C"}" TO CBLT-CASE-STAT', o)
            w.b('CALL "CBLTCAS" USING CBLT-CTX CBLT-CASE-NAME', o)
            w.b("CBLT-CASE-STAT", o, 16)
            w.b('DISPLAY "CBLT-C|" CBLT-CASE-NAME', o)
            if not c.ignored:
                w.b("PERFORM CBLT-RESET", o)
                w.b("PERFORM CBLT-BEFORE", o)
                self.emit_stmts(c.stmts)
                w.b("PERFORM CBLT-AFTER", o)
            w.b("ADD 1 TO CBLT-CASE-NR", o)
            w.b("GO TO CBLT-DISPATCH.", o)

    def emit_dispatch(self):
        """GO TO CBLT-CASE-1 ... CBLT-CASE-n CBLT-DONE DEPENDING ON
        CBLT-CASE-NR, split into lines of a few labels each."""
        w = self.w
        labels = [f"CBLT-CASE-{i}" for i in range(1, len(self.s.cases) + 1)] + ["CBLT-DONE"]
        w.b("GO TO")
        for k in range(0, len(labels), 4):
            w.b(" ".join(labels[k:k + 4]), None, 4)
        w.b("DEPENDING ON CBLT-CASE-NR.", None, 4)

    def emit_fell_off(self):
        """Last paragraph of the copy: only reached if the original flow
        fell off the end of the program during a case. Records it as a
        failed assert of the current case and goes on with the next one."""
        w = self.w
        if self.p.has_sections:
            w.a("CBLT-END SECTION.")
        w.a("CBLT-FELL-OFF.")
        w.comment("CBLT: original flow fell off the end of the program in a case")
        w.b("MOVE SPACES TO CBLT-MSG")
        w.move_literal("the case did not finish: the program fell off the end", "CBLT-MSG", None)
        w.b('MOVE "THE CASE TO FINISH" TO CBLT-EXP')
        w.b('MOVE "FELL OFF THE END OF THE PROGRAM" TO CBLT-ACT')
        w.b('CALL "CBLTEQ" USING CBLT-CTX')
        w.b("ADD 1 TO CBLT-CASE-NR")
        w.b("GO TO CBLT-DISPATCH.")

    def emit_ws_items(self):
        w = self.w
        w.comment("CBLT: control items for cases and mocks")
        w.a("01  CBLT-CASE-NAME            PIC X(60).")
        w.a("01  CBLT-CASE-STAT            PIC X.")
        w.a("01  CBLT-MOCK-CTL.")
        w.b("05  CBLT-I                PIC 9(3).")
        w.b("05  CBLT-CASE-NR          PIC 9(3).")
        w.b("05  CBLT-READ-COUNT       PIC 9(5).")
        w.b("05  CBLT-WRITE-COUNT      PIC 9(5).")
        w.b("05  CBLT-CALL-COUNT       PIC 9(5).")
        w.b('05  CBLT-AT-END-FLAG      PIC X VALUE "N".')
        w.b('88  CBLT-AT-END       VALUE "Y".', None, 4)
        w.b('88  CBLT-NOT-AT-END   VALUE "N".', None, 4)
        w.b('05  CBLT-STOP-FLAG        PIC X VALUE "N".')
        w.b('88  CBLT-STOPPED      VALUE "Y".', None, 4)
        w.b('88  CBLT-NOT-STOPPED  VALUE "N".', None, 4)
        w.b("05  CBLT-MODE-TAB.")
        w.b(f"10  CBLT-MODE         PIC 9(3) OCCURS {max(1, self.nmodes)} TIMES.", None, 4)
        w.b("05  CBLT-HIT-TAB.")
        w.b(f"10  CBLT-HIT          PIC 9(5) OCCURS {max(1, self.ncounters)} TIMES.", None, 4)
        if self.cov is not None:
            self.cov.emit_ws(w)
        if self.s.ws:
            w.comment(f"CBLT: WORKING-STORAGE of suite {os.path.basename(self.s.file)}")
            for n, _, text in self.s.ws:
                w.raw(text, (self.s.file, n))

    # ------------------------------------------------------ assembly
    def generate(self):
        p, w, s = self.p, self.w, self.s
        T = p.tokens
        self.check_program()
        self.collect()
        self.entry = self.entry_name()
        classify_cases(s, p, self.entry)

        pid_line = T[p.program_ids[0][1]].line
        proc_line = T[p.procedure_tok].line
        data_line = T[p.divisions["DATA"]].line if "DATA" in p.divisions else None
        dsecs = sorted(((i, name) for (div, name), i in p.sections.items() if div == "DATA"))
        sec_line = {name: T[i].line for i, name in dsecs}
        order = [name for _, name in dsecs]

        def next_line_after(name):
            k = order.index(name)
            return sec_line[order[k + 1]] if k + 1 < len(order) else proc_line

        # 1. identification and environment, with PROGRAM-ID renamed
        head_end = data_line if data_line else proc_line
        for no in range(1, head_end):
            ln = p.line_by_no[no]
            if no == pid_line:
                tok = T[p.program_ids[0][1]]
                text = ln.text[:tok.col - 1] + s.id + ln.text[tok.col - 1 + len(tok.text):]
                w.raw(text[:72] if p.fmt == "fixed" else text, ln.origin)
                w.comment(f"GENERATED BY CBLT from {os.path.basename(s.file)} for")
                w.comment(f"{os.path.basename(p.path)} (in-program mode). DO NOT EDIT.")
            else:
                self.emit_line(no)
        # 2. DATA DIVISION up to the end of WORKING-STORAGE
        link_range = None
        if "LINKAGE" in sec_line:
            link_range = (sec_line["LINKAGE"], next_line_after("LINKAGE"))
        if data_line is None:
            w.a("DATA DIVISION.")
            w.a("WORKING-STORAGE SECTION.")
            tail = []
        else:
            if "WORKING-STORAGE" in sec_line:
                ws_end = next_line_after("WORKING-STORAGE")
                for no in range(data_line, ws_end):
                    self.emit_line(no)
            else:
                # goes after FILE SECTION, before any other
                ins = proc_line
                for name in ("LOCAL-STORAGE", "LINKAGE", "REPORT", "SCREEN", "COMMUNICATION"):
                    if name in sec_line:
                        ins = min(ins, sec_line[name])
                for no in range(data_line, ins):
                    self.emit_line(no)
                w.a("WORKING-STORAGE SECTION.")
                ws_end = ins
            tail = [no for no in range(ws_end, proc_line)
                    if not (link_range and link_range[0] <= no < link_range[1])]
        # 3. original LINKAGE moved to WORKING-STORAGE
        if link_range:
            w.comment("CBLT: original LINKAGE SECTION, moved to WORKING-STORAGE")
            for no in range(link_range[0] + 1, link_range[1]):
                self.emit_line(no)
        # 4. CBLT items and WORKING-STORAGE of the suite
        self.emit_ws_items()
        # 5. rest of DATA DIVISION, with our LINKAGE in the right place
        split = len(tail)
        for idx, no in enumerate(tail):
            if link_range and no >= link_range[1]:
                split = idx
                break
            for name in ("REPORT", "SCREEN", "COMMUNICATION"):
                if name in sec_line and no >= sec_line[name]:
                    split = min(split, idx)
        for no in tail[:split]:
            self.emit_line(no)
        w.a("LINKAGE SECTION.")
        w.a("01  CBLT-CTX.")
        w.b("COPY CBLTCTX.")
        for no in tail[split:]:
            self.emit_line(no)
        # 6. PROCEDURE DIVISION
        w.a("PROCEDURE DIVISION USING CBLT-CTX.", self.origin(proc_line))
        self.last_line = T[p.procedure_body - 1].end_line
        if p.declaratives:
            self.emit_range(p.declaratives[0], p.declaratives[1])
        self.emit_tests()
        b = p.body_begin
        starts_with_header = b < p.procedure_end and (
            T[b].kind in ("word", "num") and (p.up(b + 1) == "." or p.up(b + 1) == "SECTION")
            and p.up(b) not in VERBS)
        if not starts_with_header and b < p.procedure_end:
            w.a("CBLT-ORIGINAL SECTION." if p.has_sections else "CBLT-ORIGINAL-MAIN.")
        self.emit_range(b, p.procedure_end)
        self.emit_noncode(T[p.procedure_end - 1].line + 1 if p.procedure_end > 0 else 1)
        self.emit_fell_off()
        w.a(f"END PROGRAM {s.id}.")
        return self.w

    def check_program(self):
        p = self.p
        if p.procedure_tok is None:
            raise InProgramError("E406", program=p.path, detail="has no PROCEDURE DIVISION")
        if not p.program_ids:
            raise InProgramError("E406", program=p.path, detail="has no PROGRAM-ID")
        if p.nested:
            raise InProgramError("E406", program=p.path, detail="has more than one program (nested or several per file)")

    def generate_coverage_copy(self):
        """External mode of portable coverage: the program as is (PROGRAM-ID
        and LINKAGE intact) with the counter table in WORKING-STORAGE, an
        ADD 1 before each statement, the CALL to the collector before each
        EXIT PROGRAM / GOBACK and, if the flow can fall off the end, a
        CBLT-COV-END paragraph that flushes before exiting."""
        p, w, plan = self.p, self.w, self.cov
        T = p.tokens
        self.check_program()
        proc_line = T[p.procedure_tok].line
        data_line = T[p.divisions["DATA"]].line if "DATA" in p.divisions else None
        dsecs = sorted(((i, name) for (div, name), i in p.sections.items() if div == "DATA"))
        sec_line = {name: T[i].line for i, name in dsecs}
        order = [name for _, name in dsecs]

        def next_line_after(name):
            k = order.index(name)
            return sec_line[order[k + 1]] if k + 1 < len(order) else proc_line

        # 1. up to the end of WORKING-STORAGE (or where it has to be created)
        if data_line is None:
            for no in range(1, proc_line):
                self.emit_line(no)
            w.a("DATA DIVISION.")
            w.a("WORKING-STORAGE SECTION.")
            plan.emit_ws(w)
        elif "WORKING-STORAGE" in sec_line:
            ws_end = next_line_after("WORKING-STORAGE")
            for no in range(1, ws_end):
                self.emit_line(no)
            plan.emit_ws(w)
            for no in range(ws_end, proc_line):
                self.emit_line(no)
        else:
            ins = proc_line
            for name in ("LOCAL-STORAGE", "LINKAGE", "REPORT", "SCREEN", "COMMUNICATION"):
                if name in sec_line:
                    ins = min(ins, sec_line[name])
            for no in range(1, ins):
                self.emit_line(no)
            w.a("WORKING-STORAGE SECTION.")
            plan.emit_ws(w)
            for no in range(ins, proc_line):
                self.emit_line(no)
        # 2. PROCEDURE DIVISION header (it can span several lines)
        hdr_end = T[p.procedure_body - 1].end_line
        for no in range(proc_line, hdr_end + 1):
            self.emit_line(no)
        self.last_line = hdr_end
        if p.declaratives:
            self.emit_range(p.declaratives[0], p.declaratives[1])
        b = p.body_begin
        starts_with_header = b < p.procedure_end and (
            T[b].kind in ("word", "num") and (p.up(b + 1) == "." or p.up(b + 1) == "SECTION")
            and p.up(b) not in VERBS)
        if not starts_with_header and b < p.procedure_end:
            w.a("CBLT-COV-MAIN SECTION." if p.has_sections else "CBLT-COV-MAIN.")
        self.emit_range(b, p.procedure_end)
        if plan.units and not plan.ends_with_exit:
            w.a("CBLT-COV-END.")
            plan.emit_flush(w)
            w.lines[-1] += "."
        # 3. END PROGRAM and whatever follows
        if p.procedure_end < len(T):
            end_line = T[p.procedure_end].line
            self.emit_noncode(end_line)
            for no in range(end_line, len(p.lines) + 1):
                self.emit_line(no)
        else:
            self.emit_noncode(len(p.lines) + 1)
        return w


def generate(suite, prog_path, copy_dirs, with_coverage=False):
    """In-program copy of the suite, instrumented for portable coverage if
    with_coverage. Returns (writer, coverage plan or None)."""
    try:
        prog = Program(prog_path, copy_dirs)
    except ParseError as e:
        raise InProgramError("E404", detail=str(e))
    g = Generator(suite, prog)
    if with_coverage:
        g.cov = covmod.Plan(prog)
    return g.generate(), g.cov


def generate_coverage(prog_path, copy_dirs):
    """Instrumented copy of the program (external mode). Returns (writer, plan)."""
    try:
        prog = Program(prog_path, copy_dirs)
    except ParseError as e:
        raise InProgramError("E404", detail=str(e))
    g = Generator(None, prog)
    g.cov = covmod.Plan(prog)
    return g.generate_coverage_copy(), g.cov
