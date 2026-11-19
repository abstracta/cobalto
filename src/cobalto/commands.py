"""The CLI commands: test, report, debug, suggest, init, list, profiles and parse."""
import json
import os
import re
import subprocess
import sys

from . import cobparse
from . import coverage as covmod
from . import inprog
from . import suggest as sugg
from .build import expand, generate, list_suites, resolve_program
from .config import DEFAULTS, copy_dirs_of, load_config, profile_of, template_fields
from .debuginfo import LAUNCH_NAME, format_vars_map, write_launch_json, write_layout
from .dsl import DslError, parse_dsl
from .messages import MESSAGES, SCHEMA, VERSION, CobaltoError, emit_json, msg, warn
from .remote import MANIFEST, clean_screen, read_manifest, run_remote
from .reports import (render_console, report_coverage, write_json, write_junit,
                     write_sonar_tests)
from .results import build_run, parse_results, read_records, reason_text, split_output
from .runner import report_compile_errors, run_local, sh


def cmd_report(a):
    """Parses a results file returned by hand from the host."""
    mpath = a.manifest or os.path.join("build", "remote", MANIFEST)
    if not os.path.exists(mpath):
        raise CobaltoError("E106", path=mpath)
    man, gen = read_manifest(mpath)
    cfg = load_config(a.config, required=False)
    prof = dict(cfg["profiles"].get(man["profile"], {}))
    prof["results_format"] = man["results_format"]
    prof.pop("coverage_glob", None)
    build = cfg["build"]
    os.makedirs(build, exist_ok=True)
    outputs, rc = {}, 0
    if a.output:
        with open(a.output, "rb") as fh:
            screen = fh.read().decode("latin-1")
        outputs = split_output(clean_screen(screen))
        if "CBLT-RUN-OK" not in screen:
            rc = 1
    print(f"Cobalto {VERSION}  profile: {man['profile']}  (results returned from the host)")
    print("Suites: " + ", ".join(s.id for s in gen.suites))
    print(f"Results: {a.results}" + (f"  screen: {a.output}" if a.output else ""))
    return report(gen, prof, {"build": build}, build, a.results, outputs, rc, a.verbose, man["profile"])


def cmd_test(a):
    cfg = load_config(a.config)
    pname, prof = profile_of(cfg, a.profile)
    build = cfg["build"]
    remote = "remote" in prof
    coverage = bool(a.coverage or prof.get("coverage", False))

    # 1 and 2. suites, sources (instrumented when coverage is on) and driver
    gen = generate(cfg, prof, a.filter, coverage)
    print(f"Cobalto {VERSION}  profile: {pname}" + ("  (remote)" if remote else "")
          + ("  portable coverage" if coverage else ""))
    print("Suites: " + ", ".join(s.id for s in gen.suites))
    fmt = template_fields(cfg, gen)

    # 3 and 4. compile and run, here or on the host
    if remote:
        res = run_remote(cfg, prof, pname, a, fmt, gen)
    else:
        if a.generate_only:
            print("Generated: " + " ".join(gen.gen_files + [gen.driver]) + ". Not compiled (--generate-only).")
            emit_json({"profile": pname, "ran": False, "suites": [s.id for s in gen.suites]})
            return 0
        res = run_local(prof, a, fmt, gen.linemaps)
    if res is None:
        emit_json({"profile": pname, "ran": False, "suites": [s.id for s in gen.suites]})
        return 0
    results_path, outputs, rc = res

    # 5. report
    return report(gen, prof, fmt, build, results_path, outputs, rc, a.verbose, pname)


