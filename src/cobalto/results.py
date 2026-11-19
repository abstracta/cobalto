"""Results protocol: reading the records the driver writes, and the run model."""
import os

from .messages import MESSAGES, SCHEMA, VERSION

def read_records(path, fmt):
    """The records as they arrived, with their space padding."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        data = fh.read().decode("latin-1")
    if fmt == "fixed200" and "\n" not in data:
        # fixed 200-byte records with no separator (SEQUENTIAL on VMS or
        # GnuCOBOL); if the transfer added line breaks, the branch below
        recs = [data[i:i + 200] for i in range(0, len(data), 200)]
    else:
        recs = data.splitlines()
    return [r for r in recs if r.strip()]


def read_results(path, fmt):
    recs = read_records(path, fmt)
    return None if recs is None else [r.rstrip() for r in recs]


def split_assert(r):
    """A|s|nnnnn|kind(8)|exp(60)|act(60)|msg(60): by position, so that a
    '|' inside a value does not shift the fields; if the record does not
    have that shape, by separator."""
    if len(r) > 19 and r[1] == r[3] == r[9] == r[18] == "|" and (len(r) <= 79 or r[79] == "|") \
            and (len(r) <= 140 or r[140] == "|"):
        return ["A", r[2], r[4:9], r[10:18], r[19:79], r[80:140], r[141:201]]
    f = r.split("|")
    return (f + [""] * 7)[:7]


def truncated_asserts(raw):
    """Lengths, as they arrived, of the A records that were cut. A complete
    one has the description separator at column 141 even when the fields are
    empty, so trimming trailing spaces never makes it shorter than that; a
    shorter one lost data (a copy from a terminal that cuts lines at the
    screen width). The longest one marks the column of the cut."""
    return [len(r) for r in raw
            if 19 < len(r.rstrip()) < 141 and r[0] == "A" and r[1] == r[3] == r[9] == r[18] == "|"]


def parse_results(records):
    suites, cur, case = [], None, None
    for r in records:
        f = r.split("|")
        if f[0] == "T":
            cur = {"name": f[1].strip(), "cases": [], "ended": False}
            case = None
            suites.append(cur)
        elif f[0] == "A" and cur:
            f = split_assert(r)
            status, kind = f[1], f[3].strip()
            if kind == "CASE":
                case = {"name": f[4].strip(), "ignored": status == "I", "asserts": []}
                cur["cases"].append(case)
            else:
                if case is None:
                    case = {"name": cur["name"], "ignored": False, "asserts": []}
                    cur["cases"].append(case)
                case["asserts"].append({"status": status, "nr": int(f[2]), "kind": kind,
                                        "exp": f[4].strip(), "act": f[5].strip(),
                                        "msg": f[6].strip()})
        elif f[0] == "E" and cur:
            cur["ended"] = True
            try:
                # what the suite counted, whether or not the detail fit in its log
                cur["asserts"], cur["failed"] = int(f[2]), int(f[3])
            except (IndexError, ValueError):
                pass
    return suites


def split_output(stdout):
    """Splits the executable's output by suite and by test case, using the
    CBLT-T| and CBLT-C| markers that the COBOL code writes with DISPLAY."""
    out, suite, case = {}, None, None
    for line in stdout.splitlines():
        if line.startswith("CBLT-T|"):
            suite, case = line[7:].strip(), None
            out.setdefault((suite, None), [])
        elif line.startswith("CBLT-C|"):
            case = line[7:].strip()
            out.setdefault((suite, case), [])
        elif suite is not None:
            out.setdefault((suite, case), []).append(line)
    return out


def reason_text(reason):
    return f"{reason['construct']} (line {reason['line']})" if reason.get("line") else reason["construct"]


def build_run(gen, parsed, outputs, rc, raw, profile):
    """The single model of a run: the console, junit.xml, sonar-tests.xml
    and results.json are all rendered from it, and it is what 'suggest' and
    --json read. gen: the Generated with the suites that were asked to run
    and what is known about them; parsed: what the results file says ran;
    raw: its records as they arrived.

    A suite with no declared test cases (a hand-written test program) gets
    one implicit case named after it. If the suite also aborted, that case
    is left out of the totals and of the console: only the error shows."""
    meta = {s.id: (s.file, s.description) for s in gen.suites}
    tot = {"cases": 0, "asserts": 0, "failed_asserts": 0, "failed_cases": 0, "skipped": 0, "errors": 0,
           "interface": 0, "internal": 0}
    out, unlogged_warnings = [], []
    for s in parsed:
        file, desc = meta.get(s["name"], ("", ""))
        original = gen.inprog.get(s["name"])
        implicit = not s["cases"]
        cases = []
        for c in s["cases"] or [{"name": s["name"], "ignored": False, "asserts": []}]:
            kind, reasons = gen.case_kinds.get((s["name"], c["name"]), ("", []))
            asserts = [{"nr": x["nr"], "status": "failed" if x["status"] == "F" else "passed", "kind": x["kind"],
                        "expected": x["exp"], "actual": x["act"], "message": x["msg"]} for x in c["asserts"]]
            failed = sum(1 for x in asserts if x["status"] == "failed")
            cases.append({"name": c["name"],
                          "status": "skipped" if c["ignored"] else "failed" if failed else "passed",
                          "kind": kind, "reasons": reasons, "implicit": implicit, "asserts": asserts,
                          "output": outputs.get((s["name"], None if implicit else c["name"]), [])})
            if implicit and not s["ended"]:
                continue
            tot["cases"] += 1
            tot["asserts"] += len(asserts)
            tot["failed_asserts"] += failed
            tot["failed_cases"] += 1 if failed and not c["ignored"] else 0
            tot["skipped"] += 1 if c["ignored"] else 0
            if kind:
                tot[kind] += 1
        if not s["ended"]:
            tot["errors"] += 1
        # The suite counts every assert, but its log keeps a fixed number of
        # entries. Past that, the end record still says how many ran and how
        # many failed: a failure with no detail is an error of the suite, never
        # a silent pass.
        logged = sum(len(c["asserts"]) for c in cases)
        logged_failed = sum(1 for c in cases for x in c["asserts"] if x["status"] == "failed")
        unlogged = max(0, s.get("asserts", logged) - logged)
        hidden = max(0, s.get("failed", logged_failed) - logged_failed)
        if unlogged or hidden:
            tot["asserts"] += unlogged
            tot["failed_asserts"] += hidden
            tot["errors"] += 1 if hidden else 0
            unlogged_warnings.append({"code": "CBLT-W308", "message": MESSAGES["W308"].format(
                suite=s["name"], asserts=s.get("asserts", logged), failed=s.get("failed", logged_failed),
                logged=logged)})
        out.append({"id": s["name"], "file": os.path.relpath(file) if file else "", "description": desc or "",
                    "in_program": original is not None, "program": original, "ended": s["ended"],
                    "unlogged_asserts": unlogged, "unlogged_failures": hidden, "cases": cases})
    missing = max(0, len(gen.suites) - len(parsed))
    tot["errors"] += missing
    cut = truncated_asserts(raw)
    warnings = []
    if missing:
        warnings.append({"code": "CBLT-W301", "message": MESSAGES["W301"].format(n=missing)})
    if cut:
        warnings.append({"code": "CBLT-W307", "message": MESSAGES["W307"].format(n=len(cut), col=max(cut))})
    warnings += unlogged_warnings
    return {"schema": SCHEMA, "cobalto": VERSION, "profile": profile, "binary_exit": rc,
            "ok": not (tot["failed_asserts"] or tot["errors"] or rc),
            "totals": tot, "suites": out, "missing_suites": missing,
            "stderr": outputs.get(("__stderr__", None), []), "warnings": warnings, "coverage": None}
