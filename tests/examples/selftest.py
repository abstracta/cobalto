#!/usr/bin/env python3
"""Regression of the example project, kept apart from the demo.

The example project (examples/) is what a demo runs, and it fails on
purpose: two of its test cases show what a failure looks like, so
`cobalto test` ends with exit code 1 there. A build cannot tell that exit
code from a real regression. This script is what a build runs instead: it
copies the project to a temporary folder, runs it with each profile that
works on one machine and compares the outcome with expected.json: the exit
code, the totals, every test case that does not pass with its status, and
the coverage totals. It ends with 0 when the examples behave as recorded.

    python3 tests/examples/selftest.py                 (every profile, in parallel)
    python3 tests/examples/selftest.py gnucobol-ibm    (only that one)
    python3 tests/examples/selftest.py --update        (rewrites expected.json from this run)

After --update, read the diff of expected.json before committing it: it is
the statement of what the examples are supposed to do.

Needs GnuCOBOL (cobc) and Python 3.9+. Standard library only.
"""
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAMPLES = os.path.join(ROOT, "examples")
EXPECTED = os.path.join(HERE, "expected.json")
# the CLI of this working copy, without installing it
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join(
    x for x in (os.path.join(ROOT, "src"), os.environ.get("PYTHONPATH")) if x))

# Profile -> extra arguments. Portable coverage everywhere except with the
# gcov profile, which measures coverage its own way.
PROFILES = {
    "gnucobol": ["--coverage"],
    "gnucobol-ibm": ["--coverage"],
    "gnucobol-mf": ["--coverage"],
    "gnucobol-coverage": [],
    "remote-sim": ["--coverage"],
}


def run_profile(profile):
    """Runs the examples with a profile in a copy of their own. Returns what
    is compared: exit code, totals, test cases that do not pass, coverage."""
    with tempfile.TemporaryDirectory(prefix="cobalto-examples-") as tmp:
        project = os.path.join(tmp, "examples")
        shutil.copytree(EXAMPLES, project, ignore=shutil.ignore_patterns("build", ".vscode"))
        r = subprocess.run([sys.executable, "-m", "cobalto", "test", "--profile", profile, "--json",
                            *PROFILES[profile]], cwd=project, env=ENV, capture_output=True, text=True, timeout=900)
    try:
        run = json.loads(r.stdout)
    except ValueError:
        return {"exit": r.returncode, "error": (r.stderr or r.stdout).strip().splitlines()[-5:]}
    if "error" in run:
        return {"exit": r.returncode, "error": run["error"]}
    not_passed = {f"{s['id']} / {c['name']}": c["status"]
                  for s in run["suites"] for c in s["cases"] if c["status"] != "passed"}
    outcome = {"exit": r.returncode, "totals": run["totals"], "not_passed": not_passed,
               "missing_suites": run["missing_suites"]}
    programs = [p for p in run.get("coverage") or [] if "statements" in p]
    if programs:
        outcome["coverage"] = {k: [sum(p[k]["hit"] for p in programs), sum(p[k]["total"] for p in programs)]
                               for k in ("paragraphs", "statements", "branches")}
    return outcome


def differences(expected, actual, path=""):
    """Readable list of what differs between two outcomes."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for key in sorted(set(expected) | set(actual)):
            where = f"{path}{key}"
            if key not in actual:
                out.append(f"{where}: expected {expected[key]!r}, missing")
            elif key not in expected:
                out.append(f"{where}: not expected, got {actual[key]!r}")
            else:
                out += differences(expected[key], actual[key], where + " > ")
        return out
    return [] if expected == actual else [f"{path.rstrip(' >')}: expected {expected!r}, got {actual!r}"]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    update = "--update" in sys.argv
    unknown = [a for a in args if a not in PROFILES]
    if unknown:
        print(f"unknown profile(s): {', '.join(unknown)}; available: {', '.join(PROFILES)}")
        return 2
    profiles = args or list(PROFILES)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(profiles)) as pool:
        outcomes = dict(zip(profiles, pool.map(run_profile, profiles)))
    expected = {}
    if os.path.exists(EXPECTED):
        with open(EXPECTED, encoding="utf-8") as fh:
            expected = json.load(fh)
    if update:
        expected.update(outcomes)
        with open(EXPECTED, "w", encoding="utf-8") as fh:
            json.dump({p: expected[p] for p in PROFILES if p in expected}, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"{EXPECTED} rewritten for: {', '.join(profiles)}")
        return 0
    failed = 0
    for profile in profiles:
        diffs = differences(expected.get(profile, {}), outcomes[profile])
        t = outcomes[profile].get("totals", {})
        summary = (f"{t.get('cases')} cases, {t.get('failed_cases')} failed, {t.get('skipped')} skipped, "
                   f"{t.get('errors')} errors, exit {outcomes[profile]['exit']}") if t else "did not run"
        print(f"  {'OK  ' if not diffs else 'FAIL'} {profile:18s} {summary}")
        for d in diffs:
            print(f"         {d}")
        failed += bool(diffs)
    print(f"\n{len(profiles) - failed} of {len(profiles)} profiles as expected")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
