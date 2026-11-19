"""Cobalto (CBLT) - portable unit testing for COBOL. Runner and CLI.

  cobalto test [--profile P] [--filter SUITE] [--coverage] [--no-run]
               [--generate-only] [--host H] [--remote-dir D] [--json] [--verbose]
  cobalto report --results FILE [--output SCREEN] [--manifest M] [--json]
  cobalto debug --suite SUITE [--profile P]
  cobalto suggest --program PROGRAM [--rounds N] [--backend api|command]
                  [--model M] [--dry-run]
  cobalto init [DIR]
  cobalto list [--json]
  cobalto profiles [--json]
  cobalto parse FILE... [--json]

Flow: discover the suites (.cblt files in the DSL, or TST*.cbl programs) ->
expand the DSL to COBOL 85 -> generate the driver -> compile with the
profile -> run -> read the results file and the output -> console, JUnit
and results.json. Standard library only: runs on any machine with
Python 3.9+.

Remote profiles ("remote" field): the CLI prepares build/remote/ with the
sources and the build and run scripts generated from the profile's
templates, uploads them with "upload", runs each script through "remote" +
"invoke", brings the results file back with "fetch" and parses it like a
local profile.

report: for hosts without ssh. 'test --generate-only' leaves a manifest
(cblt-manifest.json) in build/remote/ with the profile, the results format
and the suites; someone runs the scripts on the host and returns the
results file and, optionally, the screen output; 'report' parses them with
that manifest and produces the same console, junit.xml and results.json as
'test'.

Portable coverage (--coverage, or "coverage": true in the profile): the
programs in "sources" are compiled from an instrumented copy in build/cov/
and the in-program copies add counters; the driver dumps the records
C|program|index|count to the results file, and the CLI reports by
paragraph and writes build/lcov.info, build/coverage.xml and
build/sonar-coverage.xml (SonarQube generic format). build/junit.xml,
build/sonar-tests.xml and build/results.json are always written.

debug: compiles the suite with the debug profile (-g) and leaves
.vscode/launch.json ready for the Cobalto VS Code extension (or plain
lldb-dap), with the line map, the variable map and the data layout.

suggest: an AI model proposes a .cblt suite for a program; the CLI runs it
with coverage and feeds back the errors, the failures and the paragraphs
that did not run, for N rounds. The best round is saved as a draft in
tests/<PROGRAM>.ai.cblt for a person to review. See suggest.py.
"""
import argparse
import sys

from . import messages
from . import suggest as sugg
from .commands import (cmd_debug, cmd_init, cmd_list, cmd_parse, cmd_profiles, cmd_report,
                       cmd_suggest, cmd_test)
from .messages import VERSION, CobaltoError
from .remote import MANIFEST

COMMANDS = {"test": cmd_test, "report": cmd_report, "debug": cmd_debug, "suggest": cmd_suggest,
            "init": cmd_init, "list": cmd_list, "profiles": cmd_profiles, "parse": cmd_parse}


