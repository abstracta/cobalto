"""Running shell commands of a profile, and the local compile-and-run cycle."""
import os
import re
import subprocess
import sys

from .messages import CobaltoError, msg
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
    rx = re.compile(prof.get("error_regex", r"^(?P<file>[^:\n]+):(?P<line>\d+): (?:error|Error): (?P<msg>.*)$"), re.M)
    shown = 0
    for m in rx.finditer(r.stderr + "\n" + r.stdout):
        gf, gl = os.path.normpath(m.group("file")), int(m.group("line"))
        where = f"{gf}:{gl}"
        lm = linemaps.get(gf)
        if lm and 0 < gl <= len(lm) and lm[gl - 1]:
            sf, sl = lm[gl - 1]
            where = f"{sf}:{sl} (generated at {gf}:{gl})"
        print(msg("E201", where=where, detail=m.group("msg").strip()), file=sys.stderr)
        shown += 1
    if not shown:
        print(r.stderr, file=sys.stderr)


def run_local(prof, a, fmt, linemaps):
    """Compiles and runs on this machine. Returns
    (results_path, outputs, rc), or None if nothing was run."""
    r = sh(prof["compile"].format(**fmt), "compile", a.verbose, capture=True)
    if r.returncode != 0:
        report_compile_errors(r, prof, linemaps)
        raise CobaltoError("E202", rc=r.returncode)
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
