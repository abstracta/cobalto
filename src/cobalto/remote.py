"""Remote profiles: staging the sources and scripts, running on the host, and the manifest."""
import glob
import json
import os
import re
import shlex
import shutil
import sys

from .messages import SCHEMA, VERSION, CobaltoError, msg
from .model import Generated, SuiteRef
from .pad80 import Pad80Error, pad80_text
from .reports import write_json
from .results import split_output
from .runner import sh

END_PROGRAM = re.compile(r"^\s{7}END PROGRAM\s+([A-Za-z0-9-]+)\s*\.", re.I)


def split_programs(text):
    """Splits a source with several programs (each one closed with
    END PROGRAM) into [(name, text)]. The header comments of the file stay
    with the first program."""
    out, cur = [], []
    for line in text.splitlines():
        cur.append(line)
        m = END_PROGRAM.match(line)
        if m:
            while cur and not cur[0].strip():
                cur.pop(0)
            out.append((m.group(1).upper(), "\n".join(cur) + "\n"))
            cur = []
    if any(l.strip() for l in cur):
        out.append((f"PART{len(out) + 1}", "\n".join(cur) + "\n"))
    return out


def to_terminal_format(text):
    """ANSI fixed format -> VSI COBOL terminal format: the sequence area
    (columns 1 to 6) is removed, so the indicator lands in column 1 and
    Area A starts in column 2. It is what the COBOL command expects without
    /ANSI_FORMAT. No padding to 80 columns."""
    out = []
    for line in text.splitlines():
        line = line.expandtabs(8).rstrip()
        out.append(line[6:] if len(line) > 6 and not line[:6].strip() else line.lstrip())
    return "\n".join(out) + "\n"


def is_copybook(path):
    return os.path.splitext(path)[1].lower() in (".cpy", ".copy", ".lib", ".cob.inc")