def report(gen, prof, fmt, build, results_path, outputs, rc, verbose, pname):
    """Builds the run model and writes it out: console, junit.xml,
    sonar-tests.xml, the coverage reports and results.json. Returns the
    exit code of the command."""
    raw = read_records(results_path, prof["results_format"])
    if raw is None:
        raise CobaltoError("E300", path=results_path)
    records = [r.rstrip() for r in raw]
    run = build_run(gen, parse_results(records), outputs, rc, raw, pname)
    for line in render_console(run, verbose):
        print(line)
    junit_path = os.path.join(build, "junit.xml")
    write_junit(run, junit_path)
    sonar_tests = os.path.join(build, "sonar-tests.xml")
    write_sonar_tests(run, sonar_tests)
    results_json = os.path.join(build, "results.json")
    print(f"JUnit: {junit_path}  Sonar (test execution): {sonar_tests}  JSON: {results_json}")
    if "coverage_glob" in prof:
        report_coverage(prof["coverage_glob"].format(**fmt), [os.path.basename(x) for x in gen.sources],
                        gen.inprog)
        if gen.cov_map:
            print("  (with --coverage the gcov lines are those of the instrumented copies in build/cov/)")
    if gen.cov_map:
        hits = covmod.parse_records(records)
        if not hits:
            print("  " + msg("W306"))
            run["warnings"].append({"code": "CBLT-W306", "message": MESSAGES["W306"]})
        run["coverage"] = covmod.summarize(gen.cov_map, hits)
        covmod.print_report(run["coverage"])
        lcov = os.path.join(build, "lcov.info")
        xml = os.path.join(build, "coverage.xml")
        sonar = os.path.join(build, "sonar-coverage.xml")
        covmod.write_lcov(gen.cov_map, hits, lcov)
        covmod.write_cobertura(gen.cov_map, hits, xml)
        covmod.write_sonar(gen.cov_map, hits, sonar)
        print(f"  LCOV: {lcov}  Cobertura XML: {xml}  Sonar: {sonar}  "
              f"map: {os.path.join(build, 'cov', 'map.json')}")
    write_json(results_json, run)
    emit_json({k: v for k, v in run.items() if k not in ("schema", "cobalto")})
    return 0 if run["ok"] else 1


def cmd_debug(a):
    cfg = load_config(a.config)
    pname, prof = profile_of(cfg, a.profile or ("gnucobol-debug" if "gnucobol-debug" in cfg["profiles"] else None))
    if "remote" in prof:
        raise CobaltoError("E501", profile=pname)
    build = cfg["build"]
    names = [s.id for s in generate(cfg, prof).suites]
    suite = a.suite.upper()
    if suite not in names:
        raise CobaltoError("E500", suite=a.suite, available=", ".join(names))
    # driver with only the requested suite
    gen = generate(cfg, prof, suite)
    print(f"Cobalto {VERSION}  profile: {pname}  debugging {suite}")
    fmt = template_fields(cfg, gen)
    exe = fmt["exe"]
    r = sh(prof["compile"].format(**fmt), "compile", a.verbose, capture=True)
    if r.returncode != 0:
        report_compile_errors(r, prof, gen.linemaps)
        raise CobaltoError("E202", rc=r.returncode)
    # launch.json: the Cobalto extension (COBOL names, breakpoints in the .cblt,
    # step by statement) and, as alternatives without it, plain lldb-dap and CodeLLDB
    program = "${workspaceFolder}/" + exe.replace(os.sep, "/")
    name = LAUNCH_NAME.format(suite=suite)
    configs = [
        {"name": name, "type": "cobalto", "request": "launch",
         "suite": suite, "cwd": "${workspaceFolder}"},
        {"name": name + " (plain lldb-dap)", "type": "lldb-dap", "request": "launch",
         "program": program, "cwd": "${workspaceFolder}", "stopOnEntry": False,
         "initCommands": ["settings set target.inline-breakpoint-strategy always"]},
        {"name": name + " (CodeLLDB)", "type": "lldb", "request": "launch",
         "program": program, "cwd": "${workspaceFolder}"},
    ]
    launch = os.path.join(".vscode", "launch.json")
    if write_launch_json(launch, configs):
        print(f"launch.json: {launch}  (configuration '{configs[0]['name']}')")
    else:
        alt = os.path.join(build, "launch.json")
        write_launch_json(alt, configs)
        print(f"{launch} is not valid JSON (comments?); the configuration was written to {alt}")
    # map of COBOL variables -> C statics for the variables panel
    inprog_src = gen.inprog.get(suite)
    targets = [suite] + ([os.path.splitext(inprog_src)[0]] if inprog_src else [])
    for src in gen.sources:
        base = os.path.splitext(os.path.basename(src))[0]
        if base not in targets:
            targets.append(base)
    vars_path = os.path.join(build, f"{suite}.vars.txt")
    vars_text = format_vars_map(targets, build)
    if vars_text:
        with open(vars_path, "w", encoding="utf-8") as fh:
            fh.write(vars_text)
        print(f"COBOL variables -> generated C: {vars_path}")
    # map of generated lines -> (source file, line): the VS Code extension
    # uses it to set breakpoints in the .cblt and to show the stack on the
    # source the person wrote, not on the generated copy
    lines_path = os.path.join(build, f"{suite}.lines.json")
    origins = {}
    for gf in gen.gen_files:
        lm = gen.linemaps.get(os.path.normpath(gf))
        if lm:
            origins[gf.replace(os.sep, "/")] = [list(o) if o else None for o in lm]
    if origins:
        with open(lines_path, "w", encoding="utf-8") as fh:
            json.dump({"schema": SCHEMA, "cobalto": VERSION, "suite": suite, "origins": origins}, fh,
                      ensure_ascii=False)
            fh.write("\n")
        print(f"map of generated lines -> source: {lines_path}")
    # data layout of each program (every item, not only the referenced ones)
    layout_files = [os.path.join(cfg["lib"], "CBLTLIB.cbl"), gen.driver] + gen.tests + gen.sources
    layout_path, layout_programs = write_layout(cfg, prof, build, suite, layout_files, targets)
    n_items = sum(len(pg["items"]) for pg in layout_programs.values())
    n_warn = sum(len(pg["warnings"]) for pg in layout_programs.values())
    print(f"data layout ({len(layout_programs)} programs, {n_items} level 01/77 items"
          + (f", {n_warn} groups with an inconsistent size" if n_warn else "") + f"): {layout_path}")
    where = f"build/{suite}.cbl (in-program copy of {inprog_src})" if inprog_src else f"build/{suite}.cbl or the program under test in src/"
    dap = subprocess.run("xcrun -f lldb-dap 2>/dev/null || command -v lldb-dap", shell=True,
                         capture_output=True, text=True).stdout.strip()
    suite_src = next((os.path.relpath(s.file) for s in gen.suites if s.id == suite), None)
    print("Steps in VS Code with the Cobalto extension (vscode-cobalto):")
    print(f"  1. Breakpoint in {suite_src + ' (inside a TESTCASE) or in ' if suite_src else ''}{where}")
    print(f"  2. Run and Debug > '{configs[0]['name']}'  (or the command 'Cobalto: Debug suite')")
    print("  Variables show with their COBOL names and F10 steps one COBOL statement.")
    print("Without the extension, with 'LLDB DAP' (llvm-vs-code-extensions.lldb-dap)"
          + (f"; if it cannot find the adapter: \"lldb-dap.executable-path\": \"{dap}\"" if dap else "") + ":")
    print(f"  1. Breakpoint in {where}")
    print(f"  2. Run and Debug > '{configs[1]['name']}'")
    print("  COBOL variables show as b_NNN (bytes); each program has its own numbering.")
    print("  The .vars.txt file says which field each one is and which expression to type in the console.")
    return 0


