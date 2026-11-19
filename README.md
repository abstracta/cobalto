<p align="center"><img src="docs/logo/cobalto-logo.svg" alt="Cobalto" width="360"></p>

# Cobalto

**Unit testing for COBOL that runs wherever your COBOL runs.**

Cobalto lets a team test, debug and understand its COBOL with the compiler it already has: no new licenses and no vendor lock-in. Tests are written in a small language that reads like COBOL and run from the command line or from VS Code, where a suite can also be debugged with COBOL names. Results come out in JUnit, LCOV, Cobertura XML and SonarQube's generic format, so they fit into an existing CI pipeline, and an AI model can propose a first draft of a suite for a person to review.

It is an open source project by [Abstracta](https://abstracta.us), released under Apache-2.0.

> **Pre-release.** This repository holds a working prototype ahead of its first tagged version. Interfaces and file layout will change before `v0.1.0`.

## Why

COBOL systems run critical processes in banks, insurers, public agencies and utilities, and the teams that maintain them change business logic with no tests to notice when something breaks. The unit testing tools that exist for COBOL are tied to one compiler, one platform or one license, or are no longer maintained. For many teams the alternative is not another tool but no unit tests at all.

Cobalto gives a program a suite that does not depend on where it is compiled: the part that runs inside the COBOL is standard COBOL 85, and everything specific to an environment lives in a profile. With GnuCOBOL you can see what that is worth on a single machine: the same suite compiled with the IBM or the Micro Focus dialect catches behavior that changes with the compiler, such as rounding, binary field sizes and truncation.

Cobalto is not a migration tool: it does not translate, convert or move code. A migration is one of the changes a suite protects, along with everyday maintenance, a refactoring and a change of compiler or dialect. It is also the one where a portable suite pays off most, because the same tests run before and after.

## How it works

- **Portable core.** The assertions, the test context and the driver that runs the suites are plain COBOL 85, fixed format, with no extensions.
- **One profile per environment.** How to compile, link and run, where the results file goes, and whether the build happens on another machine over ssh, all live in a declarative profile. Adding a compiler means writing a profile, not touching the core.
- **A CLI with no dependencies.** Python 3, standard library only. It discovers the suites, generates the test COBOL, compiles, runs, reads the results and writes the console output and the reports. It works on any machine with Python, with or without internet access.
- **A VS Code extension.** Test Explorer, coverage in the gutter and debugging with COBOL names (breakpoints in the suite, step by statement, conditions written in COBOL, changing values) on top of the same project and the same CLI.

## What you can test

**Whole programs.** A suite describes test cases that call the program under test through its interface (`CALL ... USING`) and check the results with readable assertions:

```cobol
       TESTSUITE TSTDISC 'Discounts by amount'

       TESTCASE 'premium amount gets 20%'
           MOVE 2000 TO WS-AMOUNT
           CALL "DISCOUNT" USING WS-AMOUNT WS-RESULT WS-CATEGORY
           EXPECT WS-RESULT TO BE NUMERIC 1600
           EXPECT WS-CATEGORY TO BE 'PREMIUM'
```

**Single paragraphs of a program, without refactoring it.** In in-program mode, Cobalto injects the suite into a copy of the program. Test cases can `PERFORM` any paragraph, read and set any `WORKING-STORAGE` field, and replace, one test case at a time, calls to other programs, file access, embedded SQL and the system date. `RUN` executes the original flow from its entry point, with the program's `STOP RUN` ending the test case instead of the process:

```cobol
       TESTSUITE TSTINV 'Invoicing (in-program on INVOICE)'
       PROGRAM INVOICE

       TESTCASE 'full process with mocked files'
           MOCK FILE CUST-FILE
               ON READ
                   EVALUATE CBLT-READ-COUNT
                       WHEN 1
                           MOVE "C001ACME      000200000" TO CUST-REC
                       WHEN OTHER
                           SET CBLT-AT-END TO TRUE
                   END-EVALUATE
           END-MOCK
           PERFORM 2000-PROCESS
           EXPECT WS-TOTAL TO BE NUMERIC 1600
           VERIFY CALL 'DISCOUNT' HAPPENED ONCE
           VERIFY PARAGRAPH 3000-END NEVER HAPPENED
```

A mock applies only to the test case that declares it. Every other test case runs the original code.

**Interface and internal cases.** The report marks each test case as an *interface* case, which only looks at what goes into the program and what comes out, or an *internal* case, which runs a paragraph or looks at the program's own fields. Interface cases are the ones that still make sense after the program is rewritten or translated.

**Coverage with any compiler.** With `--coverage`, the CLI instruments a copy of each program under test and measures statements, the branches of `IF`, `EVALUATE` and `SEARCH`, compound conditions by operand, and paragraphs, without gcov or a special runtime. The result goes to the console and to LCOV, Cobertura XML and SonarQube's generic format.

**Results as data.** `cobalto test --json` writes the whole run as JSON: totals, every test case, the expected and actual value of each assert, and coverage. The same model is saved to `build/results.json`, so a script or an AI agent never has to read console text.

**A draft suite proposed by AI.** `cobalto suggest` asks a model for a suite for a program, compiles it, runs it with coverage and feeds back what failed or was left uncovered, in rounds. The result is a draft of characterization tests for a person to review, and everything sent to the provider is kept in `build/ai/`.

## Status

What exists today, and how far each part is verified:

| Capability | Verification |
|---|---|
| COBOL 85 core (assertions, context, driver) | `cobc -fsyntax-only` with no errors or warnings in the eight strict dialects of GnuCOBOL. Compiled, linked and run with VSI COBOL on OpenVMS |
| External and in-program suites, with mocks per test case (paragraphs, `CALL`, files, `EXEC SQL`, clock) | GnuCOBOL 3.2 on the seven example programs: 105 test cases, 415 asserts, 2 intentional failures, 6 skipped. 46 interface cases and 58 internal ones |
| Portable coverage by statement, branch, condition and paragraph | GnuCOBOL 3.2. The Sonar report was checked with SonarQube Community; Sonar's COBOL analyzer (Enterprise edition) was not tried |
| The same suite across dialects: profiles `gnucobol-ibm` and `gnucobol-mf` | With `-std=ibm` five more test cases fail and with `-std=mf` two more, because of rounding and of the size and truncation of binary fields |
| VS Code extension | macOS with GnuCOBOL 3.2, lldb-dap from Xcode and VS Code 1.140. On Linux, the debug adapter was verified over the protocol in a container |
| AI-assisted drafts (`cobalto suggest`) | Claude on three of the example programs: 36 test cases proposed in two rounds, all passing |
| Remote profiles (build and run on another machine) | The ssh mechanics are verified with a local simulator, where two test cases that use an indexed file still fail. For hosts without ssh, `cobalto report` reads a results file and a screen capture brought back by hand |

| Compiler | Status |
|---|---|
| GnuCOBOL 3.x on Linux and macOS | Verified |
| VSI COBOL V3.1-0007 on OpenVMS V8.4-2L3 | Verified with the generated DCL scripts run by hand and the results read by `cobalto report`. The labels of the build script were renamed since. Automation over ssh is not verified |
| Micro Focus | Profile template only. Not verified |
| IBM Enterprise COBOL | No profile yet. Not verified |

Running on any compiler that follows the standard is the design goal. The table above is what has been checked.

## Try it

You need Python 3.9 or later and GnuCOBOL 3.x. Install the CLI from a clone of this repository; it adds the `cobalto` command and its short alias `cblt`:

```bash
python3 -m pip install .
```

Then run the example project:

```bash
cd examples
```

```bash
cobalto test --coverage
```

```bash
cobalto test --profile gnucobol-ibm
```

```bash
cobalto test --json
```

The example project includes two test cases that fail on purpose, so these commands end with exit code 1.

To start a project of your own:

```bash
cobalto init /path/to/my/project
```

To write a first suite step by step, see the [reference](docs/reference.md). The VS Code extension is installed from its `.vsix` for now; see [its README](vscode-cobalto/README.md).

## Where things are

| Path | What it is |
|---|---|
| [src/cobalto/](src/cobalto/) | The tool, as a Python package: the CLI, the COBOL core (`lib/`) and the built-in profiles (`profiles/`) |
| [examples/](examples/) | The example project: seven programs (`src/`), their suites (`tests/`) and its `cblt.json` |
| [docs/reference.md](docs/reference.md) | The reference for the DSL, the project file, profiles, coverage, debugging and AI-assisted drafts |
| [docs/design.md](docs/design.md) | How Cobalto is built and why: the portable core, the results protocol, in-program mode, coverage, and the limits of each |
| [docs/adding-a-compiler.md](docs/adding-a-compiler.md) | How to try Cobalto with another compiler and contribute its profile |
| [vscode-cobalto/](vscode-cobalto/) | The VS Code extension |
| [tests/](tests/) | Cobalto's own tests: `python3 tests/run.py` runs them all; its [README](tests/README.md) describes each layer |
| [.claude/skills/cobalto/](.claude/skills/cobalto/) | A Claude Code skill for writing and running Cobalto suites |
| [docs/logo/](docs/logo/) | Logo |

## Contributing

The most useful contribution is running Cobalto on a compiler it has not been verified with and reporting what happened, whether it worked or not: [Adding a compiler](docs/adding-a-compiler.md) explains how, and it needs no change to the code. For problems, fixes and everything else, see [CONTRIBUTING.md](CONTRIBUTING.md).

## About the name

Cobalto is COBOL plus element 27, a stable metal that resists heat and corrosion. **CBLT** is its technical abbreviation, used where standard COBOL needs short names: the `PROGRAM-ID`s of the library (`CBLTEQ`), the context copybook (`CBLTCTX`), the message codes (`CBLT-E200`), the suite extension (`.cblt`) and the CLI.

## License

Apache-2.0. See [LICENSE](LICENSE). Cobalto took ideas from earlier COBOL unit testing projects, but includes no code from them: the parser, the rewriter, the COBOL library, the CLI and the extension were written from scratch.
