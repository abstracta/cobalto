#!/usr/bin/env python3
"""selftest - regression suite for the error and warning catalog of the Cobalto CLI.

Each scenario builds a minimal project (cobalto init plus a synthetic program
and a suite), breaks it the way a CBLT-Exxx / CBLT-Wxxx code describes, runs
the CLI and checks the exit code and the message. It also checks the happy
path of the minimal project (external, in-program, coverage) and the
behaviors that have no code of their own: the ERROR of a suite that aborts,
E201 mapped to the line of the .cblt.

    python3 tests/cli/selftest.py              (all scenarios, in parallel)
    python3 tests/cli/selftest.py E401 W305    (only those)
    python3 tests/cli/selftest.py --keep       (keeps the projects in the temp folder)
    python3 tests/cli/selftest.py --list

Needs GnuCOBOL (cobc) and Python 3.9+. Standard library only. The suggest
scenarios use a fake command that returns a fixed text: no AI provider is
contacted.
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# The CLI of this working copy, without installing it: every process this
# script starts finds the package through PYTHONPATH.
os.environ["PYTHONPATH"] = os.pathsep.join(
    x for x in (os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"), os.environ.get("PYTHONPATH")) if x)
CLI = [sys.executable, "-m", "cobalto"]

# ------------------------------------------------------------- sources
CALC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "cust.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC                  PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-EOF                    PIC X VALUE "N".
       01  WS-COUNT                  PIC 9(3) VALUE 0.
       LINKAGE SECTION.
       01  LN-A                      PIC 9(4).
       01  LN-B                      PIC 9(4).
       01  LN-SUM                    PIC 9(5).
       PROCEDURE DIVISION USING LN-A LN-B LN-SUM.
       0000-MAIN.
           PERFORM 1000-ADD
           GOBACK.
       1000-ADD.
           ADD LN-A TO LN-B GIVING LN-SUM.
       2000-COUNT.
           OPEN INPUT CUST-FILE
           PERFORM UNTIL WS-EOF = "Y"
               READ CUST-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END ADD 1 TO WS-COUNT
               END-READ
           END-PERFORM
           CLOSE CUST-FILE.
       3000-SKIP.
           IF WS-COUNT > 0
               NEXT SENTENCE
           ELSE
               MOVE 0 TO WS-COUNT.
           MOVE 1 TO WS-COUNT.
       4000-INC.
           ADD 1 TO WS-COUNT.
       5000-JUMP.
           GO TO 9000-LAST.
       9000-LAST.
           EXIT.
"""

SUITE_EXT = """\
       TESTSUITE TSTCALC 'Addition'

       WORKING-STORAGE SECTION.
       01  WS-A                      PIC 9(4).
       01  WS-B                      PIC 9(4).
       01  WS-SUM                    PIC 9(5).

       TESTCASE 'two plus three is five'
           MOVE 2 TO WS-A
           MOVE 3 TO WS-B
           CALL "CALC" USING WS-A WS-B WS-SUM
           EXPECT WS-SUM TO BE NUMERIC 5
"""

SUITE_IN = """\
       TESTSUITE TSTCALCI 'Addition from the inside'
       PROGRAM CALC

       TESTCASE 'the counter goes up by one'
           PERFORM 4000-INC
           EXPECT WS-COUNT TO BE NUMERIC 1
"""

NOPROC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPROC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                      PIC X.
"""

MISSCOPY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MISSCOPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY NOSUCH.
       PROCEDURE DIVISION.
       0000-MAIN.
           GOBACK.
"""

TWOPROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONE.
       PROCEDURE DIVISION.
       0000-MAIN.
           GOBACK.
       END PROGRAM ONE.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWO.
       PROCEDURE DIVISION.
       0000-MAIN.
           GOBACK.
       END PROGRAM TWO.
"""


READONLY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READONLY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INFILE"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC                    PIC X(4).
       WORKING-STORAGE SECTION.
       01  WS-EOF                    PIC X VALUE "N".
           88  WS-AT-END             VALUE "Y".
       01  WS-COUNT                  PIC 9(4) VALUE ZERO.
       01  WS-LAST                   PIC X(4).
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT IN-FILE
           PERFORM 1000-READ
           PERFORM UNTIL WS-AT-END
               ADD 1 TO WS-COUNT
               MOVE IN-REC TO WS-LAST
               PERFORM 1000-READ
           END-PERFORM
           CLOSE IN-FILE
           STOP RUN.
       1000-READ.
           READ IN-FILE
               AT END SET WS-AT-END TO TRUE
           END-READ.
       2000-PLAIN.
           READ IN-FILE.
"""

SUITE_READONLY = """\
       TESTSUITE TSTREADO 'READ without NOT AT END and a plain READ'
       PROGRAM READONLY

       BEFORE-EACH
           MOVE "N" TO WS-EOF
           MOVE ZERO TO WS-COUNT
       END-BEFORE

       TESTCASE 'two records and end of file'
           MOCK FILE IN-FILE
               ON READ
                   EVALUATE CBLT-READ-COUNT
                       WHEN 1 MOVE "AAAA" TO IN-REC
                       WHEN 2 MOVE "BBBB" TO IN-REC
                       WHEN OTHER SET CBLT-AT-END TO TRUE
                   END-EVALUATE
           END-MOCK
           RUN
           EXPECT WS-COUNT TO BE NUMERIC 2
           EXPECT WS-LAST TO BE 'BBBB'
           VERIFY READ IN-FILE HAPPENED 3 TIMES

       TESTCASE 'mocked file without blocks'
           MOCK FILE IN-FILE
           END-MOCK
           RUN
           EXPECT WS-COUNT TO BE NUMERIC 0

       TESTCASE 'READ without phrases'
           MOCK FILE IN-FILE
               ON READ
                   MOVE "CCCC" TO IN-REC
           END-MOCK
           PERFORM 2000-PLAIN
           EXPECT IN-REC TO BE 'CCCC'
"""


