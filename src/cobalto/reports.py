"""Renderers of a run: console, junit.xml, sonar-tests.xml, JSON, and the gcov report."""
import glob
import json
import os
from xml.sax.saxutils import escape

from .results import reason_text

def failure_text(case):
    """Text of the asserts that failed in a test case, one per line."""
    return "\n".join(f'#{a["nr"]} {a["kind"]}: expected [{a["expected"]}] actual [{a["actual"]}]'
                     + (f'  ({a["message"]})' if a["message"] else "")
                     for a in case["asserts"] if a["status"] == "failed")


def suite_error(s):
    """Why a suite counts as an error, or None: it aborted, or asserts failed
    after its log was full and their detail did not arrive."""
    if not s["ended"]:
        return "The test aborted before finishing"
    if s.get("unlogged_failures"):
        return (f'{s["unlogged_failures"]} failed assert(s) have no detail: '
                "they ran after the log of the suite was full")
    return None


def render_console(run, verbose):
    """Console lines of a run: suites, test cases, warnings and totals."""
    L = [""]
    for s in run["suites"]:
        L.append(f"  {s['id']}" + (f"  {s['description']}" if s["description"] else ""))
        for c in s["cases"]:
            if c["implicit"] and not s["ended"]:
                continue
            tag = f"  · {c['kind']}" if c["kind"] and s["in_program"] else ""
            fails = [x for x in c["asserts"] if x["status"] == "failed"]
            if c["status"] == "skipped":
                L.append(f"    SKIP  {c['name']}{tag}")
            elif fails:
                L.append(f"    FAIL  {c['name']}  ({len(fails)} of {len(c['asserts'])} asserts){tag}")
                for x in fails:
                    L.append(f"          #{x['nr']} {x['kind']}: expected [{x['expected']}] actual [{x['actual']}]")
                    if x["message"]:
                        L.append(f"          {x['message']}")
            else:
                L.append(f"    PASS  {c['name']}  ({len(c['asserts'])} asserts){tag}")
            if verbose:
                if c["kind"] == "internal" and s["in_program"] and c["reasons"]:
                    L.append(f"          internal because of: {'; '.join(reason_text(r) for r in c['reasons'])}")
                L += [f"          > {line}" for line in c["output"]]
        if not s["ended"]:
            L.append("    ERROR the suite aborted before finishing")
        elif suite_error(s):
            L.append(f"    ERROR {suite_error(s)}")
    L += ["  " + f"{w['code']}: {w['message']}" for w in run["warnings"]
          if w["code"] in ("CBLT-W301", "CBLT-W307", "CBLT-W308")]
    if run["stderr"]:
        L.append("  stderr of the executable:")
        L += [f"    > {line}" for line in run["stderr"]]
    tot = run["totals"]
    L.append(f"\nCases: {tot['cases']}  Asserts: {tot['asserts']}  Failures: {tot['failed_asserts']}  "
             f"Skipped: {tot['skipped']}  Errors: {tot['errors']}  (binary exit: {run['binary_exit']})")
    if tot["interface"] or tot["internal"]:
        L.append(f"Interface cases: {tot['interface']}  internal: {tot['internal']}"
                 "  (interface: only parameters, files, calls and the clock; internal: paragraphs or fields of the program)")
    return L


def xml_attr(value):
    return escape(str(value), {'"': "&quot;"})


