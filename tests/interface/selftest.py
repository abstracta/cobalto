#!/usr/bin/env python3
"""Self-test for the interface tests.

Runs the suites of this folder and checks what the CLI does not assert by
itself: that the guards after STOP RUN / GOBACK give the expected
values (in paragraphs, in sections, with multi-line statements and with
a simulated READ), that coverage reaches every statement of the
synthetic programs, that each test case is classified as expected
(interface or internal), that a 60-character test case name compiles,
that RUN rejects what it must reject, and that the deterministic
characterization of `suggest` replaces what it must and leaves the rest
alone.

    python3 tests/interface/selftest.py             (everything)
    python3 tests/interface/selftest.py --local-only  (does not touch examples/build)
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
# the CLI of this working copy, without installing it
sys.path.insert(0, SRC)
os.environ["PYTHONPATH"] = os.pathsep.join(x for x in (SRC, os.environ.get("PYTHONPATH")) if x)
from cobalto import suggest  # noqa: E402

LOCAL_ONLY = "--local-only" in sys.argv
failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


def run_cli(cwd, *args, config=None):
    cmd = [sys.executable, "-m", "cobalto"]
    if config:
        cmd += ["--config", config]
    r = subprocess.run(cmd + ["test", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def kinds(junit):
    out = {}
    for s in ET.parse(junit).getroot().findall("testsuite"):
        for c in s.findall("testcase"):
            props = [p.get("value") for p in c.findall("properties/property") if p.get("name") == "cobalto.kind"]
            out[(s.get("name"), c.get("name"))] = props[0] if props else ""
    return out


print("1. Local suites: GUARD (guards, 60-character name), SECTS (sections, multi-line, file) and FALLS (fall-through)")
rc, out = run_cli(HERE, "--coverage")
check(rc == 0, "exit 0")
check(re.search(r"^Cases: 11\s+Asserts: 44\s+Failures: 0\s+Skipped: 0\s+Errors: 0", out, re.M) is not None,
      "11 test cases, 44 asserts, 0 failures")
check("(GUARD)  paragraphs 2/2  statements 13/13" in out, "GUARD: 13/13 statements and 2/2 paragraphs")
check("(SECTS)  paragraphs 3/3  statements 22/22" in out and "branches 8/8" in out,
      "SECTS: 22/22 statements and 8/8 branches")
check("(FALLS)  paragraphs 2/2  statements 3/3" in out, "FALLS: 3/3 statements")
check("Interface cases: 1  internal: 10" in out, "classification: 1 interface case, 10 internal cases")
t = kinds(os.path.join(HERE, "build", "junit.xml"))
check(t.get(("TSTGUARD", "solely through the interface: it stops once and nothing more")) == "interface",
      "the test case that only uses RUN, CBLT-STOPPED and VERIFY STOP is an interface case in the JUnit")
check(t.get(("TSTGUARD", "normal path: final STOP RUN, every step")) == "internal",
      "the test case that looks at WS-STEP is an internal case in the JUnit")
check(t.get(("TSTSECTS", "mocked paragraph with STOP: the original does not run")) == "internal",
      "a test case with MOCK PARAGRAPH is an internal case in the JUnit")
guard = open(os.path.join(HERE, "build", "TSTGUARD.cbl")).read()
check(guard.count("IF CBLT-NOT-STOPPED") == 6 and "SET CBLT-STOPPED TO TRUE" in guard,
      "GUARD: 6 guards in the copy (5 in 0000-MAIN, 1 in 1000-WORK) and the flag")
sects = open(os.path.join(HERE, "build", "TSTSECTS.cbl")).read()
check(sects.count("IF CBLT-NOT-STOPPED") == 8, "SECTS: 8 guards in the copy (7 in 0000-START, 1 in 1000-CHECK)")
check("PERFORM MAIN" in sects, "RUN on SECTS executes the entry SECTION (PERFORM MAIN)")
for name, text in (("TSTGUARD", guard), ("TSTSECTS", sects)):
    check(all(len(l) <= 72 for l in text.splitlines()), f"{name}: no generated line goes past column 72")

print("1b. DSL errors of RUN (exit 2 and message)")
err_dir = os.path.join(HERE, "build", "errors")
os.makedirs(err_dir, exist_ok=True)
cfg = json.load(open(os.path.join(HERE, "cblt.json")))
bad = {
    "RUNEXT.cblt": ("       TESTSUITE TSTBAD1 'RUN without PROGRAM'\n\n       TESTCASE 'x'\n           RUN\n",
                    "RUN are only valid in a suite with PROGRAM"),
    "RUNARGS.cblt": ("       TESTSUITE TSTBAD2 'RUN USING with an extra argument'\n       PROGRAM GUARD\n\n"
                     "       TESTCASE 'x'\n           RUN USING WS-STEP\n",
                     "the program takes 0 parameter(s)"),
}
for name, (text, expected) in bad.items():
    path = os.path.join(err_dir, name)
    open(path, "w").write(text)
    cfg["tests"] = [os.path.relpath(path, HERE)]
    cfg_path = os.path.join(err_dir, name + ".json")
    json.dump(cfg, open(cfg_path, "w"))
    rc, out = run_cli(HERE, "--no-run", config=os.path.relpath(cfg_path, HERE))
    check(rc == 2 and expected in out, f"{name}: CBLT-E200 with '{expected}'")

if LOCAL_ONLY:
    print("2. (skipped with --local-only: examples/build is not touched)")
else:
    print("2. Interface suites of the main project (RUN USING, CBLT-CALL-COUNT)")
    rc, out = run_cli(os.path.join(ROOT, "examples"), "--filter", "IFACE")
    check(rc == 0 and "Cases: 3  Asserts: 16  Failures: 0" in out, "TSTIFACE: 3 test cases and 16 asserts pass")
    rc2, out2 = run_cli(os.path.join(ROOT, "examples"), "--filter", "TSTDISCI")
    check(rc2 == 0 and "Cases: 2  Asserts: 5  Failures: 0" in out2,
          "TSTDISCI (RUN USING): 2 test cases and 5 asserts pass")
    check("Interface cases: 2  internal: 0" in out2, "TSTDISCI: both test cases are interface cases")

print("3. suggest.fill_expected (deterministic characterization)")
suite = """       TESTSUITE XAI 'x'
       PROGRAM INVOICE

       TESTCASE 'case one'
           RUN
           EXPECT T-LINES TO BE NUMERIC 3
           EXPECT T-CAPTURED TO BE 'C009 GAMMA          987.65 PREMIUM'
           EXPECT WS-EOF TO BE SPACES
           EXPECT WS-END-OF-FILE TO BE FALSE
           EXPECT T-LINES TO BE GREATER THAN 5
           EXPECT WS-CATEGORY NOT TO BE 'X'
