#!/usr/bin/env python3
"""coverage - portable coverage for Cobalto (CBLT). Stdlib only.

The CLI instruments a copy of the program under test with one counter
per statement (an OCCURS table in WORKING-STORAGE and an ADD 1 before
each statement, including those nested in IF, EVALUATE, AT END, etc.).
The copy sends its counters to the library's CBLTCOV collector on every
EXIT PROGRAM / GOBACK (and when falling off the end of the PROCEDURE
DIVISION), and the driver dumps them to the results file as
C|program|index|count records. None of this depends on the compiler.

The COBOL code knows nothing about paragraph names or lines: this module
builds the index -> (paragraph, line) map while instrumenting, saves it
in build/cov/map.json and uses it to report by paragraph and to write
LCOV (build/lcov.info, for Coverage Gutters in VS Code), Cobertura XML
(build/coverage.xml, for pipelines) and the SonarQube generic coverage
format (build/sonar-coverage.xml, the only route Sonar documents for
COBOL coverage).

Branches: besides the statements, the map describes the branches of
each IF (THEN and ELSE), of each EVALUATE and SEARCH (a WHEN group, WHEN
OTHER, AT END) and of each conditional phrase (AT END / NOT AT END,
INVALID KEY, ON SIZE ERROR, ON EXCEPTION, ON OVERFLOW, AT EOP). No code
needs to be inserted per branch: the entries to an explicit branch are
those of the first statement of its body (already instrumented), and
only a body with no statement of its own (NEXT SENTENCE) gets its own
counter. The implicit branch (IF without ELSE, EVALUATE without WHEN
OTHER, READ without NOT AT END) is derived when reporting: entries to
the statement minus those of its explicit branches. This way the metric
also holds inside the statements that in-program mode rewrites with mocks.
"""
import json
import time
from xml.sax.saxutils import escape

from . import condcov
from .cobparse import VERBS
from .messages import SCHEMA, VERSION

NO_PARA = "(no paragraph)"
HIT_ITEM = "CBLT-COV-HIT"
FLUSH_LINES = ['CALL "CBLTCOV" USING CBLT-COV-OP CBLT-COV-PGM',
               '    CBLT-COV-N CBLT-COV-TAB']


class Unit:
    """An instrumented statement: index 1..n in the counter table."""
    __slots__ = ("idx", "verb", "line", "end_line", "file", "para", "start", "stmt")

    def __init__(self, idx, verb, line, end_line, file, para, start, stmt=None):
        self.idx, self.verb, self.line, self.end_line = idx, verb, line, end_line
        self.file, self.para, self.start, self.stmt = file, para, start, stmt


class Branch:
    """A branch of an instrumented statement (stmt: idx of its Unit).
    idx: counter that counts its entries, or None if it is the implicit
    branch (derived from the entries to the statement minus the explicit ones)."""
    __slots__ = ("stmt", "kind", "label", "line", "file", "para", "idx", "implicit")

    def __init__(self, stmt, kind, label, line, file, para, idx=None, implicit=False):
        self.stmt, self.kind, self.label, self.line = stmt, kind, label, line
        self.file, self.para, self.idx, self.implicit = file, para, idx, implicit