def suite_in(cases, head="       PROGRAM CALC\n"):
    return "       TESTSUITE TSTCALCI 'Addition from the inside'\n" + head + "\n" + cases


def long_line(n):
    """Valid COBOL line in area B, padded with filler text up to column n
    (73-80 is the identification area, which the compiler ignores)."""
    base = "           ADD 1 TO WS-COUNT."
    return base.ljust(72) + "X" * (n - 72) + "\n"


# ------------------------------------------------------------- scenarios
class Project:
    def __init__(self, root):
        self.root = root

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def config(self, mutate):
        path = os.path.join(self.root, "cblt.json")
        cfg = json.load(open(path, encoding="utf-8"))
        mutate(cfg)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)

    def profile_from(self, name, base, **changes):
        def mutate(cfg):
            cfg.setdefault("profiles", {})[name] = dict(changes, extends=base)
        self.config(mutate)

    def fake_ai(self, answer):
        """Fake command for suggest: ignores the prompt and returns a fixed text."""
        self.write("answer.txt", answer)
        path = self.write("ai.sh", "#!/bin/sh\ncat \"$(dirname \"$0\")/answer.txt\"\n")
        os.chmod(path, 0o755)
        return path


def base_project(p):
    p.write("src/CALC.cbl", CALC)
    p.write("tests/CALC.cblt", SUITE_EXT)


SCENARIOS = {}


def scenario(code, title, args=("test",), rc=None, expect=(), absent=(), env=None):
    """Registers a scenario: `setup(p)` prepares the project; then the CLI runs
    with `args`, and `rc` and every text in `expect` are required."""
    def deco(setup):
        SCENARIOS[code] = dict(code=code, title=title, setup=setup, args=list(args), rc=rc,
                               expect=list(expect), absent=list(absent), env=env or {})
        return setup
    return deco


# --- happy path ----------------------------------------------------------
@scenario("OK-EXT", "minimal project, external suite", rc=0,
          expect=("Cases: 1  Asserts: 1  Failures: 0  Skipped: 0  Errors: 0", "PASS  two plus three is five"))
def ok_ext(p):
    base_project(p)


@scenario("OK-IN", "in-program suite on a paragraph", rc=0,
          expect=("Cases: 2  Asserts: 2  Failures: 0", "PASS  the counter goes up by one"))