def main():
    ap = argparse.ArgumentParser(prog="cobalto")
    ap.add_argument("--version", action="version", version=f"Cobalto {VERSION}")
    ap.add_argument("--config", default="cblt.json")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("test", help="compile and run the suites")
    t.add_argument("--profile")
    t.add_argument("--filter", help="only suites whose name contains this text")
    t.add_argument("--coverage", action="store_true",
                   help="portable coverage: instruments the programs and reports by paragraph (also LCOV, Cobertura XML and Sonar)")
    t.add_argument("--no-run", action="store_true", help="compile without running")
    t.add_argument("--generate-only", action="store_true",
                   help="only generate the suites, the driver and build/remote/ (useful for remote profiles)")
    t.add_argument("--host", help="host of the remote profile (user@machine); overrides the host field")
    t.add_argument("--remote-dir", help="remote directory; overrides the remote_dir field")
    t.add_argument("--json", action="store_true",
                   help="write the result as JSON to standard output (the console goes to stderr)")
    t.add_argument("--verbose", "-v", action="store_true")
    r = sub.add_parser("report", help="parse a results file returned by hand from a host without ssh")
    r.add_argument("--results", required=True, help="results file brought back from the host (e.g. CBLT_RESULTS.DAT)")
    r.add_argument("--output", help="screen output of the run, copied to a file (optional)")
    r.add_argument("--manifest", help=f"manifest written by 'test --generate-only' (default build/remote/{MANIFEST})")
    r.add_argument("--json", action="store_true",
                   help="write the result as JSON to standard output (the console goes to stderr)")
    r.add_argument("--verbose", "-v", action="store_true")
    i = sub.add_parser("init", help="create a Cobalto project")
    i.add_argument("dir", nargs="?", default=".")
    ls = sub.add_parser("list", help="list the suites and their test cases, without compiling")
    ls.add_argument("--json", action="store_true",
                    help="write the result as JSON to standard output (the console goes to stderr)")
    f = sub.add_parser("profiles", help="list the built-in profiles and the project's")
    f.add_argument("--json", action="store_true",
                   help="write the result as JSON to standard output (the console goes to stderr)")
    p = sub.add_parser("parse", help="show how the parser sees a COBOL program")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true",
                   help="write the result as JSON to standard output (the console goes to stderr)")
    d = sub.add_parser("debug", help="compile a suite with -g and prepare .vscode/launch.json (lldb-dap)")
    d.add_argument("--suite", required=True, help="suite id (for example TSTINV)")
    d.add_argument("--profile", help="local profile with -g; default gnucobol-debug")
    d.add_argument("--verbose", "-v", action="store_true")
    g = sub.add_parser("suggest", help="ask an AI model for a suite for a program and validate it by running it")
    g.add_argument("--program", required=True, help="PROGRAM-ID, file name in sources, or path to the .cbl")
    g.add_argument("--rounds", type=int, help=f"rounds of proposal and correction (default {sugg.DEFAULT_ROUNDS})")
    g.add_argument("--max-cases", type=int, help=f"maximum number of test cases per round (default {sugg.DEFAULT_MAX_CASES})")
    g.add_argument("--backend", choices=["api", "command", "auto"], help="api (ANTHROPIC_API_KEY), command (claude -p or another CLI) or auto")
    g.add_argument("--command", help="command of the command backend; it receives the prompt on stdin")
    g.add_argument("--model", help="model (default: the one in the ai field of cblt.json)")
    g.add_argument("--out", help="output file (default tests/<PROGRAM>.ai.cblt)")
    g.add_argument("--profile", help="profile used to run each round")
    g.add_argument("--mode", choices=["auto", "interface", "in-program"],
                   help="kind of test case requested: interface (only what goes in and comes out; an internal "
                        "case counts as an error of the round), in-program (single paragraphs) or auto (ai.mode field)")
    g.add_argument("--fill-expected", action="store_true",
                   help="deterministic characterization: an equality EXPECT that fails is changed to expect the "
                        "value the program produces, without spending a round (ai.fill_expected field)")
    g.add_argument("--dry-run", action="store_true", help="build the prompt in build/ai/ without sending it")
    g.add_argument("--verbose", "-v", action="store_true")
    argv = sys.argv[1:]
    if not any(x in COMMANDS or x in ("-h", "--help", "--version") for x in argv):
        argv = ["test"] + argv          # 'cobalto --profile X' is the same as 'cobalto test --profile X'
    a = ap.parse_args(argv)
    if getattr(a, "json", False):
        messages.JSON_OUT, sys.stdout = sys.stdout, sys.stderr
    if a.cmd not in COMMANDS:
        ap.print_help()
        return 0
    try:
        return COMMANDS[a.cmd](a)
    except CobaltoError as e:
        print(e, file=sys.stderr)
        messages.emit_json({"error": {"code": f"CBLT-{e.code}", "message": e.message}})
        return 2


if __name__ == "__main__":
    sys.exit(main())
