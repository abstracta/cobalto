"""Discovery of the suites and generation of the test programs and the driver."""
import glob
import os
import re

from . import coverage as covmod
from . import inprog
from .config import copy_dirs_of
from .driver import driver_source
from .dsl import DslError, gen_suite, parse_dsl
from .messages import CobaltoError, warn
from .model import Generated, SuiteRef

PROGRAM_ID = re.compile(r"^\s{6}[\s-]\s*PROGRAM-ID\.\s*([A-Za-z0-9-]+)", re.I | re.M)


def expand(patterns):
    out = []
    for p in patterns:
        out += sorted(glob.glob(p))
    return out


def discover_legacy(files, prefix):
    """[(PROGRAM-ID, file, line)] of the hand-written test programs in files."""
    found = []
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for m in PROGRAM_ID.finditer(text):
            if m.group(1).upper().startswith(prefix.upper()):
                found.append((m.group(1).upper(), f, text.count("\n", 0, m.start(1)) + 1))
    return found


def list_suites(cfg):
    """What the suite files of the project declare, without generating or
    compiling anything: (suites, errors). A file with a syntax error goes to
    errors and does not hide the others."""
    suites, errors, legacy_files = [], [], []
    for f in expand(cfg["tests"]):
        if not f.lower().endswith(".cblt"):
            legacy_files.append(f)
            continue
        try:
            s = parse_dsl(f)
        except DslError as e:
            e.kw["file"] = f
            errors.append({"file": f, "line": e.kw["line"], "code": f"CBLT-{e.code}", "message": e.message})
            continue
        suites.append({"id": s.id, "file": f, "line": s.line, "description": s.desc, "dsl": True,
                       "program": s.program,
                       "cases": [{"name": c.name, "line": c.line, "ignored": c.ignored} for c in s.cases]})
    dsl_ids = {s["id"] for s in suites}
    for name, f, line in discover_legacy(legacy_files, cfg["test_prefix"]):
        if name not in dsl_ids:
            suites.append({"id": name, "file": f, "line": line, "description": "", "dsl": False,
                           "program": None, "cases": []})
    return suites, errors


def resolve_program(spec, cfg, suite_file):
    """PROGRAM name -> searched by PROGRAM-ID or file name in sources;
    PROGRAM "path" -> path relative to the project or to the suite."""
    spec = spec.strip()
    if spec[:1] in "'\"":
        path = spec.strip("'\"")
        for cand in (path, os.path.join(os.path.dirname(suite_file), path)):
            if os.path.isfile(cand):
                return cand
        raise CobaltoError("E400", name=path, file=suite_file, patterns=cfg["sources"])
    name = spec.upper()
    for f in expand(cfg["sources"]):
        if os.path.splitext(os.path.basename(f))[0].upper() == name:
            return f
        with open(f, encoding="utf-8", errors="replace") as fh:
            if any(m.group(1).upper() == name for m in PROGRAM_ID.finditer(fh.read())):
                return f
    raise CobaltoError("E400", name=name, file=suite_file, patterns=cfg["sources"])


def gen_inprogram(s, cfg, coverage, gen):
    """In-program copy of the program under test with the suite injected."""
    prog_path = resolve_program(s.program, cfg, s.file)
    w, plan = inprog.generate(s, prog_path, copy_dirs_of(cfg), with_coverage=coverage)
    gen.inprog[s.id] = os.path.basename(prog_path)
    if plan is not None:
        gen.cov_map.setdefault(plan.name, plan.to_json(prog_path))
    return w


def instrument_sources(cfg, sources, gen):
    """Instrumented copy of each program under test in build/cov/. If a
    source cannot be instrumented (several programs in one file, a missing
    copybook), a warning is shown and the original is compiled."""
    cov_dir = os.path.join(cfg["build"], "cov")
    os.makedirs(cov_dir, exist_ok=True)
    out = []
    for src in sources:
        try:
            w, plan = inprog.generate_coverage(src, copy_dirs_of(cfg))
        except (CobaltoError, ValueError) as e:
            warn("W305", program=src, detail=str(e))
            out.append(src)
            continue
        dst = os.path.join(cov_dir, os.path.basename(src))
        with open(dst, "w") as fh:
            fh.write(w.text())
        gen.linemaps[os.path.normpath(dst)] = w.origin
        gen.cov_map.setdefault(plan.name, plan.to_json(src))
        out.append(dst)
    covmod.save_map(gen.cov_map, os.path.join(cov_dir, "map.json"))
    return out


def generate(cfg, prof, suite_filter=None, coverage=False):
    """Discovers the suites, expands the DSL, instruments the sources when
    coverage is on, and writes the driver. suite_filter keeps only the suites
    whose id contains that text. Returns a Generated."""
    build = cfg["build"]
    os.makedirs(build, exist_ok=True)
    gen = Generated()
    for f in expand(cfg["tests"]):
        if not f.lower().endswith(".cblt"):
            gen.legacy_files.append(f)
            continue
        try:
            s = parse_dsl(f)
            w = gen_inprogram(s, cfg, coverage, gen) if s.program else gen_suite(s)
        except DslError as e:
            e.kw["file"] = f
            raise
        except ValueError as e:
            raise CobaltoError("E200", file=f, line="?", detail=str(e))
        for c in s.cases:
            gen.case_kinds[(s.id, c.name)] = (c.kind, c.reasons)
        out = os.path.join(build, f"{s.id}.cbl")
        with open(out, "w") as fh:
            fh.write(w.text())
        gen.linemaps[os.path.normpath(out)] = w.origin
        gen.gen_files.append(out)
        gen.suites.append(SuiteRef(s.id, f, s.desc))
    # a legacy test whose PROGRAM-ID repeats that of a DSL suite is not
    # compiled: the link would fail on the duplicate symbol
    prefix = cfg["test_prefix"]
    dsl_ids = {s.id for s in gen.suites}
    dup_files = set()
    for name, f, _ in discover_legacy(gen.legacy_files, prefix):
        if name in dsl_ids:
            warn("W302", name=name, file=f)
            dup_files.add(f)
    gen.legacy_files = [f for f in gen.legacy_files if f not in dup_files]
    gen.suites += [SuiteRef(name, f) for name, f, _ in discover_legacy(gen.legacy_files, prefix)]
    if suite_filter:
        gen.suites = [s for s in gen.suites if suite_filter.upper() in s.id]
    if not gen.suites:
        raise CobaltoError("E100", patterns=cfg["tests"])
    gen.sources = expand(cfg["sources"])
    if coverage:
        gen.sources = instrument_sources(cfg, gen.sources, gen)
    gen.driver = os.path.join(build, "CBLTDRV.cbl")
    with open(gen.driver, "w") as fh:
        fh.write(driver_source([s.id for s in gen.suites], prof["results_path"], prof["results_org"], coverage))
    return gen