def ok_in(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", SUITE_IN)


@scenario("OK-COV", "portable coverage of the minimal project", args=("test", "--coverage"), rc=0,
          expect=("portable coverage", "src/CALC.cbl  (CALC)", "1000-ADD", "LCOV: build/lcov.info"))
def ok_cov(p):
    """The map the reports are built from says which format it is in, like
    the other JSON files the CLI leaves in build/."""
    base_project(p)
    p.write("tests/CALCIN.cblt", SUITE_IN)
    subprocess.run([*CLI, "test", "--coverage"], cwd=p.root, capture_output=True, text=True, timeout=600)
    with open(os.path.join(p.root, "build", "cov", "map.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["schema"] == 1 and doc["cobalto"], {k: doc[k] for k in doc if k != "programs"}
    assert list(doc["programs"]) == ["CALC"] and doc["programs"]["CALC"]["units"], list(doc["programs"])


@scenario("FAIL", "an EXPECT that fails: FAIL with expected and actual, exit 1", rc=1,
          expect=("FAIL  two plus three is five", "expected [6", "actual [5", "Failures: 1"))
def fail_case(p):
    base_project(p)
    p.write("tests/CALC.cblt", SUITE_EXT.replace("NUMERIC 5", "NUMERIC 6"))


@scenario("SPACES", "a program whose file name has a space compiles and runs, with and without coverage",
          args=("test", "--coverage"), rc=0,
          expect=("Cases: 1  Asserts: 1  Failures: 0  Skipped: 0  Errors: 0", "src/CALC V2.cbl  (CALC)"),
          absent=("CBLT-E", "CBLT-W305"))
def spaces(p):
    base_project(p)
    os.rename(os.path.join(p.root, "src", "CALC.cbl"), os.path.join(p.root, "src", "CALC V2.cbl"))


EDGE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EDGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                      PIC 9(4) VALUE 0.
       01  WS-N                      PIC 9(4) VALUE 0.
       01  WS-HITS                   PIC 9(4) VALUE 0.
       01  WS-TEXT                   PIC X(12) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM COPY-RECORD
           GOBACK.
       COPY-RECORD.
           MOVE "say ""hi"" x" TO WS-TEXT
           DISPLAY "SAVED. COPY IT"
           PERFORM UNTIL WS-N > 9
               IF WS-N = 3
                   EXIT PERFORM
               END-IF
               ADD 1 TO WS-N
           END-PERFORM
           IF WS-A = 1 OR ZERO
               ADD 1 TO WS-HITS.
           IF WS-A = 1 OR > 8 OR 5
               ADD 10 TO WS-HITS.
           IF NOT WS-A = 1 OR 2
               ADD 100 TO WS-HITS.
"""

EDGE_SUITE = """\
       TESTSUITE TSTEDGE 'Constructs the rewriter must leave compilable'
       PROGRAM EDGE

       TESTCASE 'with zero: the loop is left at 3 and two conditions hold'
           MOVE 0 TO WS-A
           PERFORM COPY-RECORD
           EXPECT WS-N TO BE NUMERIC 3
           EXPECT WS-HITS TO BE NUMERIC 101
           EXPECT WS-TEXT TO BE 'say "hi" x'

       TESTCASE 'with seven: only the relation with the last operator holds'
           MOVE 0 TO WS-N
           MOVE 0 TO WS-HITS
           MOVE 7 TO WS-A
           PERFORM COPY-RECORD
           EXPECT WS-HITS TO BE NUMERIC 110
"""


@scenario("EDGE", "EXIT PERFORM, a doubled quote, COPY inside a name and a literal, and abbreviated "
                  "conditions with ZERO, a changed operator and NOT: the instrumented copy compiles and counts them",
          args=("test", "--coverage"), rc=0,
          expect=("Cases: 2  Asserts: 4  Failures: 0  Skipped: 0  Errors: 0", "src/EDGE.cbl  (EDGE)"),
          absent=("CBLT-E", "CBLT-W305"))
def edge(p):
    p.write("src/EDGE.cbl", EDGE)
    p.write("tests/EDGE.cblt", EDGE_SUITE)


# --- structured output: --json, results.json, --version ---------------------
@scenario("JSON", "test --json: the run model on standard output, equal to build/results.json",
          args=("test", "--json"), rc=1,
          expect=('"schema": 1', '"failed_asserts": 1', '"kind": "interface"', '"status": "failed"',
                  "FAIL  two plus three is five"))
def json_run(p):
    """Standard output is only the JSON (the console goes to stderr), it carries
    the expected and the actual value of the assert that failed, and it matches
    results.json."""
    fail_case(p)
    r = subprocess.run([*CLI, "test", "--json"], cwd=p.root, capture_output=True, text=True,
                       timeout=600)
    run = json.loads(r.stdout)
    case = run["suites"][0]["cases"][0]
    failed = [a for a in case["asserts"] if a["status"] == "failed"]
    assert run["ok"] is False and run["totals"]["cases"] == 1, run["totals"]
    assert failed and failed[0]["expected"].startswith("6") and failed[0]["actual"].startswith("5"), failed
    assert "FAIL  two plus three is five" in r.stderr and "FAIL" not in r.stdout
    with open(os.path.join(p.root, "build", "results.json"), encoding="utf-8") as fh:
        assert json.load(fh) == run, "results.json differs from the --json output"


@scenario("JSON-ERR", "test --json with a DSL error: the error also comes out as JSON, exit 2",
          args=("test", "--json"), rc=2,
          expect=('"code": "CBLT-E200"', '"schema": 1', "CBLT-E200: DSL syntax error"))
def json_error(p):
    base_project(p)
    p.write("tests/CALC.cblt", SUITE_EXT.replace("EXPECT WS-SUM TO BE NUMERIC 5", "EXPECT WS-SUM TO SMELL LIKE 5"))


@scenario("JSON-E201", "test --json with a compile error: each error with its file and line, or the compiler "
          "output when the profile cannot map it",
          args=("test", "--json"), rc=2,
          expect=('"code": "CBLT-E202"', '"details": [', '"code": "CBLT-E201"', '"file": "tests/CALC.cblt"',
                  '"line": 12', '"generated": "build/', "CBLT-E201: compile error in tests/CALC.cblt:12"))
def json_e201(p):
    """The location of a compile error reaches the JSON and the JUnit
    report, not only the console. With an error_regex that matches nothing,
    the compiler's own output takes its place, whichever stream it wrote:
    the stdout profile reports on standard output and leaves a notice on
    standard error."""
    e201(p)
    p.profile_from("unmapped", "gnucobol", error_regex="^NEVER$")
    p.profile_from("stdout", "gnucobol", compile="echo 'NOTICE: license checked' >&2; cobc -x -std=default "
                   "-I {lib} {incl} -o {exe} {driver} {lib}/CBLTLIB.cbl {tests} {sources} 2>&1")
    p.profile_from("stdout-unmapped", "stdout", error_regex="^NEVER$")

    def error_of(profile):
        r = subprocess.run([*CLI, "test", "--profile", profile, "--json"], cwd=p.root, capture_output=True,
                           text=True, timeout=600)
        assert r.returncode == 2, (profile, r.returncode, r.stderr)
        return json.loads(r.stdout)["error"], r.stderr

    error, console = error_of("unmapped")
    assert "details" not in error and "WS-NOSUCH" in error["output"] and "WS-NOSUCH" in console, error
    error, console = error_of("stdout")
    assert [(d["file"], d["line"]) for d in error["details"]] == [("tests/CALC.cblt", 12)], error
    error, console = error_of("stdout-unmapped")
    assert "WS-NOSUCH" in error["output"] and "NOTICE: license checked" in error["output"], error
    assert "WS-NOSUCH" in console and "NOTICE: license checked" in console, console
    r = subprocess.run([*CLI, "test"], cwd=p.root, capture_output=True, text=True, timeout=600)
    with open(os.path.join(p.root, "build", "junit.xml"), encoding="utf-8") as fh:
        junit = fh.read()
    assert r.returncode == 2 and "CBLT-E201: compile error in tests/CALC.cblt:12" in junit, junit


@scenario("JSON-COV", "test --coverage --json: the coverage of the program inside the model",
          args=("test", "--coverage", "--json"), rc=0,
          expect=('"coverage": [', '"program": "CALC"', '"statements": {', '"missed_lines": ['))
def json_coverage(p):
    base_project(p)


@scenario("PARSE-JSON", "parse --json: what the parser understands of the program, as data",
          args=("parse", "src/CALC.cbl", "--json"), rc=0,
          expect=('"program_ids": [', '"CALC"', '"paragraphs": [', '"schema": 1'))
def parse_json(p):
    base_project(p)


@scenario("PROFILES", "profiles --json: the built-in profiles plus the project's, which only state what changes",
          args=("test", "--profile", "strict"), rc=0,
          expect=("profile: strict", "Cases: 1  Asserts: 1  Failures: 0"))
def profiles_json(p):
    """A profile named like a built-in one overrides only the fields it
    states; one with "extends" starts from another; one with a field written
    as {"file": NAME} takes the text of a file next to cblt.json."""
    base_project(p)
    p.write("run.txt", "{exe}\n")
    p.config(lambda cfg: cfg.update(profiles={
        "gnucobol": {"description": "Site compiler"},
        "strict": {"extends": "gnucobol", "description": "Strict", "run": {"file": "run.txt"}}}))
    r = subprocess.run([*CLI, "profiles", "--json"], cwd=p.root, capture_output=True, text=True, timeout=600)
    doc = json.loads(r.stdout)
    by_name = {x["name"]: x for x in doc["profiles"]}
    assert doc["schema"] == 1 and doc["default"] == "gnucobol", doc
    assert by_name["gnucobol"]["description"] == "Site compiler", by_name["gnucobol"]
    assert by_name["strict"] == {"name": "strict", "kind": "local", "description": "Strict"}, by_name["strict"]
    assert by_name["vms-vsi-cobol"]["kind"] == "remote" and "gnucobol-ibm" in by_name, sorted(by_name)
    assert " * gnucobol" in r.stderr, r.stderr


@scenario("LIST", "list --json: suites and test cases as the CLI reads them; a broken file does not hide the others",
          args=("list",), rc=2, expect=("TSTCALC", "tests/CALC.cblt  (1 case(s))", "CBLT-E200", "BAD.cblt:4"))
def list_json(p):
    base_project(p)
    p.write("tests/BAD.cblt", "       TESTSUITE TSTBAD 'broken'\n\n\n           EXPECT T-SUM TO BE NUMERIC 5\n")
    p.write("tests/TSTOLD.cbl", "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TSTOLD.\n")
    r = subprocess.run([*CLI, "list", "--json"], cwd=p.root, capture_output=True, text=True, timeout=600)
    doc = json.loads(r.stdout)
    by_id = {s["id"]: s for s in doc["suites"]}
    assert doc["schema"] == 1 and sorted(by_id) == ["TSTCALC", "TSTOLD"], doc
    calc = by_id["TSTCALC"]
    assert calc["dsl"] and calc["line"] == 1 and calc["file"] == "tests/CALC.cblt", calc
    assert [c["name"] for c in calc["cases"]] == ["two plus three is five"] and calc["cases"][0]["ignored"] is False, calc
    assert calc["cases"][0]["line"] > 1, calc
    assert by_id["TSTOLD"] == {"id": "TSTOLD", "file": "tests/TSTOLD.cbl", "line": 2, "description": "",
                               "dsl": False, "program": None, "cases": []}, by_id["TSTOLD"]
    assert [(e["file"], e["line"], e["code"]) for e in doc["errors"]] == [("tests/BAD.cblt", 4, "CBLT-E200")], doc["errors"]


@scenario("VERSION", "--version shows the CLI version", args=("--version",), rc=0, expect=("Cobalto ",))
def version(p):
    pass


@scenario("FELL-OFF", "a GO TO takes the flow out of the executed paragraph: the test case fails, the next one still runs", rc=1,
          expect=("FAIL  jumps out of the paragraph", "actual [FELL OFF THE END OF THE PROGRAM]",
                  "PASS  the next test case still runs",
                  "Cases: 3  Asserts: 3  Failures: 1  Skipped: 0  Errors: 0"))
def fell_off(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'jumps out of the paragraph'
           PERFORM 5000-JUMP
           EXPECT WS-COUNT TO BE NUMERIC 0

       TESTCASE 'the next test case still runs'
           PERFORM 4000-INC
           EXPECT WS-COUNT TO BE NUMERIC 1
"""))


@scenario("MOCK-READ", "MOCK FILE on a READ without NOT AT END, without INTO and without FILE STATUS", rc=0,
          expect=("Cases: 3  Asserts: 5  Failures: 0  Skipped: 0  Errors: 0", "PASS  READ without phrases"))
def mock_read(p):
    p.write("src/READONLY.cbl", READONLY)
    p.write("tests/READONLY.cblt", SUITE_READONLY)


# --- E1xx: project and profiles -----------------------------------------
@scenario("E100", "no suite matches --filter", args=("test", "--filter", "ZZZ"), rc=2,
          expect=("CBLT-E100",))
def e100(p):
    base_project(p)


@scenario("E101", "profile that does not exist", args=("test", "--profile", "nosuch"), rc=2,
          expect=("CBLT-E101", "nosuch", "available: gnucobol"))
def e101(p):
    base_project(p)


@scenario("E102", "remote profile without a host", args=("test", "--profile", "vms-vsi-cobol"), rc=2,
          expect=("CBLT-E102", "vms-vsi-cobol"))
def e102(p):
    base_project(p)


@scenario("E103", "cblt.json is missing", args=("--config", "other.json", "test"), rc=2,
          expect=("CBLT-E103", "other.json"))
def e103(p):
    base_project(p)


@scenario("E104", "the upload to the host fails", args=("test", "--profile", "bad-upload"), rc=2,
          expect=("CBLT-E104",))
def e104(p):
    base_project(p)
    p.profile_from("bad-upload", "remote-sim", upload="false")


@scenario("E105", "the remote build does not leave the marker", args=("test", "--profile", "no-marker"), rc=2,
          expect=("CBLT-E105", "CBLT-BUILD-OK"))
def e105(p):
    base_project(p)
    p.profile_from("no-marker", "remote-sim", invoke="true")


@scenario("E106", "report without the --generate-only manifest", args=("report", "--results", "CBLT_RESULTS.DAT"), rc=2,
          expect=("CBLT-E106", "cblt-manifest.json"))
def e106(p):
    base_project(p)


# Screen of a VMS terminal: DCL echoes (SET VERIFY), a batch queue notice and
# a line with an indented '$' that is program output and must be kept.
VMS_SCREEN = """\
$ @CBLT_RUN.COM
$ DEFINE/USER_MODE CBLT_RESULTS CBLT_RESULTS.DAT
$ RUN CBLTDRV.EXE
CBLT-T|TSTCALC
CBLT-C|two plus three is five
   $5.00 edited total
Job CALC (queue SYS$BATCH, entry 7) completed
$ SET NOVERIFY
CBLT-RUN-OK
"""


def returned_records(p):
    """Runs the suite with remote-sim to get a manifest and results, and
    returns the records padded to 200, as the driver leaves them."""
    base_project(p)
    r = subprocess.run([*CLI, "test", "--profile", "remote-sim"], cwd=p.root,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    raw = open(os.path.join(p.root, "build", "cblt-results.dat"), "rb").read().decode("latin-1")
    recs = [raw[i:i + 200] for i in range(0, len(raw), 200)] if "\n" not in raw else raw.splitlines()
    return [x.ljust(200) for x in recs if x.strip()]


def write_returned(p, rel, lines, final_newline=True):
    """Writes a file the way it ends up when copied by hand as text on Windows:
    CRLF line endings, with or without a final newline."""
    with open(os.path.join(p.root, rel), "w", encoding="latin-1", newline="") as fh:
        fh.write("\r\n".join(lines) + ("\r\n" if final_newline else ""))


@scenario("REPORT", "report reads results and screen output returned by hand from the host",
          args=("report", "--results", "returned.dat", "--output", "screen.txt", "-v"), rc=0,
          expect=("results returned from the host", "PASS  two plus three is five", "> " + "   $5.00 edited total",
                  "Cases: 1  Asserts: 1  Failures: 0  Skipped: 0  Errors: 0"),
          absent=("CBLT-E", "W301", "W307", "> $", "> Job "))
def report_ok(p):
    """The file comes back with one line per record, CRLF and without the
    trailing spaces; the screen has DCL echoes and a batch queue notice."""
    write_returned(p, "returned.dat", [x.rstrip() for x in returned_records(p)])
    p.write("screen.txt", VMS_SCREEN)


@scenario("REPORT-VMS", "report on content copied from an OpenVMS terminal (CRLF, padding up to 200, no final newline, last record of 199 bytes, padded markers)",
          args=("report", "--results", "returned.dat", "--output", "screen.txt", "-v"), rc=0,
          expect=("PASS  two plus three is five", "> result: 000000500",
                  "Cases: 1  Asserts: 1  Failures: 0  Skipped: 0  Errors: 0  (binary exit: 0)"),
          absent=("CBLT-E", "W301", "W307"))
def report_vms(p):
    """The way the content comes back from VSI COBOL on OpenVMS, reproduced
    with the data of this suite: the records keep the padding up to 200 except
    the last one, which is left at 199 and without a final newline; the screen
    markers carry the padding of the COBOL field, with no DCL echoes; and VSI
    COBOL displays a field with an implied decimal point without the point."""
    recs = returned_records(p)
    write_returned(p, "returned.dat", recs[:-1] + [recs[-1][:199]], final_newline=False)
    write_returned(p, "screen.txt", ["CBLT-T|" + "TSTCALC".ljust(30),
                                       "CBLT-C|" + "two plus three is five".ljust(60),
                                       "result: 000000500", "CBLT-RUN-OK"])


@scenario("W307", "report warns when the copy from the terminal cut the lines (column 109)",
          args=("report", "--results", "returned.dat"), rc=0,
          expect=("CBLT-W307: 2 assert record(s) arrived cut at column 109",
                  "PASS  two plus three is five",
                  "Cases: 1  Asserts: 1  Failures: 0  Skipped: 0  Errors: 0"),
          absent=("CBLT-E", "W301"))
def w307(p):
    """The other way the content comes back from that system: every line cut
    at column 109 and the last one without padding. The totals and the short
    values read fine, the description of each assert is lost and the report
    warns about it."""
    recs = returned_records(p)
    write_returned(p, "returned.dat", [x[:109] for x in recs[:-1]] + [recs[-1].rstrip()],
                   final_newline=False)


# --- E2xx: DSL, build, 80 columns ----------------------------------------
@scenario("E200", "unrecognized EXPECT, with file and line", rc=2,
          expect=("CBLT-E200", "tests/CALC.cblt:12", "unrecognized EXPECT"))
def e200(p):
    base_project(p)
    p.write("tests/CALC.cblt", SUITE_EXT.replace("EXPECT WS-SUM TO BE NUMERIC 5", "EXPECT WS-SUM TO SMELL LIKE 5"))


@scenario("E200-NOT", "EXPECT NOT with a numeric form is an error, not a check that always passes", rc=2,
          expect=("CBLT-E200", "tests/CALC.cblt:12", "NOT is only supported"))
def e200_not(p):
    base_project(p)
    p.write("tests/CALC.cblt", SUITE_EXT.replace("EXPECT WS-SUM TO BE NUMERIC 5", "EXPECT WS-SUM NOT TO BE NUMERIC 9"))


@scenario("E200-SUITE", "file without TESTSUITE", rc=2, expect=("CBLT-E200", "TESTSUITE is missing"))
def e200_suite(p):
    base_project(p)
    p.write("tests/CALC.cblt", "       TESTCASE 'no header'\n           EXPECT WS-X TO BE 'A'\n")


@scenario("E201", "compile error mapped to the line of the .cblt", rc=2,
          expect=("CBLT-E201", "tests/CALC.cblt:12", "CBLT-E202"))
def e201(p):
    base_project(p)
    p.write("tests/CALC.cblt", SUITE_EXT.replace("           EXPECT WS-SUM TO BE NUMERIC 5",
                                                "           MOVE 1 TO WS-NOSUCH\n           EXPECT WS-SUM TO BE NUMERIC 5"))


@scenario("E203", "source with a line longer than 80 columns in a profile with pad80",
          args=("test", "--profile", "remote-sim"), rc=2, expect=("CBLT-E203", "src/CALC.cbl:"))
def e203(p):
    base_project(p)
    p.write("src/CALC.cbl", CALC.replace("           ADD 1 TO WS-COUNT.\n", long_line(90)))


@scenario("W303", "text in columns 73-80: warns and continues", args=("test", "--profile", "remote-sim"), rc=0,
          expect=("CBLT-W303", "columns 73-80", "Cases: 1  Asserts: 1  Failures: 0"))
def w303(p):
    base_project(p)
    p.write("src/CALC.cbl", CALC.replace("           ADD 1 TO WS-COUNT.\n", long_line(78)))


# --- E3xx / W30x: execution ----------------------------------------------
@scenario("E300", "the executable leaves no results file", args=("test", "--profile", "no-run"), rc=2,
          expect=("CBLT-E300",))
def e300(p):
    base_project(p)
    p.profile_from("no-run", "gnucobol", run="true")


@scenario("ERR-REPORT", "a run that stops with exit code 2 writes the error to junit.xml, sonar-tests.xml and "
          "results.json, and leaves the coverage reports as they were",
          args=("test", "--coverage"), rc=2, expect=("CBLT-E201", "CBLT-E202"))
def err_reports(p):
    """None of the reports a CI step or a script reads is left from an
    earlier run: after a compile error they hold the error, the same model
    --json writes. The coverage reports keep the last run with coverage, and
    --no-run, which is not a test run, does not touch any report."""
    build = os.path.join(p.root, "build")

    def run(*args, rc):
        r = subprocess.run([*CLI, *args], cwd=p.root, capture_output=True, text=True, timeout=600)
        assert r.returncode == rc, (args, r.returncode, r.stdout + r.stderr)
        return r

    def read(name):
        with open(os.path.join(build, name), encoding="utf-8") as fh:
            return fh.read()

    base_project(p)
    run("test", "--coverage", rc=0)
    passed = read("results.json")
    coverage = [read(n) for n in ("lcov.info", "coverage.xml", "sonar-coverage.xml")]
    run("test", "--no-run", rc=0)
    assert read("results.json") == passed, "--no-run changed results.json"
    good = SUITE_EXT
    e201(p)
    r = run("test", "--coverage", "--json", rc=2)
    doc = json.loads(read("results.json"))
    assert json.loads(r.stdout) == doc, "results.json differs from the --json output"
    assert doc["ok"] is False and doc["error"]["code"] == "CBLT-E202" and doc["suites"] == [], doc
    assert 'testcase name="CBLT-E202" classname="cobalto"' in read("junit.xml"), read("junit.xml")
    assert "<file" not in read("sonar-tests.xml"), read("sonar-tests.xml")
    assert [read(n) for n in ("lcov.info", "coverage.xml", "sonar-coverage.xml")] == coverage
    p.write("tests/CALC.cblt", good)
    run("test", rc=0)
    run("report", "--results", "CBLT_RESULTS.DAT", rc=2)
    assert json.loads(read("results.json"))["error"]["code"] == "CBLT-E106"
    e201(p)


@scenario("ABORT", "a suite aborts: ERROR, the next one never starts (W301), exit 1", rc=1,
          expect=("ERROR", "CBLT-W301", "1 test(s) never started", "Errors: 2"))
def abort(p):
    base_project(p)
    p.write("tests/A.cblt", """\
       TESTSUITE TSTABORT 'Aborts'

       TESTCASE 'calls a missing program without ON EXCEPTION'
           CALL "NOSUCH"
""")
    p.write("tests/Z.cblt", """\
       TESTSUITE TSTZ 'Never starts'

       TESTCASE 'never gets to run'
           CONTINUE
""")
    os.remove(os.path.join(p.root, "tests", "CALC.cblt"))


@scenario("W308", "a failure after the log of the suite is full is an error, not a pass", rc=1,
          expect=("PASS  more asserts than the log keeps  (499 asserts)",
                  "ERROR 1 failed assert(s) have no detail",
                  "CBLT-W308: TSTCALC ran 506 assert(s) and 1 failed, but the detail of only 499 arrived",
                  "Cases: 1  Asserts: 506  Failures: 1  Skipped: 0  Errors: 1"))
def w308(p):
    """The log of a suite keeps 500 entries: the test case and 499 asserts.
    The failure is the last of the asserts that did not fit."""
    base_project(p)
    p.write("tests/CALC.cblt", """\
       TESTSUITE TSTCALC 'More asserts than the log keeps'

       WORKING-STORAGE SECTION.
       01  WS-A                      PIC X(3) VALUE "ABC".

       TESTCASE 'more asserts than the log keeps'
""" + "           EXPECT WS-A TO BE 'ABC'\n" * 505 + "           EXPECT WS-A TO BE 'XYZ'\n")


@scenario("W302", "PROGRAM-ID of a legacy test repeated in a DSL suite", rc=0,
          expect=("CBLT-W302", "TSTCALC", "is not compiled", "Cases: 1  Asserts: 1  Failures: 0"))
def w302(p):
    base_project(p)
    p.write("tests/TSTCALC.cbl", """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSTCALC.
       PROCEDURE DIVISION.
       0000-MAIN.
           GOBACK.
""")


# --- E4xx / W30x: in-program mode ----------------------------------------
@scenario("E400", "PROGRAM that does not exist", rc=2, expect=("CBLT-E400", "NOSUCH", "tests/CALCIN.cblt"))
def e400(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("       TESTCASE 'x'\n           CONTINUE\n", head="       PROGRAM NOSUCH\n"))


@scenario("E401", "MOCK PARAGRAPH of a paragraph that does not exist", rc=2, expect=("CBLT-E401", "9999-NOPE", "CALC"))
def e401(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'paragraph that does not exist'
           MOCK PARAGRAPH 9999-NOPE
               CONTINUE
           END-MOCK
           PERFORM 4000-INC
"""))


@scenario("E402", "MOCK CALL of a program that the program does not call", rc=2, expect=("CBLT-E402", "NOPE", "CALC"))
def e402(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'call that does not exist'
           MOCK CALL 'NOPE'
               CONTINUE
           END-MOCK
           PERFORM 4000-INC
"""))


@scenario("E403", "MOCK FILE of an undeclared file", rc=2, expect=("CBLT-E403", "NOPE-FILE", "CALC"))
def e403(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'file that does not exist'
           MOCK FILE NOPE-FILE
               ON READ
                   SET CBLT-AT-END TO TRUE
           END-MOCK
           PERFORM 2000-COUNT
"""))


@scenario("E403-OP", "VERIFY of an operation that the program does not perform on the file", rc=2,
          expect=("CBLT-E403", "CUST-FILE"))
def e403_op(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'the program never writes'
           MOCK FILE CUST-FILE
               ON READ
                   SET CBLT-AT-END TO TRUE
           END-MOCK
           PERFORM 2000-COUNT
           VERIFY WRITE CUST-FILE NEVER HAPPENED
"""))