def cmd_suggest(a):
    """Asks a model for a suite for a program, runs it with coverage, feeds
    the result back, and keeps the best round."""
    cfg = load_config(a.config)
    ai = dict(cfg.get("ai", {}))
    for k in ("backend", "command", "model"):
        if getattr(a, k, None):
            ai[k] = getattr(a, k)
    rounds = a.rounds or int(ai.get("rounds", sugg.DEFAULT_ROUNDS))
    max_cases = a.max_cases or int(ai.get("max_cases", sugg.DEFAULT_MAX_CASES))
    focus = (a.mode or ai.get("mode") or "auto").lower()
    if focus not in sugg.FOCUS_RULES:
        raise CobaltoError("E200", file=a.config, line="ai.mode", detail=f"possible values: {', '.join(sugg.FOCUS_RULES)}")
    fill = a.fill_expected or bool(ai.get("fill_expected"))
    pname, _ = profile_of(cfg, a.profile)

    # program, parser and existing suites
    path = a.program if os.path.isfile(a.program) else resolve_program(a.program, cfg, a.config)
    try:
        prog = cobparse.Program(path, copy_dirs_of(cfg))
    except cobparse.ParseError as e:
        raise CobaltoError("E404", detail=str(e))
    prog_name = prog.program_id
    source = "".join(ln.text + "\n" for ln in prog.lines)
    summary = cobparse.summary(prog)
    mode = sugg.suggest_mode(prog)
    suite_id = (prog_name.replace("-", "") + "AI")[:30]
    existing = []
    for f in expand(cfg["tests"]):
        if not f.lower().endswith(".cblt") or os.path.basename(f).upper() == f"{prog_name}.AI.CBLT":
            continue
        try:
            st = parse_dsl(f)
        except (DslError, ValueError):
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        same = st.program and os.path.normpath(resolve_program(st.program, cfg, f)) == os.path.normpath(path)
        if same or re.search(r"CALL\s+[\'\"]" + re.escape(prog_name) + r"[\'\"]", text, re.I):
            existing.append(text)
    existing_text = "\n".join(existing) if existing else None

    out_dir = os.path.join(cfg["build"], "ai")
    os.makedirs(out_dir, exist_ok=True)
    out_path = a.out or os.path.join(os.path.dirname(expand(cfg["tests"])[0]) if expand(cfg["tests"]) else "tests",
                                     f"{prog_name}.ai.cblt")
    backend = None if a.dry_run else sugg.pick_backend(ai)
    print(f"Cobalto {VERSION}  suggest: {path} ({prog_name}, {mode} mode"
          + (f", {focus} cases" if focus != "auto" else "") + ")"
          + (f"  backend {backend}" if backend else "  (--dry-run)")
          + (f"  existing suite: yes" if existing else "")
          + ("  expected values taken from the program" if fill else ""))

    # temporary configuration to run only the round
    run_cfg = dict(cfg)
    run_cfg_path = os.path.join(out_dir, "cblt.json")
    # the round runs in a process of its own, with this same package
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        x for x in (package_root, os.environ.get("PYTHONPATH")) if x))

    results_json = os.path.join(cfg["build"], "results.json")

    def run_round(round_file):
        """Runs the suite of the round on its own. Returns the process and the
        run model, or None if it did not get to run (DSL or compile error)."""
        run_cfg["tests"] = [round_file]
        with open(run_cfg_path, "w", encoding="utf-8") as fh:
            json.dump(run_cfg, fh, indent=2)
        if os.path.exists(results_json):
            os.remove(results_json)
        r = subprocess.run([sys.executable, "-m", "cobalto", "--config", run_cfg_path, "test", "--coverage",
                            "--profile", pname], capture_output=True, text=True, env=env)
        if not os.path.exists(results_json):
            return r, None
        with open(results_json, encoding="utf-8") as fh:
            return r, json.load(fh)

    def round_feedback(r, run):
        """What goes back to the model: the test cases and the coverage of the
        program under test, or the errors if the round did not get to run."""
        if run is None:
            return sugg.tail(r.stdout + "\n" + r.stderr)
        lines = render_console(run, False)
        cov = sugg.program_coverage(run, prog_name)
        covmod.print_report([cov] if cov else [], out=lines.append)
        return sugg.tail("\n".join(lines) + "\n" + r.stderr)

    def interior_cases(round_file):
        """Internal cases of the round (as classified by inprog)."""
        try:
            st = parse_dsl(round_file)
        except (DslError, ValueError):
            return []
        if not st.program:
            return []
        inprog.classify_cases(st, prog, inprog.entry_name(prog))
        return [c for c in st.cases if c.kind == "internal"]

    best = None          # (score, n, suite_text, summary, (failures, errors))
    previous = output = lint = advice = None
    for n in range(1, rounds + 1):
        feedback = " ".join(x for x in (lint, advice) if x) or None
        prompt = sugg.build_prompt(path, source, summary, suite_id, prog_name, mode, max_cases,
                                   existing=existing_text, previous=previous, output=output,
                                   lint=feedback, focus=focus)
        base = os.path.join(out_dir, f"{prog_name}.round{n}")
        with open(base + ".prompt.txt", "w", encoding="utf-8") as fh:
            fh.write(sugg.SYSTEM + "\n\n" + prompt)
        if a.dry_run:
            print(f"  round {n}: prompt in {base}.prompt.txt ({len(prompt.splitlines())} lines); nothing was sent")
            return 0
        print(f"  round {n}: asking the model ...", flush=True)
        answer = sugg.ask(ai, backend, sugg.SYSTEM, prompt, a.verbose)
        with open(base + ".response.txt", "w", encoding="utf-8") as fh:
            fh.write(answer)
        suite_text = sugg.extract_suite(answer, suite_id)
        if suite_text is None:
            raise CobaltoError("E602", path=base + ".response.txt")
        round_file = base + ".cblt"
        with open(round_file, "w", encoding="utf-8") as fh:
            fh.write(suite_text)
        lint = sugg.lint_suite(suite_text)
        r, run = run_round(round_file)
        if fill and not lint:
            patched, nfill = sugg.fill_expected(suite_text, run)
            if nfill:
                suite_text = patched
                with open(round_file, "w", encoding="utf-8") as fh:
                    fh.write(suite_text)
                print(f"  round {n}: {nfill} expected value(s) replaced by the ones the program "
                      f"produces (characterization); running again")
                r, run = run_round(round_file)
        output = round_feedback(r, run)
        if a.verbose:
            print("\n".join("    | " + l for l in output.splitlines()))
        interior = interior_cases(round_file) if focus == "interface" else []
        advice = None
        if interior:
            detail = "; ".join(f"'{c.name}' ({', '.join(reason_text(x) for x in c.reasons[:2])})"
                               for c in interior[:6])
            advice = (f"{len(interior)} case(s) touch the inside of the program and only interface "
                      f"cases were requested: {detail}. Rewrite them to go in through RUN / RUN USING "
                      f"(or CALL) and to check only what comes out.")
        score, text, perfect, bad = sugg.score_run(run, r.returncode, prog_name, lint, len(interior))
        print(f"  round {n}: {text}" + (f"  ({lint})" if lint else "")
              + (f"  ({len(interior)} internal)" if interior else "") + f"  -> {round_file}")
        if best is None or score > best[0]:
            best = (score, n, suite_text, text, bad)
        elif n >= 2:
            print("  no improvement over the best round; stopping")
            break
        if perfect:
            print("  every test case passes and the program is 100% covered")
            break
        previous = suite_text

    score, n, suite_text, text, bad = best
    if not score[0]:
        print("  " + msg("W601", dir=out_dir))
        return 1
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(suite_text)
    print(f"\nDraft: {out_path}  (round {n}: {text})")
    if bad[0] or bad[1]:
        print("  " + msg("W602", fails=bad[0], errors=bad[1]))
    print("  Review the test cases and the expected values before accepting them; "
          "then run: cobalto test --coverage")
    return 0


