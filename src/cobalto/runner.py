"""Running shell commands of a profile, and the local compile-and-run cycle."""
import os
import re
import subprocess
import sys

from .messages import CobaltoError, compile_error_line
from .results import split_output

def sh(cmd, label, verbose, capture=False):
    if verbose:
        print(f"[{label}] {cmd}")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors="replace")
    if verbose or not capture:
        # the output of the "run" step is split by test case later on;
        # the output of the other steps is shown as is with -v
        if r.stdout and (not capture or (verbose and label != "run")):
            print(r.stdout, end="")
        if r.stderr and label != "compile":
            print(r.stderr, end="", file=sys.stderr)
    return r


def report_compile_errors(r, prof, linemaps):
    """Prints one CBLT-E201 per compiler message that the profile's
    error_regex matches, at the line of the .cblt or of the original program
    that caused it, or the compiler's output as is if none matches. Returns
    what the JSON error object of the build failure adds: "details", one
    entry per message (file and line of the source, "generated" with the
    line of the generated COBOL when the error was mapped back from it, or
    null), or "output", the compiler's output."""
    rx = re.compile(prof.get("error_regex", r"^(?P<file>[^:\n]+):(?P<line>\d+): (?:error|Error): (?P<msg>.*)$"), re.M)
    details = []
    for m in rx.finditer(r.stderr + "\n" + r.stdout):
        gf, gl = os.path.normpath(m.group("file")), int(m.group("line"))
        detail = {"code": "CBLT-E201", "file": gf, "line": gl, "generated": None, "message": m.group("msg").strip()}
        lm = linemaps.get(gf)
        if lm and 0 < gl <= len(lm) and lm[gl - 1]:
            sf, sl = lm[gl - 1]
            detail.update(file=sf, line=sl, generated=f"{gf}:{gl}")
        print(compile_error_line(detail), file=sys.stderr)
        details.append(detail)
    if details:
        return {"details": details}
    # nothing matched: the compiler's own words, from stderr or, if it wrote
    # nothing there, from stdout
    output = r.stderr if r.stderr.strip() else r.stdout
    print(output, file=sys.stderr)
    return {"output": output}


def run_local(prof, a, fmt, linemaps):
    """Compiles and runs on this machine. Returns
    (results_path, outputs, rc), or None if nothing was run."""
    r = sh(prof["compile"].format(**fmt), "compile", a.verbose, capture=True)
    if r.returncode != 0:
        raise CobaltoError("E202", extra=report_compile_errors(r, prof, linemaps), rc=r.returncode)
    if a.no_run:
        print("Compiled. Not run (--no-run).")
        return None
    results_path = prof["results_path"]
    if os.path.exists(results_path):
        os.remove(results_path)
    if "pre" in prof:
        sh(prof["pre"].format(**fmt), "pre", a.verbose)
    r = sh(prof["run"].format(**fmt), "run", a.verbose, capture=True)
    outputs = split_output(r.stdout)
    if r.stderr.strip():
        outputs[("__stderr__", None)] = r.stderr.splitlines()
    if "post" in prof:
        sh(prof["post"].format(**fmt), "post", a.verbose)
    return results_path, outputs, r.returncode
