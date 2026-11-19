#!/usr/bin/env python3
"""suggest - AI-assisted test generation for Cobalto (CBLT). Stdlib only.

A language model proposes a .cblt suite for a program from its source and
from what Cobalto's own parser understands of it; the CLI runs the suite,
gives the model back the compile errors, the failures and the portable
coverage, and repeats until there is no improvement or the rounds run out.
The result is a draft in tests/<PROGRAM>.ai.cblt that a person reviews
before accepting it.

What is sent to the AI provider (and nothing else): the program source
with its copybooks expanded, the parser summary, the hand-written suite if
there is one, and the console output of each round. Every request is
saved in build/ai/<PROGRAM>.round<n>.prompt.txt so it can be audited, and
--dry-run builds the request without sending it.

Backends:
- "api": Anthropic's Messages API over HTTP (urllib), with the key in the
  ANTHROPIC_API_KEY environment variable, which is never printed or stored.
- "command": a command that receives the prompt on stdin and returns text
  on stdout; by default the Claude Code CLI (`claude -p`), which uses the
  user's session. It works for any other provider that has a CLI.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request

from .messages import CobaltoError

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
API_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_COMMAND = "claude -p --permission-mode dontAsk --output-format text"
DEFAULT_ROUNDS = 2
DEFAULT_MAX_CASES = 12
MAX_WIDTH = 72

SYSTEM = """\
You are a test engineer with expert knowledge of COBOL. Your task is to write a \
unit test suite for a COBOL program with Cobalto, a tool that \
expands a DSL (.cblt file) into standard COBOL 85 and compiles it with the \
user's compiler. The tests are characterization tests: they document what \
the program does today, with input values that you invent, to protect it when it changes.

RESPONSE: return only the complete suite inside a single \
```cobol ... ``` block. No explanations before or after it. If you are asked to fix it, \
return the entire corrected suite, not a diff.

FORMAT: fixed-format COBOL. The DSL keywords (TESTSUITE, PROGRAM, \
WORKING-STORAGE SECTION., BEFORE-EACH, END-BEFORE, AFTER-EACH, END-AFTER, \
TESTCASE, IGNORE, MOCK, END-MOCK, ON, EXPECT, VERIFY) go in column 8; the \
COBOL of the cases goes from column 12 on. No line goes past column 72. \
Comments: asterisk in column 7. COBOL 85 only: MOVE, ADD, COMPUTE, \
PERFORM, CALL, IF, EVALUATE, STRING, INSPECT; no GOBACK, no intrinsic \
functions and no dialect syntax. The statements inside TESTCASE, \
BEFORE-EACH, AFTER-EACH and MOCK do NOT end with a period.

DSL (everything that is not a keyword is ordinary COBOL and is copied as is):
  TESTSUITE id 'description'         first line; use the id you are given
  PROGRAM name                       turns on in-program mode (see below)
  WORKING-STORAGE SECTION.           the suite's own fields (01 ... PIC ...)
  BEFORE-EACH ... END-BEFORE         COBOL that runs before each case
  AFTER-EACH ... END-AFTER           COBOL that runs after each case
  TESTCASE 'description'             one case; short description, in English
  IGNORE                             marks the next TESTCASE as ignored
  EXPECT field TO BE 'text'          alphanumeric equality (ignores trailing spaces)
  EXPECT field TO BE identifier      equality with another field
  EXPECT field NOT TO BE 'text'      inequality
  EXPECT field TO BE NUMERIC n       numeric equality (works for COMP-3, binary)
  EXPECT field TO BE GREATER THAN expr / LESS THAN expr
  EXPECT field TO BE BETWEEN a AND b
  EXPECT condition-88 TO BE TRUE / FALSE
  EXPECT field TO BE SPACES / ZEROS
  EXPECT field TO CONTAIN 'text'
The forms with 'text', NOT TO BE, CONTAIN and SPACES are for alphanumeric \
fields (PIC X). On a numeric field (PIC 9, V, COMP) use only \
NUMERIC, GREATER THAN, LESS THAN, BETWEEN or ZEROS.