class Plan:
    """What to insert in the instrumented copy of a program."""

    def __init__(self, prog):
        self.prog = prog
        self.name = prog.program_id
        self.units = []
        self.branches = []
        self.counters = 0           # counters: statements + branches with their own counter
        self.paragraphs = []        # [(name, line, end_line, is_section)]
        self.inserts = {}           # token idx -> [COBOL lines] (before the token)
        self.ends_with_exit = False
        self.cond_names = {it.name.upper() for it in prog.data_items if str(it.level) == "88"}
        self.data_names = {it.name.upper() for it in prog.data_items if str(it.level) != "88"}
        self._build()
        self._build_branches()

    # -------------------------------------------------------- units
    def _para_of(self, st):
        for para in self.prog.paragraphs:
            if para.body_start <= st.start < para.body_end:
                return para
        return None

    def _build(self):
        p = self.prog
        body = [st for st in p.statements if p.body_begin is not None
                and p.body_begin <= st.start < p.procedure_end]
        seen = set()
        for para in p.paragraphs:
            o = p.origin_of_line(para.line)
            self.paragraphs.append((para.name, o[1], p.origin_of_line(para.end_line)[1], para.is_section))
            seen.add(para.name)
        for st in body:
            if st.verb == "EXIT" and st.end - st.start == 1:
                continue            # bare EXIT: not executable and must be alone in its paragraph
            para = self._para_of(st)
            pname = para.name if para else NO_PARA
            if pname == NO_PARA and NO_PARA not in seen:
                seen.add(NO_PARA)
                self.paragraphs.insert(0, (NO_PARA, p.origin_of_line(st.line)[1],
                                           p.origin_of_line(st.line)[1], False))
            o = p.origin_of_line(st.line)
            u = Unit(len(self.units) + 1, st.verb, o[1], p.origin_of_line(st.end_line)[1],
                     o[0], pname, st.start, st)
            self.units.append(u)
            self.inserts.setdefault(st.start, []).append(f"ADD 1 TO {HIT_ITEM}({u.idx})")
            if (st.verb == "EXIT" and p.up(st.start + 1) == "PROGRAM") or st.verb == "GOBACK":
                self.inserts[st.start].extend(FLUSH_LINES)
        self.counters = len(self.units)
        if body:
            last = max(body, key=lambda s: s.end)
            self.ends_with_exit = last.verb in ("GOBACK", "STOP") or \
                (last.verb == "EXIT" and p.up(last.start + 1) == "PROGRAM")

    @property
    def n(self):
        return max(1, self.counters)

    # ---------------------------------------------------------- branches
    def _children(self):
        """Direct children of each statement: {start of the parent: [Stmt]}."""
        out, stack = {}, []
        for st in sorted(self.prog.statements, key=lambda s: (s.start, -s.end)):
            while stack and stack[-1].end <= st.start:
                stack.pop()
            if stack:
                out.setdefault(stack[-1].start, []).append(st)
            stack.append(st)
        return out

    def _line_of(self, tok):
        return self.prog.origin_of_line(self.prog.tokens[tok].line)[1]

    def _body_counter(self, tok, unit_at):
        """Counter of the entries to a body that starts at tok: that of the
        statement that opens it or, if there is none (NEXT SENTENCE), its own."""
        u = unit_at.get(tok)
        if u is not None:
            return u.idx
        self.counters += 1
        self.inserts.setdefault(tok, []).append(f"ADD 1 TO {HIT_ITEM}({self.counters})")
        return self.counters

    def _conditions(self, tok, cond_list):
        """Per-operand evaluation tree inserted before token tok
        (see condcov). Returns the operands per condition, or None if the
        condition is not understood (regular branch coverage remains)."""
        saved = self.counters

        def new_counter():
            self.counters += 1
            return self.counters
        try:
            lines, ops = condcov.build(cond_list, self.cond_names, self.data_names, new_counter, HIT_ITEM)
        except condcov.CondError:
            self.counters = saved
            return None
        self.inserts.setdefault(tok, []).extend(lines)
        return ops

    def _build_branches(self):
        unit_at = {u.start: u for u in self.units}
        children = self._children()
        for u in self.units:
            st = u.stmt
            ch = children.get(st.start, [])
            if st.verb == "IF":
                self._branches_if(u, st, ch, unit_at)
            elif st.verb in ("EVALUATE", "SEARCH"):
                self._branches_evaluate(u, st, ch, unit_at)
            elif st.verb == "GO":
                self._branches_goto(u, st)
            elif st.phrases:
                self._branches_phrases(u, st, unit_at)

    def _add(self, u, label, line, idx=None, implicit=False, kind=None):
        self.branches.append(Branch(u.idx, kind or u.verb, label, line, u.file, u.para, idx, implicit))

    def _add_cond(self, u, ops, line):
        """True / false outcomes of each operand of a compound condition."""
        for op in ops:
            self._add(u, op.text(28) + " true", line, op.idx_true, kind="COND")
            self._add(u, op.text(28) + " false", line, op.idx_false, kind="COND")

    def _branches_if(self, u, st, ch, unit_at):
        p = self.prog
        then_head = else_head = else_line = None
        seen_else = False
        j, ci = st.start + 1, 0
        while j < st.end:
            while ci < len(ch) and ch[ci].start < j:
                ci += 1
            is_body = ci < len(ch) and ch[ci].start == j
            if is_body or (p.up(j) == "NEXT" and p.up(j + 1) == "SENTENCE"):
                if seen_else and else_head is None:
                    else_head = j
                elif not seen_else and then_head is None:
                    then_head = j
                j = ch[ci].end if is_body else j + 2
                continue
            if p.up(j) == "ELSE" and not seen_else:
                seen_else, else_line = True, self._line_of(j)
            j += 1
        if then_head is None:
            return
        cond = p.tokens[st.start + 1:then_head]
        if cond and cond[-1].up == "THEN":
            cond = cond[:-1]
        if condcov.is_compound(cond):
            ops = self._conditions(st.start, [cond])
            if ops is not None:
                self._add_cond(u, ops[0], u.line)
        self._add(u, "THEN", u.line, self._body_counter(then_head, unit_at))
        if else_head is not None:
            self._add(u, "ELSE", else_line, self._body_counter(else_head, unit_at))
        else:
            self._add(u, "ELSE", u.line, implicit=True)

    def _when_text(self, j, end, limit=24):
        """Objects of the WHEN that starts at j (up to the body or the next
        WHEN), trimmed for the branch label."""
        T, p = self.prog.tokens, self.prog
        words = []
        while j < end and p.up(j) != "WHEN" and p.up(j) not in VERBS \
                and not (p.up(j) == "NEXT" and p.up(j + 1) == "SENTENCE"):
            words.append(T[j].text)
            j += 1
        text = " ".join(words).replace("( ", "(").replace(" )", ")")
        return text if len(text) <= limit else text[:limit - 3] + "..."

    def _branches_evaluate(self, u, st, ch, unit_at):
        """A WHEN group (several consecutive WHENs share a body), WHEN
        OTHER and, in SEARCH, AT END. Without WHEN OTHER / AT END, the
        implicit branch is 'none matched' / 'not found'."""
        p = self.prog
        groups, cur = [], None                  # [head, body, label, [whens]]
        whens = []                              # [start, end) of the condition of each WHEN
        chain = st.verb == "EVALUATE" and p.up(st.start + 1) == "TRUE" and p.up(st.start + 2) == "WHEN"
        j, ci = st.start + 1, 0
        while j < st.end:
            while ci < len(ch) and ch[ci].start < j:
                ci += 1
            is_body = ci < len(ch) and ch[ci].start == j
            if is_body or (p.up(j) == "NEXT" and p.up(j + 1) == "SENTENCE"):
                if cur is not None and cur[1] is None:
                    cur[1] = j
                if whens and whens[-1][1] is None:
                    whens[-1][1] = j
                j = ch[ci].end if is_body else j + 2
                continue
            w = p.up(j)
            if w == "WHEN":
                if whens and whens[-1][1] is None:
                    whens[-1][1] = j
                if cur is None or cur[1] is not None:
                    cur = [j, None, "WHEN " + self._when_text(j + 1, st.end), []]
                    groups.append(cur)
                if p.up(j + 1) != "OTHER":
                    cur[3].append(len(whens))
                    whens.append([j + 1, None, self._line_of(j)])
                j += 1
                continue
            if st.verb == "SEARCH" and w == "AT" and p.up(j + 1) == "END":
                cur = [j, None, "AT END", []]
                groups.append(cur)
                j += 2
                continue
            j += 1
        if whens and whens[-1][1] is None:
            whens[-1][1] = st.end - 1 if st.terminated else st.end
        groups = [g for g in groups if g[1] is not None]
        if not groups:
            return
        ops_by_when = None
        if chain and whens:
            conds = [p.tokens[a:b] for a, b, _ in whens]
            if any(condcov.is_compound(c) for c in conds):
                ops_by_when = self._conditions(st.start, conds)
        for head, body, label, ids in groups:
            self._add(u, label, self._line_of(head), self._body_counter(body, unit_at))
            for k in ids:
                if ops_by_when is not None and ops_by_when[k]:
                    self._add_cond(u, ops_by_when[k], whens[k][2])
        labels = {g[2] for g in groups}
        if st.verb == "EVALUATE" and "WHEN OTHER" not in labels:
            self._add(u, "WHEN OTHER", u.line, implicit=True)
        if st.verb == "SEARCH" and "AT END" not in labels:
            self._add(u, "AT END", u.line, implicit=True)

    def _branches_goto(self, u, st):
        """GO TO a b c DEPENDING ON x: one target per value 1..n and the
        implicit fall-through (x out of range continues with the next
        statement). Before the GO TO an EVALUATE on x is inserted that
        counts the chosen target; the statement is not touched."""
        T, p = self.prog.tokens, self.prog
        j = st.start + 1
        if p.up(j) == "TO":
            j += 1
        dests = []
        while j < st.end and p.up(j) != "DEPENDING":
            dests.append(T[j].text)
            j += 1
        if j >= st.end or not dests:
            return
        j += 1
        if p.up(j) == "ON":
            j += 1
        var = condcov.Op(condcov.pieces_of(T[j:st.end])).text()
        if not var or len(var) > 30:
            return
        lines = [f"EVALUATE {var}"]
        for k, dest in enumerate(dests, 1):
            self.counters += 1
            lines += [f"  WHEN {k}", f"    ADD 1 TO {HIT_ITEM}({self.counters})"]
            self._add(u, f"GO TO {dest}", u.line, self.counters)
        lines.append("END-EVALUATE")
        self.inserts.setdefault(st.start, []).extend(lines)
        self._add(u, "no jump", u.line, implicit=True)

    def _branches_phrases(self, u, st, unit_at):
        """A conditional phrase and its opposite (AT END / NOT AT END, ...):
        the missing one is the implicit branch."""
        fam, sides = None, {}
        for name, j, b0, b1 in st.phrases:
            neg = name.startswith("NOT ")
            base = name[4:] if neg else name
            if st.verb == "CALL" and base == "ON OVERFLOW":
                base = "ON EXCEPTION"           # same family as ON EXCEPTION
            if fam is None:
                fam = base
            if base != fam or neg in sides:
                continue
            if b1 is None or b1 <= b0:
                return                          # empty body: not measured
            sides[neg] = (name, j, b0)
        if not sides:
            return
        for neg in (False, True):
            if neg in sides:
                name, j, b0 = sides[neg]
                self._add(u, name, self._line_of(j), self._body_counter(b0, unit_at))
            else:
                self._add(u, ("NOT " if neg else "") + fam, u.line, implicit=True)

    # -------------------------------------------------------- COBOL
    def emit_ws(self, w):
        w.comment("CBLT: coverage counters")
        w.a("01  CBLT-COV-CTL.")
        w.b('05  CBLT-COV-OP            PIC X VALUE "F".')
        w.b(f'05  CBLT-COV-PGM           PIC X(30) VALUE "{self.name[:30]}".')
        w.b(f"05  CBLT-COV-N             PIC 9(5) VALUE {self.counters}.")
        w.a("01  CBLT-COV-TAB.")
        w.b(f"05  {HIT_ITEM}           PIC 9(9) OCCURS {self.n} TIMES")
        w.b("VALUE ZERO.", None, 26)

    def emit_flush(self, w, origin=None, indent=0):
        for txt in FLUSH_LINES:
            w.b(txt, origin, indent)

    def to_json(self, path):
        return {"program": self.name, "file": path, "counters": self.counters,
                "paragraphs": [{"name": n, "line": l, "end_line": e, "section": s}
                               for n, l, e, s in self.paragraphs],
                "units": [{"idx": u.idx, "verb": u.verb, "line": u.line, "end_line": u.end_line,
                           "file": u.file, "paragraph": u.para} for u in self.units],
                "branches": [{"stmt": b.stmt, "kind": b.kind, "label": b.label, "line": b.line,
                              "file": b.file, "paragraph": b.para, "idx": b.idx,
                              "implicit": b.implicit} for b in self.branches]}


