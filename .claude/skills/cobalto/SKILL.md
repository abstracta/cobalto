---
name: cobalto
description: Write, run and fix unit tests for COBOL programs with Cobalto (CLI `cobalto` or `cblt`, `.cblt` suites). Use this skill whenever the task touches COBOL and tests, even if Cobalto is not named, for example to write or extend a suite, to characterize a program before refactoring it, migrating it or translating it to another language, to check that a change or a change of dialect did not alter its behavior, to raise coverage, or to diagnose a `CBLT-Exxx` message. Also use it when the project has a `cblt.json` or `.cblt` files.
---

# Cobalto: unit tests for COBOL

Cobalto expands a DSL (`.cblt` files) to standard COBOL 85, compiles it with the project's compiler, runs the test cases and returns results that can be checked: PASS or FAIL per case, expected and actual per assertion, and coverage by statement, branch and paragraph.

The division of work is this: the agent reads the program and proposes the cases; Cobalto says what really happens when they run. A suite that was not run is evidence of nothing, so every claim about the behavior of a program must come from a run, not from reading the source.

## Before writing

1. Locate the project: the folder that contains `cblt.json`. Every command runs from there. `cblt.json` declares where the sources are (`sources`), the suites (`tests`), the copybooks (`copybooks`) and the build profile.
2. Locate the CLI: `cobalto` (or `cblt`, the same command under a shorter name) on the `PATH` or in the project's virtual environment (`.venv/bin/cobalto`). If it is not installed, install it from a clone of Cobalto into a virtual environment (`python3 -m venv .venv`, then `.venv/bin/python3 -m pip install <path to the clone>`); Homebrew and recent Debian and Ubuntu do not let `pip` modify the system Python. From here on it is written `cobalto`.
3. If there is no `cblt.json`, create the project with `cobalto init <folder>` and review `sources` and `copybooks`.
4. Ask the parser how it reads the program: `cobalto parse src/PROGRAM.cbl`. It shows the paragraphs with their lines, the files, the `CALL`, file I/O, `EXEC` (SQL) and `ACCEPT` (clock) statements with their lines, the `WORKING-STORAGE` and `LINKAGE` items and the `PROCEDURE DIVISION USING` list. The names the suite uses must match that output, not a guess.
5. Read the program's existing suite, if there is one, to cover what is missing instead of repeating cases. If the `tests/` folder does not exist, create it.

## Choosing the kind of case

Cobalto classifies each case and shows it in the report.

- **Interface case:** the case enters through `CALL` (suite without `PROGRAM`) or through `RUN` / `RUN USING` (suite with `PROGRAM`), mocks everything external and checks only what comes out: parameters, records written, calls made, the end of the program. These cases stay valid when the program is rewritten inside or translated to another language.
- **Internal case:** the case executes a single paragraph with `PERFORM`, mocks or counts paragraphs, or reads and sets fields of the program's `WORKING-STORAGE`. They pinpoint a defect and support a refactoring for as long as the COBOL stays alive, but they do not survive a rewrite.

Rule of thumb: if the request is to protect a rewrite, a translation or a migration, write interface cases. If it is to understand or fix a specific paragraph, internal cases. When in doubt, interface cases for the whole flow and internal cases only where a rule needs to be isolated.

## The cycle

1. Write the suite in `tests/NAME.cblt` with the DSL (full reference in `references/dsl.md`; read it before writing the first suite of the session).
2. Run only that suite with coverage:

   ```bash
   cobalto test --coverage --filter TSTNAME
   ```

   Exit codes: 0 everything passes, 1 there are failures or errors, 2 configuration, DSL or compile error.
3. Look at the exit code first, then read the console output and fix according to what it says (table below). With exit code 2 there are no results: the cause is in the `CBLT-E` lines of the output. `build/results.json` and `build/junit.xml` hold only that error (with Cobalto 0.7.0, or when `cblt.json` cannot be read, they are from an earlier run).
4. Repeat until the suite compiles, has no unexplained failures and the program's coverage leaves no business branch unexecuted. With `-v` the output shows each case's `DISPLAY` lines and the reason for its classification.
5. At the end run `cobalto test` without a filter, to confirm that the new suite did not break the others.

| What the output shows | What to do |
|---|---|
| `CBLT-E200` (DSL syntax error) | Fix the indicated line of the `.cblt` |
| `CBLT-E201` (compile error) | Fix the indicated line of the `.cblt` or of the original program. If that line has nothing wrong, the error is in the generated COBOL: open `build/<SUITE>.cbl` at the line the message gives as `generated at` |
| `CBLT-E401`, `E402`, `E403` (paragraph, `CALL` or file that does not exist) | The name does not match the program; check with `cobalto parse` |
| `FAIL` with `expected [...] actual [...]` | Decide between a wrongly deduced value and a defect in the program (see "When a case fails") |
| `the case did not finish: the program fell off the end` | A `GO TO` left the executed paragraph; use `PERFORM A THRU B` or `RUN` |
| `NOT EXECUTED`, `statements not executed on lines ...` or `branches not executed: ...` in the coverage table | Add the case that reaches that branch |
| Case marked `· internal` when interface cases were requested | `-v` shows the reason (`internal because of: ...`); remove the `PERFORM` of an inner paragraph or the `WORKING-STORAGE` field |

## When a case fails