def stage_remote(cfg, prof, fmt, driver, gen_files, legacy_files, sources):
    """Prepares build/remote/ with what is uploaded to the host: sources
    with upper-case names (VMS), padded to 80 columns if the profile asks
    for it, the copybook with the extension the remote compiler expects
    (VSI COBOL looks for CBLTCTX.LIB), and the build and run scripts
    generated from the "compile" and "run" templates.
    Returns (stage_dir, uploaded_names, scripts, cobol_names)."""
    stage = os.path.join(fmt["build"], "remote")
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    lib_files = sorted(glob.glob(os.path.join(cfg["lib"], "*")))
    copybooks = [f for f in lib_files if is_copybook(f)]
    for d in cfg.get("copybooks", []):
        copybooks += [f for f in sorted(glob.glob(os.path.join(d, "*"))) if is_copybook(f)]
    programs = [driver] + [f for f in lib_files if f not in copybooks] + gen_files + legacy_files + sources
    names, cobol_names = [], []
    units = []                      # (nombre_base, ext, texto, es_programa)
    for f in programs + copybooks:
        base, ext = os.path.splitext(os.path.basename(f))
        if f in copybooks and prof.get("copybook_ext"):
            ext = prof["copybook_ext"]
        elif f in programs and prof.get("source_ext") and ext.lower() not in (".sco",):
            ext = prof["source_ext"]       # e.g. ".COB": what the host's compile command accepts
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if prof.get("split_lib") and f in lib_files and f not in copybooks:
            # one source per program, for compilers that do not accept
            # several programs (separated by END PROGRAM) in one file
            for pname, ptext in split_programs(text):
                units.append((pname, ext, ptext, True, f))
        else:
            units.append((base, ext, text, f in programs, f))
    for base, ext, text, is_program, src in units:
        name = (base + ext).upper() if prof.get("upper_names", True) else base + ext
        if prof.get("source_format", "ansi") == "terminal":
            text = to_terminal_format(text)
        if prof.get("pad80"):
            try:
                text, warns = pad80_text(text, src)
            except Pad80Error as e:
                raise CobaltoError("E203", detail=str(e))
            for w in warns:
                print(msg("W303", detail=w), file=sys.stderr)
        with open(os.path.join(stage, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        names.append(name)
        if is_program:
            cobol_names.append(name)
    # build and run scripts from the templates
    obj_ext = prof.get("obj_ext", ".OBJ")
    objs = prof.get("objs_sep", ", ").join(os.path.splitext(n)[0] + obj_ext for n in cobol_names)
    each = prof.get("compile_each", "")
    lines = []
    for n in cobol_names:
        ext = os.path.splitext(n)[1].upper()
        tpl = each.get(ext, each.get("*", "")) if isinstance(each, dict) else each
        if tpl:
            lines.append(tpl.format(file=n, name=os.path.splitext(n)[0], **fmt))
    sfmt = dict(fmt, files=" ".join(cobol_names), objs=objs, compile_each="\n".join(lines))
    scripts = prof.get("scripts", {"compile": "CBLT_BUILD.COM", "run": "CBLT_RUN.COM"})
    for key, fname in scripts.items():
        with open(os.path.join(stage, fname), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(prof[key].format(**sfmt).rstrip("\n") + "\n")
        names.append(fname)
    return stage, names, scripts, cobol_names


def run_remote(cfg, prof, pname, a, fmt, gen):
    """Uploads build/remote/ to the host, runs the build and run scripts
    through "remote" and brings the results file back with "fetch".
    Returns (results_local, outputs, rc), or None if nothing was run."""
    host = a.host or prof.get("host", "")
    rdir = a.remote_dir if a.remote_dir is not None else prof.get("remote_dir", "")
    fmt = dict(fmt, host=host, remote_dir=rdir)
    stage, names, scripts, cobol_names = stage_remote(cfg, prof, fmt, gen.driver, gen.gen_files,
                                                      gen.legacy_files, gen.sources)
    write_manifest(stage, pname, prof, gen)
    print(f"Prepared {stage}/: " + " ".join(names))
    if a.generate_only:
        return None
    templates = prof.get("remote", "") + prof.get("upload", "") + prof.get("fetch", "")
    if "{host}" in templates and not host:
        raise CobaltoError("E102", profile=pname)
    results_local = prof.get("results_local", os.path.join(fmt["build"], "cblt-results.dat"))
    rfmt = dict(fmt, stage=stage, files=" ".join(cobol_names), results_local=results_local,
                upload_files=" ".join(shlex.quote(os.path.join(stage, n)) for n in names))

    def remote(cmd, label):
        return sh(prof["remote"].format(**rfmt) + " " + shlex.quote(cmd), label, a.verbose, capture=True)

    r = sh(prof["upload"].format(**rfmt), "upload", a.verbose, capture=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, end="", file=sys.stderr)
        raise CobaltoError("E104", rc=r.returncode)
    invoke = prof.get("invoke", "@{script}")
    build_ok = prof.get("build_ok", "CBLT-BUILD-OK")
    r = remote(invoke.format(script=scripts["compile"], **rfmt), "compile")
    if r.returncode != 0 or build_ok not in r.stdout:
        print(r.stdout, end="")
        print(r.stderr, end="", file=sys.stderr)
        raise CobaltoError("E105", rc=r.returncode, marker=build_ok)
    if a.no_run:
        print("Compiled on the host. Not run (--no-run).")
        return None
    run_ok = prof.get("run_ok", "CBLT-RUN-OK")
    r = remote(invoke.format(script=scripts["run"], **rfmt), "run")
    rc = r.returncode
    if run_ok not in r.stdout:
        rc = rc or 1
    markers = (build_ok, run_ok, "CBLT-BUILD-FAILED", "CBLT-RUN-FAILED")
    stdout = "\n".join(l for l in r.stdout.splitlines() if l.strip() not in markers)
    outputs = split_output(stdout)
    if r.stderr.strip():
        outputs[("__stderr__", None)] = r.stderr.splitlines()
    if os.path.exists(results_local):
        os.remove(results_local)
    r = sh(prof["fetch"].format(**rfmt), "fetch", a.verbose, capture=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, end="", file=sys.stderr)
    return results_local, outputs, rc


MANIFEST = "cblt-manifest.json"


def write_manifest(stage, pname, prof, gen):
    """Leaves in build/remote/ what 'report' needs to read a results file
    that comes back from the host by hand: profile, format, suites (id,
    file, description), which suites are in-program, and the kind of each
    test case (interface or internal). It is not uploaded to the host."""
    write_json(os.path.join(stage, MANIFEST),
               {"schema": SCHEMA, "cobalto": VERSION, "profile": pname, "results_format": prof["results_format"],
                "suites": [[s.id, os.path.relpath(s.file), s.description] for s in gen.suites],
                "inprog": {s.id: gen.inprog[s.id] for s in gen.suites if s.id in gen.inprog},
                "case_kinds": [[su, ca, kind, reasons] for (su, ca), (kind, reasons) in gen.case_kinds.items()]})


def read_manifest(path):
    """Loads a manifest. Returns it with a Generated that holds what the
    report needs: the suites, which ones are in-program and the kind of each
    test case."""
    with open(path, encoding="utf-8") as fh:
        man = json.load(fh)
    gen = Generated(suites=[SuiteRef(*x) for x in man["suites"]], inprog=dict(man.get("inprog", {})),
                    case_kinds={(su, ca): (kind, reasons) for su, ca, kind, reasons in man.get("case_kinds", [])})
    return man, gen


SCREEN_NOISE = re.compile(r"^\$( |$)|^\s*Job \S+ \(queue .*\) (started|completed)")


def clean_screen(text):
    """Screen output copied from a terminal: removes the DCL echoes
    (SET VERIFY), the batch queue notices and the end markers, so that
    they are not attributed to the last test case."""
    markers = ("CBLT-BUILD-OK", "CBLT-RUN-OK", "CBLT-BUILD-FAILED", "CBLT-RUN-FAILED")
    keep = []
    for line in text.replace("\r", "").splitlines():
        if SCREEN_NOISE.match(line) or line.strip() in markers:
            continue
        keep.append(line)
    return "\n".join(keep)