# ------------------------------------------------------------------ report
def parse_records(records):
    """C|program|index|count records -> {program: {index: count}}."""
    hits = {}
    for r in records:
        f = r.split("|")
        if f[0] == "C" and len(f) >= 4:
            try:
                hits.setdefault(f[1].strip(), {})[int(f[2])] = int(f[3])
            except ValueError:
                continue
    return hits


def branch_counts(m, counts):
    """[(branch, entries)] of a map. The implicit branch is derived: entries
    to the statement minus those of its explicit branches."""
    explicit = {}
    for b in m.get("branches", []):
        if b["idx"] is not None and b["kind"] != "COND":     # per-operand outcomes are not mutually exclusive
            explicit[b["stmt"]] = explicit.get(b["stmt"], 0) + counts.get(b["idx"], 0)
    out = []
    for b in m.get("branches", []):
        if b["idx"] is not None:
            c = counts.get(b["idx"], 0)
        else:
            c = max(0, counts.get(b["stmt"], 0) - explicit.get(b["stmt"], 0))
        out.append((b, c))
    return out


def branch_text(b):
    return f"{b['line']} {b['label']}" + (" implicit" if b["implicit"] else "")


def summarize(cov_map, hits):
    """cov_map: {program: dict from to_json}. Returns a summary per program,
    ready for JSON (it is the "coverage" section of results.json):
    [{"program", "file", "paragraphs": {"hit", "total"}, "statements": {...},
      "branches": {...},
      "rows": [{"name", "section", "entries" (None if the paragraph has no
                instrumentable statements), "statements": {"hit", "total"},
                "missed_lines", "branches": {"hit", "total"}, "missed_branches"}]}]"""
    out = []
    for name, m in cov_map.items():
        counts = hits.get(name, {})
        by_para, br_para = {}, {}
        for u in m["units"]:
            by_para.setdefault(u["paragraph"], []).append(u)
        for b, c in branch_counts(m, counts):
            br_para.setdefault(b["paragraph"], []).append((b, c))
        rows = []
        phit = ptot = shit = stot = bhit = btot = 0
        for pp in m["paragraphs"]:
            pname, is_sec = pp["name"], bool(pp["section"])
            units = by_para.get(pname, [])
            if not units:
                rows.append({"name": pname, "section": is_sec, "entries": None,
                             "statements": {"hit": 0, "total": 0}, "missed_lines": [],
                             "branches": {"hit": 0, "total": 0}, "missed_branches": []})
                continue
            got = [counts.get(u["idx"], 0) for u in units]
            h = sum(1 for c in got if c > 0)
            missed = sorted({u["line"] for u, c in zip(units, got) if c == 0})
            brs = br_para.get(pname, [])
            bh = sum(1 for _, c in brs if c > 0)
            bmissed = [branch_text(b) for b, c in sorted(brs, key=lambda x: (x[0]["line"], x[0]["stmt"]))
                       if c == 0]
            rows.append({"name": pname, "section": is_sec, "entries": got[0],
                         "statements": {"hit": h, "total": len(units)}, "missed_lines": missed,
                         "branches": {"hit": bh, "total": len(brs)}, "missed_branches": bmissed})
            ptot += 1
            phit += 1 if h else 0
            stot += len(units)
            shit += h
            btot += len(brs)
            bhit += bh
        out.append({"program": name, "file": m["file"],
                    "paragraphs": {"hit": phit, "total": ptot},
                    "statements": {"hit": shit, "total": stot},
                    "branches": {"hit": bhit, "total": btot}, "rows": rows})
    return out