A `FAIL` has two readings, and choosing the wrong one is the most expensive mistake in this work.

- **The expected value was wrongly deduced.** Reread the code with the actual value in view. If the program does that by design (truncation without `ROUNDED`, a `PIC` smaller than the result, a branch that had gone unnoticed), fix the `EXPECT`.
- **The program has a defect, or the rule is not clear.** In characterization tests the `EXPECT` still keeps the value the program produces, because the suite documents the current behavior. Put a `REVIEW` comment above it that says what was expected and why it looks like a defect, and include it in the final report. The decision to keep the defect or fix it belongs to a person, not to the agent.

Do not modify the program under test to make a case pass, unless the request is to fix that program. Do not delete a failing case or loosen an assertion until it passes either: that hides exactly what the suite exists to show.

## Rules that prevent most errors

- **Fixed format.** DSL keywords go in column 8 and the COBOL of the cases from column 12. No line goes past column 72. Comments carry an asterisk in column 7. The compiler rejects or silently ignores whatever falls outside those columns.
- **No final period** on the statements inside `TESTCASE`, `BEFORE-EACH`, `AFTER-EACH` and `MOCK`: the code is injected into structures that a period would close too early.
- **COBOL 85 only** in the suite: no intrinsic functions and no dialect syntax, because the same suite has to compile with every compiler the program is built with, the current one and the next.
- **`EXPECT` according to the type of the field.** On a numeric field (`PIC 9`, `V`, `COMP`), use `NUMERIC`, `GREATER THAN`, `LESS THAN`, `BETWEEN` or `ZEROS`. The forms with `'text'`, `NOT TO BE`, `CONTAIN` and `SPACES` are for alphanumeric fields.
- **The main flow is executed with `RUN` or `RUN USING`**, not with a `PERFORM` of the main paragraph. In the test copy, `STOP RUN`, `GOBACK` and `EXIT PROGRAM` end the case and not the process.
- **Mock everything external in every case that goes through it:** files, `CALL` to other programs, `EXEC SQL` and `ACCEPT FROM DATE/TIME`. A `MOCK` applies only to the `TESTCASE` that declares it, or to all of them if it is in `BEFORE-EACH`.
- **`T-` prefix** on the suite's own fields, without redeclaring fields of the program or using `CBLT-*` names.
- **State between cases.** In a suite with `PROGRAM`, the program's `WORKING-STORAGE` is not reset between cases: an end-of-file flag or a counter stays as the previous case left it. Initialize them in `BEFORE-EACH`, which does not count for the classification, so the cases remain interface cases.
- **`RETURN-CODE` is copied as soon as `RUN` returns** to a `T-*` field and is checked on that field. Every `EXPECT` and every `VERIFY` calls the Cobalto library, and that call leaves `RETURN-CODE` at zero.
- **Subscripts without a space in `EXPECT`:** `EXPECT T-ID(1) TO BE 'x'`. With the usual COBOL space (`T-ID (1)`) the DSL does not recognize the line.
- **Called programs.** In an interface case the `CALL` is mocked and what it received is checked; the rule of the called program is protected by its own suite. If it has none, say so in the report.
- **One case per behavior:** each branch of `IF` and `EVALUATE`, each `AT END` and `INVALID KEY`, the limits of each `PIC` (zero, maximum, empty).
- **Made-up test data, consistent with the `PIC`s.** Do not copy production data or personal data into a suite.

## What to deliver

When finished, report with the output of the last run in view:

- Cases, asserts, failures and skipped (the `Cases: N  Asserts: N  Failures: N  Skipped: N  Errors: N` line), and how many cases are interface cases and how many internal (the `Interface cases: N  internal: N` line).
- Coverage of the program (paragraphs, statements and branches), what was left unexecuted and why.
- Each `REVIEW`: what the program does, what was expected and which decision is left for a person.
- What could not be tested (for example, SQL without a precompiler or a paragraph with `NEXT SENTENCE`).

## Other useful commands

- `cobalto test --profile gnucobol-ibm` (or `gnucobol-mf`): the same suite with another dialect. The cases that fail only there are differences in behavior between compilers, which is what a change of compiler or a migration needs to see. `cobalto profiles` lists the profiles.
- `cobalto suggest --program X --dry-run`: builds the prompt that AI-assisted generation would send, in `build/ai/`, without sending it. Inside an agent session `suggest` is not needed: the agent writes the suite and uses `cobalto test` as the oracle.
- Results as data: `cobalto test --json` writes the model of the run to standard output (totals, cases, expected and actual of each assert, coverage with `--coverage`) and sends the console to standard error. Use it when you need to compute over the results rather than read them, for example to compare the same suites under two profiles: redirect standard output to a file (`cobalto test --json > /tmp/run.json`) and read that, not `build/results.json`, which the next run replaces. With exit code 2 the JSON has `"ok": false`, no suites and an `error` object; for a compile error, its `details` give the `file`, `line` and `message` of each one, the same as the `CBLT-E201` lines on standard error.
- Results for other tools: `build/junit.xml` and `build/sonar-tests.xml` on every run; with `--coverage`, also `build/lcov.info`, `build/coverage.xml` and `build/sonar-coverage.xml`.

## Third-party code

If the source belongs to a third party, the owner of the code decides which parts may go out to an AI provider. Cobalto works offline; when in doubt, ask before reading or sending sources outside the project.
