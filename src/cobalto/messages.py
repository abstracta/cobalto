"""Message catalog, versions and the JSON output channel of the Cobalto CLI."""
import json
import sys

from . import __version__ as VERSION

SCHEMA = 1              # version of the JSON files the CLI writes: results, manifest, lines, layout and coverage map
JSON_OUT = None         # with --json, the real standard output: only the JSON goes there, the console goes to stderr
# Errors (E) exit with code 2; warnings (W) do not change the exit code.
MESSAGES = {
    "E100": "no test suites found in {patterns}",
    "E101": "profile '{profile}' does not exist; available: {available}",
    "E102": "remote profile '{profile}' needs a host: --host or the \"host\" field in cblt.json",
    "E103": "{path} not found; run 'cobalto init' or pass --config",
    "E104": "the upload to the host failed (exit {rc})",
    "E105": "the remote build failed (exit {rc}, the marker {marker} did not appear)",
    "E106": "manifest {path} not found; run 'cobalto test --generate-only' with the remote profile or pass --manifest",
    "E200": "DSL syntax error in {file}:{line}: {detail}",
    "E201": "compile error in {where}: {detail}",
    "E202": "the build failed (exit {rc})",
    "E203": "source cannot be converted to 80 columns: {detail}",
    "E300": "no results file ({path}): the process died before opening it, or the remote fetch failed",
    "W301": "{n} test(s) never started: the process died first",
    "W302": "duplicate PROGRAM-ID '{name}' in {file}; that file is not compiled",
    "W303": "{detail}",
    "W304": "there are no {kind} statements in {program}; the MOCK has no effect",
    "W305": "{program} is not instrumented for coverage ({detail}); the original is compiled",
    "W306": "no coverage records (C|...) arrived: no instrumented program reached EXIT PROGRAM or GOBACK, or the library has no CBLTCOV",
    "W307": "{n} assert record(s) arrived cut at column {col} (a complete one reaches at least column 141): the description is missing and the values may be incomplete; copy the content without trimming the lines",
    "W308": "{suite} ran {asserts} assert(s) and {failed} failed, but the detail of only {logged} arrived: the log of a suite keeps 500 entries (asserts plus test cases) and the rest are counted with no detail; split the suite",
    "E400": "program under test '{name}' not found for {file} (searched by PROGRAM-ID and file name in {patterns})",
    "E401": "MOCK/VERIFY PARAGRAPH: paragraph '{name}' does not exist in {program} (or it is a SECTION)",
    "E402": "MOCK/VERIFY CALL: there is no CALL to '{name}' in {program}",
    "E403": "file MOCK/VERIFY: '{name}' is not declared (SELECT/FD) in {program}, or the program has no such operation on it",
    "E404": "the program under test could not be parsed: {detail}",
    "E405": "paragraph '{name}' of {program} cannot be mocked: it contains NEXT SENTENCE",
    "E406": "program {program} cannot be used in in-program mode: {detail}",
    "E407": "MOCK and VERIFY are only valid in a suite with PROGRAM (in-program mode): {file}:{line}",
    "E500": "debug: suite '{suite}' does not exist; available: {available}",
    "E501": "debug: profile '{profile}' is remote; a local profile with -g is needed (for example gnucobol-debug)",
    "E600": "suggest: no AI backend ({detail}); see the \"ai\" field in cblt.json or --backend",
    "E601": "suggest: the {backend} backend failed: {detail}",
    "E602": "suggest: the model's answer contains no suite (TESTSUITE); saved to {path}",
    "W601": "suggest: no round compiled; the drafts are in {dir}",
    "W602": "suggest: the best round has {fails} failure(s) and {errors} error(s); review it before adopting it",
}


def msg(code, **kw):
    return f"CBLT-{code}: " + MESSAGES[code].format(**kw)


class CobaltoError(Exception):
    """An error from the catalog: its code (for example "E200") and the
    fields of its message. It can be raised anywhere; main turns it into the
    message on stderr and exit code 2."""

    def __init__(self, code, **kw):
        super().__init__(code)
        self.code, self.kw = code, kw

    @property
    def message(self):
        return MESSAGES[self.code].format(**self.kw)

    def __str__(self):
        return f"CBLT-{self.code}: {self.message}"


def warn(code, **kw):
    """Prints a warning from the catalog on stderr."""
    print(msg(code, **kw), file=sys.stderr)


def emit_json(data):
    """With --json, writes a JSON document to standard output; without
    --json it does nothing. Every document carries the schema version and
    the CLI version."""
    if JSON_OUT is not None:
        json.dump(dict({"schema": SCHEMA, "cobalto": VERSION}, **data), JSON_OUT, indent=2, ensure_ascii=False)
        JSON_OUT.write("\n")