def _pct(h, t):
    return 100 * h // max(1, t)


def print_report(summary, out=print):
    """Console output of the portable coverage, from the summary of summarize()."""
    if not summary:
        return
    out("\nPortable coverage (instrumented statements and branches, by paragraph):")
    tp = [0] * 6
    for prog in summary:
        tot = [prog[k][x] for k in ("paragraphs", "statements", "branches") for x in ("hit", "total")]
        phit, ptot, shit, stot, bhit, btot = tot
        out(f"  {prog['file']}  ({prog['program']})  paragraphs {phit}/{ptot}  statements {shit}/{stot}  "
            f"{_pct(shit, stot)}%  branches {bhit}/{btot}  {_pct(bhit, btot)}%")
        for row in prog["rows"]:
            label = row["name"] + (" SECTION" if row["section"] else "")
            if row["entries"] is None:
                out(f"    {label:30s}      -   (no instrumentable statements)")
                continue
            h, total = row["statements"]["hit"], row["statements"]["total"]
            bh, bt = row["branches"]["hit"], row["branches"]["total"]
            missed, bmissed = row["missed_lines"], row["missed_branches"]
            tags = []
            if h == 0:
                tags.append("NOT EXECUTED")
            else:
                if missed:
                    tags.append("statements not executed on lines " +
                                ", ".join(str(x) for x in missed[:10]) + (" ..." if len(missed) > 10 else ""))
                if bmissed:
                    tags.append("branches not executed: " + ", ".join(bmissed[:8]) +
                                (" ..." if len(bmissed) > 8 else ""))
            bcell = f"branches {bh}/{bt:<3d}" if bt else " " * 16
            out((f"    {label:30s} {row['entries']:6d}x  {h:4d}/{total:<4d} {_pct(h, total):3d}%  {bcell}"
                 + ("  " + "; ".join(tags) if tags else "")).rstrip())
        for i, v in enumerate(tot):
            tp[i] += v
    if len(summary) > 1 and tp[3]:
        out(f"  TOTAL  paragraphs {tp[0]}/{tp[1]}  statements {tp[2]}/{tp[3]}  {_pct(tp[2], tp[3])}%"
            f"  branches {tp[4]}/{tp[5]}  {_pct(tp[4], tp[5])}%")


