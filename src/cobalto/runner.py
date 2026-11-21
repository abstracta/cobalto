"""Running shell commands of a profile, and the local compile-and-run cycle."""
import os
import re
import subprocess
import sys

from .messages import CobaltoError, compile_error_line
from .results import split_output

def sh(cmd, label, verbose, capture=False, merge=False):
    """Runs a command of the profile. With merge, standard error goes into
    standard output: one stream, as a terminal shows it, for a step whose
    output is read whole whichever stream it was written to (the compile
    step: a compiler may report on either)."""
    if verbose:
        print(f"[{label}] {cmd}")
    r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT if merge else subprocess.PIPE, text=True, errors="replace")
    if merge:
        r.stderr = ""
    if verbose or not capture:
        # the output of the "run" step is split by test case later on;
        # the output of the other steps is shown as is with -v
        if r.stdout and (not capture or (verbose and label != "run")):
            print(r.stdout, end="")
        if r.stderr and label != "compile":
            print(r.stderr, end="", file=sys.stderr)
    return r


def report_compile_errors(r, prof, linemaps, shown=False):
    """Prints one CBLT-E201 per compiler message that the profile's
    error_regex matches, at the line of the .cblt or of the original program
    that caused it, or the compiler's output as is if none matches (unless
    shown says -v already printed it). Returns what the JSON error object of
    the build failure adds: "details", one entry per message (file and line
    of the source, "generated" with the line of the generated COBOL when the
    error was mapped back from it, or null), or "output", the compiler's
    output, both of its streams."""
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
    # nothing matched: the compiler's own words, whichever stream they were
    # written to (the compile step captures both as one)
    output = r.stderr + r.stdout
    if not shown:
        print(output, file=sys.stderr)
    return {"output": output}


def compile_step(prof, fmt, linemaps, verbose):
    """Runs the compile command of the profile, with its two streams as one.
    Raises CBLT-E202, with the compile errors, if it fails."""
    r = sh(prof["compile"].format(**fmt), "compile", verbose, capture=True, merge=True)
    if r.returncode != 0:
        raise CobaltoError("E202", extra=report_compile_errors(r, prof, linemaps, shown=verbose), rc=r.returncode)
    return r


def run_local(prof, a, fmt, linemaps):
    """Compiles and runs on this machine. Returns
    (results_path, outputs, rc), or None if nothing was run."""
    compile_step(prof, fmt, linemaps, a.verbose)
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