@scenario("E404", "program under test with a copybook that does not exist", rc=2,
          expect=("CBLT-E404", "NOSUCH"))
def e404(p):
    base_project(p)
    p.write("src/MISSCOPY.cbl", MISSCOPY)
    p.write("tests/MISS.cblt", "       TESTSUITE TSTMISS 'x'\n       PROGRAM MISSCOPY\n\n       TESTCASE 'x'\n           CONTINUE\n")


@scenario("E405", "MOCK PARAGRAPH of a paragraph with NEXT SENTENCE", rc=2, expect=("CBLT-E405", "3000-SKIP"))
def e405(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'cannot be mocked'
           MOCK PARAGRAPH 3000-SKIP
               CONTINUE
           END-MOCK
           PERFORM 4000-INC
"""))


@scenario("E406", "program without PROCEDURE DIVISION", rc=2, expect=("CBLT-E406", "NOPROC", "PROCEDURE DIVISION"))
def e406(p):
    base_project(p)
    p.write("src/NOPROC.cbl", NOPROC)
    p.write("tests/NOPROC.cblt", "       TESTSUITE TSTNOPROC 'x'\n       PROGRAM NOPROC\n\n       TESTCASE 'x'\n           CONTINUE\n")


@scenario("E407", "MOCK in a suite without PROGRAM", rc=2,
          expect=("CBLT-E200", "are only valid in a suite with PROGRAM"))
def e407(p):
    base_project(p)
    p.write("tests/CALC.cblt", SUITE_EXT.replace("           MOVE 2 TO WS-A\n",
                                                "           MOCK CALL 'CALC'\n               MOVE 9 TO WS-SUM\n           END-MOCK\n           MOVE 2 TO WS-A\n"))


@scenario("W304", "MOCK SQL in a program without EXEC SQL: warns and continues", rc=0,
          expect=("CBLT-W304", "EXEC SQL", "Cases: 2  Asserts: 2  Failures: 0"))
def w304(p):
    base_project(p)
    p.write("tests/CALCIN.cblt", suite_in("""\
       TESTCASE 'mocked sql without sql'
           MOCK SQL
               CONTINUE
           END-MOCK
           PERFORM 4000-INC
           EXPECT WS-COUNT TO BE NUMERIC 1
"""))


@scenario("W305", "source with two programs: not instrumented for coverage", args=("test", "--coverage"), rc=0,
          expect=("CBLT-W305", "TWOPROG.cbl", "the original is compiled"))
def w305(p):
    base_project(p)
    p.write("src/TWOPROG.cbl", TWOPROG)


@scenario("W306", "coverage requested but no instrumented program ran", args=("test", "--coverage"), rc=0,
          expect=("CBLT-W306",))
def w306(p):
    base_project(p)
    p.write("tests/CALC.cblt", """\
       TESTSUITE TSTCALC 'Calls nothing'

       WORKING-STORAGE SECTION.
       01  WS-X                      PIC X VALUE "A".

       TESTCASE 'only checks its own field'
           EXPECT WS-X TO BE 'A'
""")


# --- E5xx: debug ---------------------------------------------------------
@scenario("E500", "debug of a suite that does not exist", args=("debug", "--suite", "NOPE"), rc=2,
          expect=("CBLT-E500", "NOPE", "available: TSTCALC"))
def e500(p):
    base_project(p)


@scenario("E501", "debug with a remote profile", args=("debug", "--suite", "TSTCALC", "--profile", "remote-sim"), rc=2,
          expect=("CBLT-E501", "remote-sim"))
def e501(p):
    base_project(p)


# --- E6xx / W60x: suggest -------------------------------------------------
NO_KEY = {"ANTHROPIC_API_KEY": ""}


@scenario("E600", "suggest without a backend: no key and no command in the PATH",
          args=("suggest", "--program", "CALC", "--backend", "auto", "--command", "/nosuch/ai", "--rounds", "1"),
          rc=2, expect=("CBLT-E600",), env=NO_KEY)
def e600(p):
    base_project(p)


@scenario("E601", "suggest with a command that does not exist",
          args=("suggest", "--program", "CALC", "--backend", "command", "--command", "/nosuch/ai", "--rounds", "1"),
          rc=2, expect=("CBLT-E601", "not found"), env=NO_KEY)
def e601(p):
    base_project(p)


@scenario("E602", "suggest with an answer that contains no suite", rc=2,
          expect=("CBLT-E602", "response.txt"), env=NO_KEY)
def e602(p):
    base_project(p)
    cmd = p.fake_ai("Sorry, I cannot help with that.\n")
    SCENARIOS["E602"]["args"] = ["suggest", "--program", "CALC", "--backend", "command", "--command", cmd, "--rounds", "1"]


@scenario("W601", "suggest: no round compiles, exit 1", rc=1,
          expect=("CBLT-W601", "no round compiled"), env=NO_KEY)
def w601(p):
    base_project(p)
    cmd = p.fake_ai("""\
       TESTSUITE CALCAI 'Proposal'

       WORKING-STORAGE SECTION.
       01  T-A                       PIC 9(4).

       TESTCASE 'with a broken EXPECT'
           MOVE 1 TO T-A
           EXPECT T-A TO SMELL LIKE 1
""")
    SCENARIOS["W601"]["args"] = ["suggest", "--program", "CALC", "--backend", "command", "--command", cmd, "--rounds", "1"]


@scenario("W602", "suggest: the best round has failures", rc=0,
          expect=("CBLT-W602", "1 failure(s)", "Draft:"), env=NO_KEY)
def w602(p):
    base_project(p)
    cmd = p.fake_ai("""\
       TESTSUITE CALCAI 'Proposal'

       WORKING-STORAGE SECTION.
       01  T-A                       PIC 9(4).
       01  T-B                       PIC 9(4).
       01  T-SUM                     PIC 9(5).

       TESTCASE 'wrong expected value'
           MOVE 2 TO T-A
           MOVE 2 TO T-B
           CALL "CALC" USING T-A T-B T-SUM
           EXPECT T-SUM TO BE NUMERIC 5
""")
    SCENARIOS["W602"]["args"] = ["suggest", "--program", "CALC", "--backend", "command", "--command", cmd, "--rounds", "1"]


# ---------------------------------------------------------------- runner
def run_scenario(sc, base_dir, keep):
    root = os.path.join(base_dir, sc["code"].lower().replace("-", "_"))
    r = subprocess.run([*CLI, "init", root], capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"cobalto init failed: {r.stderr.strip()}"
    p = Project(root)
    sc["setup"](p)
    env = dict(os.environ)
    env.update(sc["env"])
    env = {k: v for k, v in env.items() if v != "" or k not in sc["env"]}
    r = subprocess.run(CLI + sc["args"], cwd=root, capture_output=True, text=True, env=env, timeout=600)
    out = r.stdout + r.stderr
    problems = []
    if sc["rc"] is not None and r.returncode != sc["rc"]:
        problems.append(f"exit {r.returncode}, expected {sc['rc']}")
    for text in sc["expect"]:
        if text not in out:
            problems.append(f"missing '{text}'")
    for text in sc["absent"]:
        if text in out:
            problems.append(f"unexpected '{text}'")
    if problems and not keep:
        pass
    detail = "; ".join(problems)
    if problems:
        tail = "\n".join("      | " + l for l in out.strip().splitlines()[-12:])
        detail += "\n" + tail
    return not problems, detail


def main():
    ap = argparse.ArgumentParser(description="regression suite for the error catalog of the Cobalto CLI")
    ap.add_argument("codes", nargs="*", help="codes to run (all by default)")
    ap.add_argument("--keep", action="store_true", help="do not delete the temporary projects")
    ap.add_argument("--list", action="store_true", help="list the scenarios")
    ap.add_argument("-j", type=int, default=4, help="scenarios in parallel (4)")
    a = ap.parse_args()
    if a.list:
        for code, sc in SCENARIOS.items():
            print(f"  {code:10s} {sc['title']}")
        return 0
    if shutil.which("cobc") is None:
        print("cobc (GnuCOBOL) is not in the PATH", file=sys.stderr)
        return 2
    wanted = [c.upper() for c in a.codes] or list(SCENARIOS)
    unknown = [c for c in wanted if c not in SCENARIOS]
    if unknown:
        print(f"unknown scenarios: {', '.join(unknown)} (see --list)", file=sys.stderr)
        return 2
    base_dir = tempfile.mkdtemp(prefix="cblt-selftest-")
    print(f"Cobalto selftest: {len(wanted)} scenarios in {base_dir}")
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.j)) as ex:
        futures = {ex.submit(run_scenario, SCENARIOS[c], base_dir, a.keep): c for c in wanted}
        results = {}
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()
    for c in wanted:
        ok, detail = results[c]
        print(f"  {'OK  ' if ok else 'FAIL'} {c:10s} {SCENARIOS[c]['title']}" + ("" if ok else f"\n      {detail}"))
        failures += 0 if ok else 1
    if not a.keep:
        shutil.rmtree(base_dir, ignore_errors=True)
    print(f"\n{len(wanted) - failures} of {len(wanted)} scenarios passed" + (f"; {failures} failed" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
