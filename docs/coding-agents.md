# Using Cobalto from a coding agent

Coding agents are natural users of Cobalto. The agent reads a program and proposes test cases, and Cobalto says what really happens when they run: which cases pass, the expected and actual value of every assert that fails, and which statements and branches no case reached. A suite that was not run is evidence of nothing, so every claim the agent makes about the program should come from a run, not from reading the source.

This page covers Claude Code, the agent the repository ships a skill for: how to install the skill, the loop it follows, which outputs an agent should read and which ones it can rely on, and how all of this relates to `cobalto suggest`. To work on Cobalto itself with an agent, see [AGENTS.md](../AGENTS.md) instead.

## Claude Code

### Install the CLI

The agent runs the same `cobalto` command a person does, so install it first, as the [README](../README.md#try-it) describes: from a clone of the repository, in a virtual environment. The skill looks for the command on the `PATH` and in the project's `.venv/bin/`.

### Install the skill

The skill is the folder [.claude/skills/cobalto/](../.claude/skills/cobalto/) of this repository: [SKILL.md](../.claude/skills/cobalto/SKILL.md), with the loop and the rules, and [references/dsl.md](../.claude/skills/cobalto/references/dsl.md), with the suite language. It is not part of the Python package, so installing the CLI does not install it. Copy the whole folder from a clone of Cobalto to one of the two places where Claude Code looks for skills.

For one project, into the project's own `.claude/skills/`. Commit it there, and everyone who opens the project in Claude Code gets the skill:

```bash
mkdir -p /path/to/project/.claude/skills
```

```bash
cp -R /path/to/cobalto/.claude/skills/cobalto /path/to/project/.claude/skills/
```

For one user, in every project on that machine, into `~/.claude/skills/`:

```bash
mkdir -p ~/.claude/skills
```

```bash
cp -R /path/to/cobalto/.claude/skills/cobalto ~/.claude/skills/
```

The description of the skill tells Claude Code to use it when a task touches COBOL and tests, or when the project has a `cblt.json` or `.cblt` files. It can also be invoked by name, with `/cobalto`. Claude Code's [documentation on skills](https://code.claude.com/docs/en/skills) has the details of where skills load from.

The skill describes the suite language and the messages of the Cobalto version it came with. When you update the CLI, copy the skill again from the same version.

### Other agents

The skill is plain Markdown, and nothing in it is specific to Claude Code except where it is installed. Other agents have not been tried. One that reads its instructions from a file can be pointed at `SKILL.md` and `references/dsl.md`.

## The loop the skill follows

[SKILL.md](../.claude/skills/cobalto/SKILL.md) has the full instructions. In short:

1. **Find the project and the CLI.** The project is the folder with `cblt.json`, and every command runs from there. Without one, `cobalto init` creates it.
2. **Learn the program from the parser.** `cobalto parse src/PROGRAM.cbl` lists the paragraphs, the files, the `CALL`, file, SQL and clock statements with their lines, and the data items. The names a suite uses come from that output, not from a guess. If the program already has a suite, the agent reads it to cover what is missing.
3. **Write the suite**, in `tests/NAME.cblt`. Interface cases, which only look at what goes in and comes out, when the goal is to protect a rewrite or a translation. Internal cases, on single paragraphs and fields, when the goal is to understand or fix one rule.
4. **Run it with coverage**, on its own: `cobalto test --coverage --filter TSTNAME`.
5. **Fix what the output says.** A syntax or compile error points at a line of the `.cblt`, or of the original program in an in-program suite. A name that does not exist in the program comes back as `CBLT-E401`, `E402` or `E403`. A failure shows the expected and the actual value, and the agent has to decide whether it deduced the value wrongly or found a defect. A defect is kept as current behavior with a `REVIEW` comment for a person to decide; the agent does not change the program or loosen the assert to make the case pass. The coverage table shows the statements and branches that no case reached.
6. **Run every suite at the end**, with `cobalto test` and no filter, to confirm the new suite did not break the others.
7. **Report** the totals, how many cases are interface cases and how many internal, the coverage of the program and what was left out, and every `REVIEW`.

The exit code says how a run ended: 0 when everything passed, 1 when there are failures or errors in the tests, 2 when the CLI could not do what was asked (configuration, suite syntax or compile error).

## Console or `results.json`

Every run that gets as far as reading its results writes the whole run as JSON to `build/results.json`, and `--json` writes the same model to standard output. The question is which of them an agent in the loop should read.

**The skill reads the exit code first, then the console, and does not read `build/results.json`.** The console is shorter, and loses nothing the loop needs. For the `TSTBATCH` suite with `--coverage` (13 test cases), the console was about 6 KB and the JSON about 45 KB, measured with Cobalto 0.7.0 and GnuCOBOL 3.2 on macOS, on the example project. The JSON has the coverage of every program in `sources`, field by field. The console does not cut expected or actual values, and `-v` adds the output of each case and the reason a case is internal.

With Cobalto 0.7.0 the JSON also fell short after an error, which no longer holds from 0.8.0:

- **The location of a compile error.** A test case with a compile error prints `CBLT-E201: compile error in tests/LOANBTCH.cblt:67 (generated at build/TSTBATCH.cbl:172): 'FROBNICATED' is not defined`, followed by `CBLT-E202: the build failed (exit 1)`. With 0.7.0, `--json` carried only the last one, with no file or line. From 0.8.0 the error object of `CBLT-E202` lists each compile error in `details`, with `file`, `line`, `generated` and `message`, so the JSON has the location too; when the profile's `error_regex` matches none of the compiler's messages, it carries the compiler's `output` instead. A syntax error in the suite, `CBLT-E200`, keeps its file and line in the message.
- **A `results.json` left by an earlier run.** With 0.7.0, a run that stopped before reading results wrote none of the reports in `build/`, so the `results.json` left there belonged to the last run that got that far, and it could say `"ok": true`. From 0.8.0 the run writes its error there, with `"ok": false` and no suites, unless `cblt.json` cannot be read and the CLI cannot tell which folder to write to. Either way, the exit code is what says whether the suites ran.

The console is not a contract, and its wording can change between versions. That matters to a program that parses it, not to an agent that reads it.

### When to use the JSON

The JSON is for when the agent computes over results instead of reading them: comparing two runs, counting for a report, or a script it writes for the project. Take it from the standard output of the same run, not from `build/results.json`. Redirected to a file, standard output holds either the model of that run or, with exit code 2, the error object; the console still arrives on standard error:

```bash
cobalto test --json > /tmp/cobalto-gnucobol.json
```

```bash
cobalto test --profile gnucobol-ibm --json > /tmp/cobalto-ibm.json
```

This script lists the test cases whose status changed between the two runs, including the ones that are in only one of them. It stops on an error object, on a run that did not run the suites (`--no-run` or `--generate-only`) and on a `schema` newer than the one it was written for, and it reports the suites that aborted or never started, whose test cases a comparison would otherwise miss:

```python
import json
import sys


def statuses(path):
    with open(path, encoding="utf-8") as fh:
        run = json.load(fh)
    if run.get("schema", 0) > 1:
        sys.exit(f"{path}: schema {run['schema']} is newer than this script knows")
    if "error" in run:
        sys.exit(f"{path}: {run['error']['code']}: {run['error']['message']}")
    if run.get("ran") is False:
        sys.exit(f"{path}: the suites were not run")
    for suite in run["suites"]:
        if not suite["ended"] or suite["unlogged_failures"]:
            print(f"{path}: suite {suite['id']} did not report all its results")
    if run["missing_suites"]:
        print(f"{path}: {run['missing_suites']} suite(s) never started")
    return {(s["id"], c["name"]): c["status"] for s in run["suites"] for c in s["cases"]}


before, after = statuses(sys.argv[1]), statuses(sys.argv[2])
for suite, case in sorted(before.keys() | after.keys()):
    old, new = before.get((suite, case), "absent"), after.get((suite, case), "absent")
    if old != new:
        print(f"{suite}  {case}: {old} -> {new}")
```

On the example project it prints the five test cases that fail only with the IBM dialect:

```text
TSTBATCH  interface: master file goes in, transactions come out: passed -> failed
TSTBATCH  two active loans with the real LOANCALC: passed -> failed
TSTCLOSE  the batch counter wraps to zero after 9999: passed -> failed
TSTCLOSE  the control record is 11 bytes long: passed -> failed
TSTLOAN  installment for 100,000 at 36% a year over 12 months: passed -> failed
```

## Outputs an agent can rely on

These are the outputs Cobalto treats as contracts. [CONTRIBUTING.md](../CONTRIBUTING.md#what-a-change-has-to-respect) and the [design document](design.md#9-one-model-of-a-run) set the rules for them, and the [reference](reference.md#output) describes their fields.

| Output | What it holds |
|---|---|
| `cobalto test --json`, `cobalto report --json` | The model of the run: `profile`, `ok`, `totals`, the suites with their test cases (`status` is `passed`, `failed` or `skipped`, plus `kind`, `reasons`, the asserts with `expected` and `actual`, and `output`), `warnings` and, with `--coverage`, `coverage` by program and paragraph, with the lines and branches not executed. A suite that aborted has `ended` false, the suites that never started are counted in `missing_suites`, and both count in `totals.errors`: an aborted suite is an error of the suite, not a status of its test cases. With `--no-run` or `--generate-only`, `test --json` writes `{"profile": ..., "ran": false, "suites": [...]}` instead, with the ids of the suites |
| `build/results.json` | The same model, written by every run that gets as far as reading its results, and by a run that stops with exit code 2 once `cblt.json` is read, with `ok` false, no suites and the `error`. A run with `--no-run` or `--generate-only` that ends without an error does not rewrite it |
| `cobalto parse FILE --json` | What the parser understands of each program, and the files it could not parse |
| `cobalto list --json` | The suites and their test cases as the CLI reads them, without compiling anything, and the suite files with a syntax error |
| `cobalto profiles --json` | The default profile, and every profile with its name, kind and description |
| A fatal error with `--json` | `{"error": {"code": "CBLT-Ennn", "message": "..."}}`, with exit code 2. From `test` and `report`, once `cblt.json` is read, it comes inside the model of the run, with `ok` false and no suites, the same document as `build/results.json`. After a build failure, the error object also has `details`, each compile error with its `file` and `line`, or `output`, the compiler's output |
| `build/junit.xml` | One JUnit test case per `TESTCASE`, with the properties `cobalto.kind` and, if it failed, `cobalto.expected` and `cobalto.actual` of its first failed assert |
| The other JSON files in `build/` | The coverage map, the line map and the data layout of `cobalto debug`, and the manifest of `--generate-only`. They exist for the VS Code extension and for `cobalto report`; an agent rarely needs them |
| Exit codes | 0 everything passed, 1 failures or errors in the tests, 2 the CLI could not do what was asked |
| Message codes | `CBLT-Ennn` for errors and `CBLT-Wnnn` for warnings, from one catalog that the reference lists. A code keeps its meaning |

Some outputs are not contracts. The console is written for people. The COBOL that Cobalto generates in `build/` is worth opening at the line a `generated at` message gives, but its shape changes between versions. The prompts and answers of `cobalto suggest` in `build/ai/` are a record for people to audit.

### How `schema` changes

- Every JSON document the CLI writes, on standard output or in `build/`, carries `schema`, the version of the format, and `cobalto`, the version of the CLI that wrote it. Files written before Cobalto 0.7.0 have no `schema`.
- There is one `schema` number for all of them, and it is 1 today.
- Adding a field does not change `schema`. Changing the meaning of a field, renaming it or removing it raises `schema`, and [CHANGELOG.md](../CHANGELOG.md) lists the change.
- A reader should ignore the fields it does not know, and refuse a document whose `schema` is newer than the one it was written for instead of guessing, as the script above and the VS Code extension do.

No version of Cobalto has been tagged yet, and until 1.0 the formats can still change, as the [roadmap](../README.md#roadmap) says. The rule above is what keeps that safe for a reader: a format that changes in a way that breaks a reader comes with a new `schema`, so the reader finds out instead of misreading it.

## `cobalto suggest`

`cobalto suggest --program PROGRAM` runs a loop like the skill's, with a model of its own. It sends the model the source of the program with its copybooks, the summary of the parser and the existing suite, runs each suite the model proposes with coverage, sends back what Cobalto reported, and keeps the best round as a draft in `tests/PROGRAM.ai.cblt`. It reads `build/results.json` between rounds, and deletes the file before each round so that a round that does not compile is never read as the one before it. The [reference](reference.md#ai-assisted-test-generation) describes its backends and options.

Inside an agent session `suggest` is not needed: the agent is already the model, and `cobalto test` is the oracle. `suggest` is for where there is no agent session to drive the loop: a person without an agent, a batch of programs, or a job that drafts suites unattended. With `--mode interface` it asks only for interface cases. With `--fill-expected` it changes each failed equality assert to expect the value the program produced, with a `REVIEW` comment that keeps the original, so an interface suite that records what a program does today takes a single round. With `--dry-run` it writes the prompt to `build/ai/` without sending it, which shows the context Cobalto gives a model.

The result is a draft for a person to review either way, whether a coding agent wrote it or `suggest` did.

## Source code and model providers

A coding agent sends what it reads to its model provider, as `suggest` does. Whether a program's source may leave the machine is for the owner of the code to decide, not for the agent or for Cobalto. Suites use made-up data consistent with the `PIC` clauses, never production or personal data.