def _lines_by_file(m, counts):
    """{file: {line: max_count}} and {file: [(name, line, entries)]} for LCOV/Cobertura."""
    lines, funcs = {}, {}
    first_unit = {}
    for u in m["units"]:
        c = counts.get(u["idx"], 0)
        d = lines.setdefault(u["file"], {})
        d[u["line"]] = max(d.get(u["line"], 0), c)
        first_unit.setdefault(u["paragraph"], (u["file"], c))
    for pp in m["paragraphs"]:
        if pp["name"] in first_unit:
            f, c = first_unit[pp["name"]]
            funcs.setdefault(f, []).append((pp["name"], pp["line"], c))
    return lines, funcs


def _branches_by_file(m, counts):
    """{file: {line of the statement: [(statement idx, ordinal, label, entries)]}}."""
    stmt_line = {u["idx"]: (u["file"], u["line"]) for u in m["units"]}
    out, ordinal = {}, {}
    for b, c in branch_counts(m, counts):
        f, ln = stmt_line[b["stmt"]]
        i = ordinal.get(b["stmt"], 0)
        ordinal[b["stmt"]] = i + 1
        out.setdefault(f, {}).setdefault(ln, []).append((b["stmt"], i, b["label"], c))
    return out


def write_lcov(cov_map, hits, path):
    L = []
    for name, m in cov_map.items():
        counts = hits.get(name, {})
        lines, funcs = _lines_by_file(m, counts)
        branches = _branches_by_file(m, counts)
        for f in sorted(lines):
            L.append("TN:")
            L.append(f"SF:{f}")
            for pname, line, c in funcs.get(f, []):
                L.append(f"FN:{line},{pname}")
            for pname, line, c in funcs.get(f, []):
                L.append(f"FNDA:{c},{pname}")
            L.append(f"FNF:{len(funcs.get(f, []))}")
            L.append(f"FNH:{sum(1 for _, _, c in funcs.get(f, []) if c)}")
            brf = brh = 0
            for ln in sorted(branches.get(f, {})):
                for stmt, i, label, c in branches[f][ln]:
                    L.append(f"BRDA:{ln},{stmt},{i},{c}")
                    brf += 1
                    brh += 1 if c else 0
            L.append(f"BRF:{brf}")
            L.append(f"BRH:{brh}")
            for ln in sorted(lines[f]):
                L.append(f"DA:{ln},{lines[f][ln]}")
            L.append(f"LF:{len(lines[f])}")
            L.append(f"LH:{sum(1 for c in lines[f].values() if c)}")
            L.append("end_of_record")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + ("\n" if L else ""))