TWO MODES:
1) External (no PROGRAM): the suite declares its fields, does CALL "PROGRAM" \
USING ... with the parameters of the LINKAGE SECTION and checks the results. \
Use it when the program is a subprogram whose entire logic runs in one CALL.
2) In-program (with PROGRAM name): the cases run INSIDE a copy of the \
program: they can PERFORM any paragraph, read and set any \
field of its WORKING-STORAGE, and the LINKAGE items become WORKING-STORAGE items \
(they are set with MOVE). MOCK and VERIFY exist only in this mode:
  MOCK PARAGRAPH name ... END-MOCK      replaces the paragraph with the block
  MOCK CALL 'PROG' ... END-MOCK         replaces the CALLs; the block can set
                                        the parameters, which are fields of the program
  MOCK FILE file                        replaces OPEN/CLOSE/READ/WRITE/REWRITE/
      ON READ                           DELETE/START on the file; in ON READ you
          EVALUATE CBLT-READ-COUNT      fill in the FD record (1st read:
              WHEN 1 MOVE ... TO REC    CBLT-READ-COUNT = 1, etc.) and
              WHEN OTHER                SET CBLT-AT-END TO TRUE signals end of file;
                  SET CBLT-AT-END TO TRUE   in ON WRITE the record is already filled in
          END-EVALUATE                  and can be copied to a field of the suite
      ON WRITE ...                      to check it. With no blocks: all no-ops.
  END-MOCK
  MOCK SQL ['text'] ... END-MOCK        replaces EXEC SQL (sets host variables and SQLCODE)
  MOCK CLOCK ... END-MOCK               lines DATE 'yymmdd' / DATE YYYYMMDD '...' /
                                        DAY 'yyddd' / TIME 'hhmmsscc' for ACCEPT FROM
  VERIFY PARAGRAPH name HAPPENED n TIMES     (ONCE, NEVER HAPPENED, AT LEAST n TIMES,
  VERIFY CALL 'PROG' HAPPENED ONCE            NO MORE THAN n TIMES); also VERIFY
  VERIFY READ file HAPPENED n TIMES           WRITE|REWRITE|DELETE|START|OPEN|CLOSE,
                                              VERIFY SQL, VERIFY CLOCK, VERIFY STOP
  RUN                                   executes the whole original flow from its
  RUN USING arg1 arg2 ...               entry point; with USING it sets the parameters of
                                        PROCEDURE DIVISION USING by position and on
                                        return copies the fields back (like a
                                        CALL BY REFERENCE). In the copy, STOP RUN,
                                        GOBACK and EXIT PROGRAM end the case, not
                                        the process: CBLT-STOPPED is left TRUE and
                                        VERIFY STOP HAPPENED ONCE checks it.
  Inside a MOCK CALL, CBLT-CALL-COUNT is 1 on the first call of the case,
  2 on the second, etc. (to answer differently on each call).
A MOCK applies only to the TESTCASE that declares it (or to all of them if it is in BEFORE-EACH).

TWO KINDS OF CASE (Cobalto classifies them and shows them in the report):
- interface: enters through CALL (external) or through RUN / RUN USING (in-program), \
simulates everything external (files, CALL, SQL, clock) and checks ONLY what comes out: \
LINKAGE parameters, records captured in ON WRITE, VERIFY CALL/READ/WRITE/STOP, \
EXPECT inside a MOCK CALL on the parameters received, and the suite's own \
fields (T-*). It does not PERFORM internal paragraphs and does not touch the program's \
WORKING-STORAGE outside a MOCK. These are the cases that stay just as valid after a rewrite or a migration, \
even if the language changes.
- internal: PERFORM of a single paragraph, MOCK PARAGRAPH, VERIFY PARAGRAPH, \
EXPECT or MOVE on fields of the program's WORKING-STORAGE. They pinpoint a \
defect and support a refactoring for as long as the COBOL stays alive.

GOLDEN RULES:
- To execute the main flow use RUN (or RUN USING), never PERFORM of the \
main paragraph. The program's STOP RUN / GOBACK do not cut the suite short.
- One case per behavior: each branch of an IF/EVALUATE, each AT END / \
INVALID KEY, each category of data, limits (zero, maximum, empty).
- Invent your own input values, consistent with the PICs; never assume real data.
- Expected values come from reading the code, not from guessing. If a rule \
is not clear, write the EXPECT anyway with the value the code produces and \
put a REVIEW comment above it.
- File operations, CALLs to other programs, EXEC SQL statements and \
ACCEPT FROM DATE/TIME are mocked in every case that goes through them.
- T- prefix for the suite's own fields, so they do not clash with the program's. \
Do not redeclare fields the program already has. Do not use CBLT-* names.
- Paragraph, field and file names exactly as they appear in the program.
"""

FOCUS_RULES = {
    "auto": "",
    "interface": """