def cmd_init(a):
    """Creates the folders and a cblt.json that only states where the
    programs and the suites are. The COBOL core and the profiles are the
    ones that ship with the CLI."""
    root = os.path.abspath(a.dir)
    for d in ("src", "tests"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    cfg_path = os.path.join(root, "cblt.json")
    if not os.path.exists(cfg_path):
        write_json(cfg_path, {"profile": DEFAULTS["profile"], "sources": DEFAULTS["sources"],
                              "tests": DEFAULTS["tests"], "copybooks": ["src"]})
    print(f"Cobalto project initialized in {root}: cblt.json, src/, tests/")
    return 0


def cmd_list(a):
    """Lists the suites and their test cases as the CLI reads them. Nothing
    is generated or compiled."""
    suites, errors = list_suites(load_config(a.config))
    for s in suites:
        what = f"{len(s['cases'])} case(s)" if s["dsl"] else "COBOL test without the DSL"
        print(f"  {s['id']:10s} {s['file']}  ({what})" + (f"  {s['description']}" if s["description"] else ""))
    for e in errors:
        print(f"{e['code']}: {e['message']}", file=sys.stderr)
    emit_json({"suites": suites, "errors": errors})
    return 2 if errors else 0


def cmd_profiles(a):
    """Lists the built-in profiles and the project's, and marks the default."""
    cfg = load_config(a.config, required=False)
    profiles = [{"name": n, "kind": "remote" if "remote" in p else "local", "description": p.get("description", "")}
                for n, p in cfg["profiles"].items()]
    for p in profiles:
        mark = "*" if p["name"] == cfg["profile"] else " "
        print(f" {mark} {p['name']:18s} {p['kind']:6s}  {p['description']}")
    emit_json({"default": cfg["profile"], "profiles": profiles})
    return 0


def cmd_parse(a):
    """Shows what the parser understands of a program (to diagnose a MOCK
    that cannot find its paragraph or file)."""
    copy_dirs = copy_dirs_of(load_config(a.config, required=False))
    rc, programs, errors = 0, [], []
    for f in a.files:
        try:
            prog = cobparse.Program(f, copy_dirs)
            programs.append(cobparse.describe(prog))
            print(cobparse.summary(prog))
        except (cobparse.ParseError, OSError) as e:
            warn("E404", detail=str(e))
            errors.append({"file": f, "code": "CBLT-E404", "message": MESSAGES["E404"].format(detail=str(e))})
            rc = 2
    emit_json({"programs": programs, "errors": errors})
    return rc