def write_cobertura(cov_map, hits, path):
    classes, tot_hit, tot_all, tot_bhit, tot_ball = [], 0, 0, 0, 0
    for name, m in cov_map.items():
        counts = hits.get(name, {})
        lines, funcs = _lines_by_file(m, counts)
        branches = _branches_by_file(m, counts)
        for f in sorted(lines):
            lh = sum(1 for c in lines[f].values() if c)
            lf = len(lines[f])
            tot_hit += lh
            tot_all += lf
            bl = branches.get(f, {})
            ball = sum(len(v) for v in bl.values())
            bhit = sum(1 for v in bl.values() for b in v if b[3])
            tot_bhit += bhit
            tot_ball += ball
            methods = []
            by_para = {}
            for u in m["units"]:
                if u["file"] == f:
                    by_para.setdefault(u["paragraph"], []).append(u)
            for pname, line, c in funcs.get(f, []):
                units = by_para.get(pname, [])
                mh = sum(1 for u in units if counts.get(u["idx"], 0))
                methods.append(f'        <method name="{escape(pname)}" signature="" '
                               f'line-rate="{mh / max(1, len(units)):.4f}" branch-rate="0">'
                               f'<lines><line number="{line}" hits="{c}"/></lines></method>')
            lines_xml = []
            for ln in sorted(lines[f]):
                if ln in bl:
                    t = len(bl[ln])
                    h = sum(1 for b in bl[ln] if b[3])
                    lines_xml.append(f'        <line number="{ln}" hits="{lines[f][ln]}" branch="true" '
                                     f'condition-coverage="{_pct(h, t)}% ({h}/{t})">'
                                     f'<conditions><condition number="0" type="jump" '
                                     f'coverage="{_pct(h, t)}%"/></conditions></line>')
                else:
                    lines_xml.append(f'        <line number="{ln}" hits="{lines[f][ln]}" branch="false"/>')
            classes.append(f'    <class name="{escape(name)}" filename="{escape(f)}" '
                           f'line-rate="{lh / max(1, lf):.4f}" branch-rate="{bhit / max(1, ball):.4f}" '
                           f'complexity="0">\n'
                           f'      <methods>\n' + "\n".join(methods) + '\n      </methods>\n'
                           f'      <lines>\n' + "\n".join(lines_xml) + '\n      </lines>\n    </class>')
    rate = tot_hit / max(1, tot_all)
    brate = tot_bhit / max(1, tot_ball)
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<coverage line-rate="{rate:.4f}" branch-rate="{brate:.4f}" lines-covered="{tot_hit}" '
           f'lines-valid="{tot_all}" branches-covered="{tot_bhit}" branches-valid="{tot_ball}" '
           f'complexity="0" version="cobalto" timestamp="{int(time.time())}">',
           '  <sources><source>.</source></sources>',
           '  <packages>',
           f'  <package name="cobol" line-rate="{rate:.4f}" branch-rate="{brate:.4f}" complexity="0">',
           '   <classes>'] + classes + ['   </classes>', '  </package>', '  </packages>', '</coverage>']
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(xml) + "\n")