KIND OF CASE REQUESTED: INTERFACE ONLY. Each case enters through CALL or through RUN / \
RUN USING, simulates everything external and checks only what comes out. No PERFORM of \
internal paragraphs, no MOCK PARAGRAPH, no VERIFY PARAGRAPH, and no EXPECT or MOVE on \
fields of the program's WORKING-STORAGE outside a MOCK (the LINKAGE \
parameters and the file records may be used). To prepare the \
input use the parameters, the records of the MOCK FILE blocks, MOCK CALL, \
MOCK SQL and MOCK CLOCK. To check outputs use the parameters, the suite's \
own T-* fields set in ON WRITE or inside a MOCK CALL, VERIFY and \
CBLT-STOPPED. A case that touches the internals counts as an error of the round.
""",
    "in-program": """
KIND OF CASE REQUESTED: INTERNAL. Test each logic paragraph separately \
with PERFORM, preparing its WORKING-STORAGE fields and simulating everything external; \
add interface cases with RUN only for the complete path.
""",
}

PROMPT_HEAD = """\
Program under test: {path}
Suggested mode: {mode}
Suite id (use it exactly): TESTSUITE {suite_id} '...'{program_line}
Maximum number of cases in this round: {max_cases}.{focus}

```cobol
{source}```

What the Cobalto parser sees in the program:
{summary}
"""

PROMPT_EXISTING = """
A hand-written suite for this program already exists. Do not repeat its cases: \
cover what it is missing (branches, paragraphs and limits it does not touch).
```cobol
{existing}```
"""

PROMPT_FEEDBACK = """
This is the suite you proposed in the previous round:
```cobol
{previous}```