"""
msgs = [("EXPECT T-LINES TO BE NUMERIC 3", "EQNUM", "3.000", "2.000"),
        ("EXPECT T-CAPTURED TO BE 'C009 GAMMA          987.65 PREMIUM'", "EQUALS",
         "C009 GAMMA          987.65 PREMIUM", "C009 GAMMA          987.64 PREMIUM"),
        ("EXPECT WS-EOF TO BE SPACES", "EQUALS", "", "Y"),
        ("EXPECT WS-END-OF-FILE TO BE FALSE", "EQUALS", "FALSE", "TRUE"),
        ("EXPECT T-LINES TO BE GREATER THAN 5", "GT", "5.000", "2.000"),
        ("EXPECT WS-CATEGORY NOT TO BE 'X'", "NE", "X", "X")]
run = {"suites": [{"id": "XAI", "cases": [{"name": "case one", "status": "failed", "asserts": [
    {"nr": i, "status": "failed", "kind": k, "expected": e, "actual": a, "message": m[:60]}
    for i, (m, k, e, a) in enumerate(msgs, 1)]}]}]}
new, n = suggest.fill_expected(suite, run)
check(n == 4, f"replaces 4 of 6 (numeric, alphanumeric, SPACES, FALSE): {n}")
check("EXPECT T-LINES TO BE NUMERIC 2" in new, "numeric: 3 -> 2 with no extra zeros")
check("EXPECT T-CAPTURED TO BE 'C009 GAMMA          987.64 PREMIUM'" in new, "alphanumeric: takes the actual value")
check("EXPECT WS-EOF TO BE 'Y'" in new, "SPACES -> actual literal")
check("EXPECT WS-END-OF-FILE TO BE TRUE" in new, "FALSE -> TRUE")
check("GREATER THAN 5" in new and "NOT TO BE 'X'" in new, "GREATER THAN and NOT TO BE are left for the model")
check(new.count("* REVIEW: original expected value") == 4, "every replacement carries its REVIEW comment")
check(all(len(l) <= 72 for l in new.splitlines()), "no line of the result goes past column 72")

print()
if failures:
    print(f"{len(failures)} checks FAILED")
    sys.exit(1)
print("all checks pass")