def write_sonar(cov_map, hits, path):
    """SonarQube/SonarCloud generic coverage format (Generic Test
    Data, version 1): one <file path> per source file and one
    <lineToCover> per line with instrumented statements. The paths are
    those of the map, relative to the project root (where cblt.json is),
    which is the one the scanner must analyze (sonar.projectBaseDir). It
    is imported with sonar.coverageReportPaths=build/sonar-coverage.xml.

    The line of an IF, EVALUATE, SEARCH or of a statement with a
    conditional phrase declares branchesToCover = its branches and
    coveredBranches = the executed ones. A line without branches but with
    several statements (COBOL allows it: "WRITE ... INVALID KEY CONTINUE")
    is declared with branchesToCover = statements on the line and
    coveredBranches = the executed ones, so that Sonar marks it as
    partially covered instead of fully covered."""
    by_file, br = {}, {}
    for name, m in cov_map.items():
        h = hits.get(name, {})
        for u in m["units"]:
            t = by_file.setdefault(u["file"], {}).setdefault(u["line"], [0, 0])
            t[0] += 1
            if h.get(u["idx"], 0):
                t[1] += 1
        for f, by_line in _branches_by_file(m, h).items():
            for ln, bl in by_line.items():
                t = br.setdefault(f, {}).setdefault(ln, [0, 0])
                t[0] += len(bl)
                t[1] += sum(1 for b in bl if b[3])
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<coverage version="1">']
    for f in sorted(by_file):
        xml.append(f'  <file path="{escape(f, {chr(34): "&quot;"})}">')
        for ln in sorted(by_file[f]):
            total, done = by_file[f][ln]
            attrs = f'lineNumber="{ln}" covered="{"true" if done else "false"}"'
            if ln in br.get(f, {}):
                total, done = br[f][ln]
            if total > 1 or ln in br.get(f, {}):
                attrs += f' branchesToCover="{total}" coveredBranches="{done}"'
            xml.append(f'    <lineToCover {attrs}/>')
        xml.append('  </file>')
    xml.append('</coverage>')
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(xml) + "\n")


def save_map(cov_map, path):
    """Writes build/cov/map.json: the maps by PROGRAM-ID under "programs",
    next to the version of the format and of the CLI."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA, "cobalto": VERSION, "programs": cov_map}, fh, indent=1)


def load_map(path):
    """{PROGRAM-ID: map} of a map.json. A file from before the "schema" field
    was the programs themselves at the top level."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["programs"] if "schema" in data else data
