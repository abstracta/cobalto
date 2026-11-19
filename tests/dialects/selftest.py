#!/usr/bin/env python3
"""Syntax check in the strict dialects of GnuCOBOL.

What runs inside the COBOL build is meant to be standard COBOL 85: the
core, the generated driver, the suites expanded from the DSL, the
in-program copies and the copies instrumented for coverage. Running only on
GnuCOBOL's default dialect would hide an extension that slipped in. This
script generates the example project with coverage and passes every one of
those sources, and the example programs themselves, through
`cobc -fsyntax-only -std=DIALECT` for each strict dialect. It expects no
errors and no warnings.

    python3 tests/dialects/selftest.py              (every dialect)
    python3 tests/dialects/selftest.py ibm-strict   (only that one)

It is a syntax check with one compiler, not a run on IBM, Micro Focus,
ACUCOBOL or RM/COBOL compilers.

Needs GnuCOBOL (cobc) and Python 3.9+. Standard library only.
"""
import concurrent.futures
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAMPLES = os.path.join(ROOT, "examples")
LIB = os.path.join(ROOT, "src", "cobalto", "lib")
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join(
    x for x in (os.path.join(ROOT, "src"), os.environ.get("PYTHONPATH")) if x))

DIALECTS = ["default", "cobol85", "cobol2002", "cobol2014", "ibm-strict", "mf-strict", "acu-strict", "rm-strict"]

# What is known not to pass, with the message it fails with and the reason.
# A source listed here that passes cleanly is reported too, so that the
# list does not outlive its reason.
EXCEPTIONS = {
    # The example program DAYCLOSE uses FUNCTION LENGTH, an intrinsic
    # function RM/COBOL does not have. It is the program under test, not
    # something Cobalto generates: its copies carry the same statement.
    ("rm-strict", "src/DAYCLOSE.cbl"): "FUNCTION 'LENGTH' unknown",
    ("rm-strict", "build/cov/DAYCLOSE.cbl"): "FUNCTION 'LENGTH' unknown",
    ("rm-strict", "build/TSTCLOSE.cbl"): "FUNCTION 'LENGTH' unknown",
}


def check(project, dialect, source):
    """(dialect, source, problem or None) for one source in one dialect."""
    path = source if os.path.isabs(source) else os.path.join(project, source)
    r = subprocess.run(["cobc", "-fsyntax-only", f"-std={dialect}", "-I", LIB, "-I", "src", path],
                       cwd=project, capture_output=True, text=True)
    output = (r.stdout + r.stderr).strip()
    known = EXCEPTIONS.get((dialect, source))
    if known:
        if known in output:
            return dialect, source, None
        return dialect, source, f"listed as an exception ({known}) but " + ("it passes" if not output else output)
    return dialect, source, output or None


def main():
    wanted = sys.argv[1:] or DIALECTS
    unknown = [d for d in wanted if d not in DIALECTS]
    if unknown:
        print(f"unknown dialect(s): {', '.join(unknown)}; available: {', '.join(DIALECTS)}")
        return 2
    with tempfile.TemporaryDirectory(prefix="cobalto-dialects-") as tmp:
        project = os.path.join(tmp, "examples")
        shutil.copytree(EXAMPLES, project, ignore=shutil.ignore_patterns("build", ".vscode"))
        r = subprocess.run([sys.executable, "-m", "cobalto", "test", "--coverage", "--generate-only"],
                           cwd=project, env=ENV, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return 2
        sources = [os.path.join(LIB, "CBLTLIB.cbl")]
        for pattern in ("build/*.cbl", "build/cov/*.cbl", "src/*.cbl", "tests/*.cbl"):
            sources += sorted(os.path.relpath(f, project) for f in glob.glob(os.path.join(project, pattern)))
        jobs = [(project, d, s) for d in wanted for s in sources]
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            results = list(pool.map(lambda j: check(*j), jobs))
    failed = 0
    for dialect in wanted:
        problems = [(s, p) for d, s, p in results if d == dialect and p]
        excepted = sum(1 for d, s in EXCEPTIONS if d == dialect)
        note = f" ({excepted} known exception(s))" if excepted else ""
        print(f"  {'OK  ' if not problems else 'FAIL'} {dialect:12s} {len(sources)} sources{note}")
        for source, problem in problems:
            print(f"         {os.path.basename(source) if os.path.isabs(source) else source}:")
            for line in problem.splitlines()[:6]:
                print(f"           {line}")
        failed += bool(problems)
    print(f"\n{len(wanted) - failed} of {len(wanted)} dialects with no errors and no warnings")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