def write_junit(run, path):
    """junit.xml: one testcase per test case. What the format has no place
    for goes in properties of the case: cobalto.kind (interface or internal)
    and, if it failed, cobalto.expected and cobalto.actual of the first
    assert that failed."""
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuites>"]
    for s in run["suites"]:
        cases = s["cases"]
        nfail = sum(1 for c in cases if any(a["status"] == "failed" for a in c["asserts"]))
        nskip = sum(1 for c in cases if c["status"] == "skipped")
        error = suite_error(s)
        nerr = 1 if error else 0
        L.append(f'  <testsuite name="{xml_attr(s["id"])}" tests="{len(cases)}" '
                 f'failures="{nfail}" errors="{nerr}" skipped="{nskip}">')
        for i, c in enumerate(cases):
            L.append(f'    <testcase name="{xml_attr(c["name"])}" classname="{xml_attr(s["id"])}">')
            fails = [a for a in c["asserts"] if a["status"] == "failed"]
            props = [("cobalto.kind", c["kind"])] if c["kind"] else []
            if fails:
                props += [("cobalto.expected", fails[0]["expected"]), ("cobalto.actual", fails[0]["actual"])]
            if props:
                L.append("      <properties>" + "".join(f'<property name="{n}" value="{xml_attr(v)}"/>'
                                                        for n, v in props) + "</properties>")
            if c["status"] == "skipped":
                L.append("      <skipped/>")
            if fails:
                text = failure_text(c)
                L.append(f'      <failure message="{xml_attr(text.splitlines()[0])}">'
                         f'<![CDATA[{text}]]></failure>')
            if error and i == len(cases) - 1:
                L.append(f'      <error message="{xml_attr(error)}"/>')
            if c["output"]:
                L.append(f'      <system-out><![CDATA[{chr(10).join(c["output"])}]]></system-out>')
            L.append("    </testcase>")
        L.append("  </testsuite>")
    L.append("</testsuites>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def write_sonar_tests(run, path):
    """SonarQube generic test execution report
    (sonar.testExecutionReportPaths): one <file> per suite file and one
    <testCase> per test case, with <failure>, <skipped> or <error>. Sonar
    requires a duration in milliseconds; Cobalto does not time each case
    and writes 0. Paths are relative to the folder of cblt.json, which must
    be listed in sonar.tests."""
    by_file = {}
    for s in run["suites"]:
        by_file.setdefault(s["file"] or s["id"], []).append(s)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<testExecutions version="1">']
    for f in sorted(by_file):
        L.append(f'  <file path="{xml_attr(f)}">')
        for s in by_file[f]:
            error = suite_error(s)
            for i, c in enumerate(s["cases"]):
                name = c["name"] if len(by_file[f]) == 1 else f'{s["id"]}: {c["name"]}'
                failed = any(a["status"] == "failed" for a in c["asserts"])
                skipped = c["status"] == "skipped"
                aborted = bool(error) and i == len(s["cases"]) - 1
                if not failed and not skipped and not aborted:
                    L.append(f'    <testCase name="{xml_attr(name)}" duration="0"/>')
                    continue
                L.append(f'    <testCase name="{xml_attr(name)}" duration="0">')
                if skipped:
                    L.append('      <skipped message="IGNORE"/>')
                if failed:
                    text = failure_text(c)
                    L.append(f'      <failure message="{xml_attr(text.splitlines()[0])}">'
                             f'<![CDATA[{text}]]></failure>')
                if aborted:
                    L.append(f'      <error message="{xml_attr(error)}"/>')
                L.append("    </testCase>")
        L.append("  </file>")
    L.append("</testExecutions>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def report_coverage(pattern, source_names, inprog):
    """Reads .cbl.gcov files (gcov format: 'count: line: source') and shows
    the executed lines per COBOL file. Only the sources under test count:
    tests, driver and library are left out of the total."""
    rows, tot_hit, tot_all = [], 0, 0
    for g in sorted(glob.glob(pattern)):
        name = os.path.basename(g)[:-5]           # drops .gcov
        name = name.split("#")[-1]                # llvm-gcov encodes paths with #
        hit = total = 0
        missed = []
        with open(g, encoding="latin-1") as fh:
            lines = fh.readlines()
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            count, ln = parts[0].strip(), parts[1].strip()
            if count == "-" or ln == "0":
                continue
            total += 1
            if count == "#####":
                missed.append(ln)
            else:
                hit += 1
        original = inprog.get(name[:-4]) if name.endswith(".cbl") else None
        under_test = name in source_names or original is not None
        if original is not None:
            name = f"{name} (in-program copy of {original})"
        rows.append((name, hit, total, missed, under_test))
        if under_test:
            tot_hit += hit; tot_all += total
    if not rows:
        return
    print("\nCoverage (executable COBOL lines):")
    for name, hit, total, missed, ut in rows:
        pct = 100 * hit // max(1, total)
        tag = "" if ut else "   (not code under test)"
        extra = f"  not executed: {', '.join(missed[:12])}" + (" ..." if len(missed) > 12 else "") if ut and missed else ""
        print(f"  {name:28s} {hit:4d}/{total:<4d} {pct:3d}%{tag}{extra}")
    if tot_all:
        print(f"  {'TOTAL code under test':28s} {tot_hit:4d}/{tot_all:<4d} {100 * tot_hit // tot_all:3d}%")