Result of compiling and running it with Cobalto:
```
{output}```
{lint}
What to do:
- If there is a CBLT-E200 or CBLT-E201: fix exactly that line (the line \
number shown is the one in the .cblt).
- If a case shows FAIL: reread the code. If the expected value was wrong, \
change it to the one the program produces (these are characterization tests). If the \
data of the case was set up wrong, fix the data.
- If there are paragraphs tagged NOT EXECUTED, statements not executed or branches not executed \
(a WHEN, an implicit ELSE, an AT END), add cases that execute them (up to \
the maximum number of cases), without removing the ones that already pass.
Return the complete suite.
"""


# ------------------------------------------------------------------ backend
class SuggestError(CobaltoError):
    """An error of the AI backend or of its answer."""


def pick_backend(ai):
    b = ai.get("backend", "auto")
    if b == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "api"
        if shutil.which(shlex.split(ai.get("command") or DEFAULT_COMMAND)[0]):
            return "command"
        raise SuggestError("E600", detail="neither ANTHROPIC_API_KEY in the environment nor the command "
                           f"'{shlex.split(ai.get('command') or DEFAULT_COMMAND)[0]}' on the PATH")
    if b not in ("api", "command"):
        raise SuggestError("E600", detail=f"unknown backend '{b}' (api, command or auto)")
    return b


def call_api(ai, system, prompt, verbose):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SuggestError("E600", detail="api backend without ANTHROPIC_API_KEY in the environment")
    body = {"model": ai.get("model") or DEFAULT_MODEL,
            "max_tokens": int(ai.get("max_tokens", 16000)),
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": ai.get("effort", "high")},
            "fallbacks": "default"}
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json", "x-api-key": key,
                                          "anthropic-version": API_VERSION, "anthropic-beta": API_BETA})
    try:
        with urllib.request.urlopen(req, timeout=int(ai.get("timeout", 600))) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", {})
            detail = f"HTTP {e.code} {err.get('type', '')}: {err.get('message', '')}"
        except Exception:
            detail = f"HTTP {e.code}"
        raise SuggestError("E601", backend="api", detail=detail)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SuggestError("E601", backend="api", detail=str(e))
    if resp.get("stop_reason") == "refusal":
        sd = resp.get("stop_details") or {}
        raise SuggestError("E601", backend="api",
                           detail=f"the model refused the request ({sd.get('category')}): {sd.get('explanation')}")
    if verbose:
        u = resp.get("usage", {})
        print(f"  api: model {resp.get('model')}  input tokens {u.get('input_tokens')}  "
              f"output {u.get('output_tokens')}  stop {resp.get('stop_reason')}")
    return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")


def call_command(ai, system, prompt, verbose):
    cmd = ai.get("command") or DEFAULT_COMMAND
    model = ai.get("model", "")
    if "{model}" in cmd:
        cmd = cmd.replace("{model}", shlex.quote(model))
    elif model and cmd.startswith("claude "):
        cmd += " --model " + shlex.quote(model)
    if verbose:
        print(f"  command: {cmd}")
    text = system + "\n\n" + prompt
    argv = shlex.split(cmd)
    env = dict(os.environ)
    if os.path.basename(argv[0]) == "claude":
        # a nested claude (suggest run from inside a Claude Code session)
        # inherits variables that make its authentication fail
        for k in list(env):
            if k.startswith("CLAUDE") or k == "ANTHROPIC_BASE_URL":
                del env[k]
    try:
        r = subprocess.run(argv, input=text, capture_output=True, text=True, env=env,
                           timeout=int(ai.get("timeout", 900)))
    except FileNotFoundError:
        raise SuggestError("E601", backend="command", detail=f"'{shlex.split(cmd)[0]}' not found")
    except subprocess.TimeoutExpired:
        raise SuggestError("E601", backend="command", detail="the command did not respond in time")
    if r.returncode != 0 or not r.stdout.strip():
        detail = (r.stderr.strip() or r.stdout.strip() or "no output").splitlines()[-1][:200]
        raise SuggestError("E601", backend="command", detail=f"exit {r.returncode}: {detail}")
    return r.stdout


def ask(ai, backend, system, prompt, verbose):
    return (call_api if backend == "api" else call_command)(ai, system, prompt, verbose)


# ------------------------------------------------------------------ prompt
def suggest_mode(prog):
    """External for subprograms with USING and no paragraphs worth isolating."""
    paras = [p for p in prog.paragraphs if not p.is_section]
    if prog.procedure_using and len(paras) <= 1:
        return "external"
    return "in-program"


def build_prompt(path, source, summary_text, suite_id, prog_name, mode, max_cases,
                 existing=None, previous=None, output=None, lint=None, focus="auto"):
    program_line = f"\nProgram for the PROGRAM line: {prog_name}" if mode == "in-program" else \
        "\nNo PROGRAM line (external mode): CALL the program with its parameters."
    p = PROMPT_HEAD.format(path=path, mode=mode, suite_id=suite_id, program_line=program_line,
                           max_cases=max_cases, source=source if source.endswith("\n") else source + "\n",
                           summary=summary_text, focus=FOCUS_RULES.get(focus, ""))
    if existing:
        p += PROMPT_EXISTING.format(existing=existing if existing.endswith("\n") else existing + "\n")
    if previous is not None:
        p += PROMPT_FEEDBACK.format(previous=previous if previous.endswith("\n") else previous + "\n",
                                    output=output if output.endswith("\n") else output + "\n",
                                    lint=("Also: " + lint + "\n") if lint else "")
    else:
        p += "\nWrite the suite.\n"
    return p


FENCE = re.compile(r"```[A-Za-z]*\n(.*?)```", re.S)


def extract_suite(text, suite_id):
    """Extracts the suite from the ```...``` block (or takes everything), sets
    the TESTSUITE id and normalizes whitespace. None if it is not a suite."""
    m = FENCE.search(text)
    body = m.group(1) if m else text
    lines = [l.rstrip().expandtabs(4) for l in body.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    out, fixed = [], False
    for l in lines:
        if not fixed and re.match(r"\s*TESTSUITE\s", l, re.I):
            l = re.sub(r"(\s*TESTSUITE\s+)\S+", lambda mm: mm.group(1) + suite_id, l, count=1, flags=re.I)
            fixed = True
        out.append(l)
    if not fixed:
        return None
    return "\n".join(out) + "\n"


def lint_suite(text):
    long_lines = [i for i, l in enumerate(text.splitlines(), 1) if len(l) > MAX_WIDTH]
    if long_lines:
        return (f"{len(long_lines)} line(s) go past column {MAX_WIDTH} and the compiler would "
                f"truncate them: {', '.join(str(x) for x in long_lines[:10])}. Split them.")
    return ""


# ------------------------------------------------------------------ rounds
# A round runs the CLI and reads build/results.json, the model of the run
# (see build_run in results.py). Nothing below parses the console output.
def program_coverage(run, prog_name):
    """Coverage summary of the program under test inside the run model."""
    for prog in (run or {}).get("coverage") or []:
        if prog["program"] == prog_name:
            return prog
    return None


def score_run(run, rc, prog_name, lint, interior=0):
    """Score of a round: (compiled, -(failures+errors), -internal cases
    that were not requested, covered statements of the program, cases
    ok), a readable summary, whether it came out perfect, and (failures,
    errors). run is None if the round did not get to execute (DSL or
    compile error)."""
    compiled = run is not None and rc != 2 and not lint
    totals = run["totals"] if run else {}
    cases, fails, errors = (totals.get(k, 0) for k in ("cases", "failed_asserts", "errors"))
    cov = program_coverage(run, prog_name)
    shit, stot = (cov["statements"]["hit"], cov["statements"]["total"]) if cov else (0, 0)
    ok = max(0, cases - errors) if compiled else 0
    text = (f"cases {cases}  failures {fails}  errors {errors}  statements {shit}/{stot}"
            + (f"  internal {interior}" if interior else "")
            if compiled else "did not compile")
    perfect = compiled and fails == 0 and errors == 0 and not interior and stot and shit == stot
    return (compiled, -(fails + errors), -interior, shit, ok), text, perfect, (fails, errors)


# ------------------------------------------------ deterministic characterization
EXPECT_NUM_RE = re.compile(r"^(\s*EXPECT\s+\S+\s+TO\s+BE\s+)(NUMERIC\s+\S+|ZEROS?|ZEROES)(\s*)$", re.I)
EXPECT_STR_RE = re.compile(r"^(\s*EXPECT\s+\S+\s+TO\s+BE\s+)('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|SPACES?|TRUE|FALSE)(\s*)$", re.I)


def plain_number(act):
    """'987.640' -> '987.64', '0.000' -> '0', '-12.500' -> '-12.5'."""
    s = act.strip()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def fill_expected(suite_text, run):
    """Characterization tests without spending a model round: every
    EXPECT that failed on an equality (numeric, alphanumeric, SPACES/ZEROS,
    TRUE/FALSE) now expects the value the program produced, with a
    REVIEW comment that keeps the original. run is the model of the
    run (results.json). Returns (text, n)."""
    lines = suite_text.splitlines()
    # (case, EXPECT message) -> [(kind, actual)]
    fails = {}
    for suite in (run or {}).get("suites", []):
        for case in suite["cases"]:
            for a in case["asserts"]:
                if a["status"] == "failed" and a["message"].startswith("EXPECT "):
                    fails.setdefault((case["name"], a["message"].strip()), []).append((a["kind"], a["actual"]))
    if not fails:
        return suite_text, 0
    done, cur_case, used = 0, None, {}
    out = []
    for l in lines:
        m = re.match(r"^\s*TESTCASE\s+(.*)$", l, re.I)
        if m:
            cur_case = m.group(1).strip().strip("'\"")[:60]
        key = (cur_case, l.strip()[:60]) if cur_case and re.match(r"^\s*EXPECT\s", l, re.I) else None
        if key in fails and used.get(key, 0) < len(fails[key]):
            kind, act = fails[key][used.get(key, 0)]
            used[key] = used.get(key, 0) + 1
            new = None
            mn, ms = EXPECT_NUM_RE.match(l), EXPECT_STR_RE.match(l)
            if kind == "EQNUM" and mn:
                new = f"{mn.group(1)}NUMERIC {plain_number(act)}"
            elif kind == "EQUALS" and ms:
                old = ms.group(2).upper()
                if old in ("TRUE", "FALSE"):
                    new = f"{ms.group(1)}{'FALSE' if old == 'TRUE' else 'TRUE'}"
                elif len(act.rstrip()) < 60:
                    val = act.rstrip()
                    new = f"{ms.group(1)}SPACES" if not val else f"{ms.group(1)}'{val.replace(chr(39), chr(39) * 2)}'"
            if new and len(new) <= MAX_WIDTH:
                old_val = (mn or ms).group(2)
                out.append(("      * REVIEW: original expected value " + old_val)[:MAX_WIDTH])
                out.append("      * (replaced by the value the program produces)")
                out.append(new)
                done += 1
                continue
        out.append(l)
    return "\n".join(out) + "\n", done


def tail(text, n=60):
    """Last n non-empty lines of a text, to give back to the model."""
    return "\n".join([l for l in text.splitlines() if l.strip()][-n:])
