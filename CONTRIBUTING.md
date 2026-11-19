# Contributing to Cobalto

Thank you for looking into this. The contributions that help most are, in this order:

1. **Running Cobalto on a compiler it has not been verified with**, and telling us what happened. See [Adding a compiler](docs/adding-a-compiler.md). You do not need to change any code for this.
2. **Reporting a COBOL construct that Cobalto's parser or rewriter gets wrong.** Real programs are where these show up.
3. **Fixes and improvements** to the CLI, the VS Code extension and the documentation.

## Reporting a problem

Open an issue with the "Bug report" template. What makes a report actionable:

- The output of `cobalto --version` and the name and version of the COBOL compiler.
- The command you ran and what it printed. `-v` shows every command Cobalto executed.
- The smallest program and suite that show the problem.
- If a `MOCK` does not find its target, or a statement is rewritten wrongly, the output of `cobalto parse FILE` for that program: it shows what the parser understood.

**Do not post code that is not yours to share.** Most COBOL belongs to someone's production system. Reduce the problem to a synthetic program with made-up names and data before posting it. If it only happens on the real program, describe the construct (for example, "a `READ` with `INVALID KEY` inside an `IF` closed by a period") and we will build the case from that. The same goes for build output, host names and paths of a private environment.

## Adding a compiler

A compiler is added with a profile, a JSON object that says how to compile and run there. [Adding a compiler](docs/adding-a-compiler.md) goes through it step by step, from a first try in your own project to a built-in profile, and says what evidence a pull request needs.

## Working on Cobalto

You need Python 3.9 or later and GnuCOBOL 3.x (`brew install gnucobol` on macOS, the `gnucobol3` package on Debian and Ubuntu). From a clone:

```bash
python3 -m pip install -e .
python3 tests/run.py
```

The first command installs `cobalto` from the working copy. The second runs every layer of the CLI's tests in under a minute, and none of them needs Cobalto installed. [tests/README.md](tests/README.md) describes each layer and how to run one alone.

For the VS Code extension you also need Node.js (CI uses version 22):

```bash
cd vscode-cobalto
npm ci
npm run lint
npm test
```

Its [README](vscode-cobalto/README.md) describes the checks that need a debugger or a running VS Code.

[docs/design.md](docs/design.md) explains how Cobalto is built and why. Reading it first will save you time on anything larger than a small fix.

## What a change has to respect

These are the constraints that keep Cobalto portable. Each one has a reason in the design document.

- **The CLI uses only the Python standard library**, and runs on Python 3.9. It has to work on a machine with nothing but Python.
- **The COBOL core is standard COBOL 85 in fixed format.** `tests/dialects/` checks it, and everything Cobalto generates, against eight dialect configurations of GnuCOBOL. A change to the core also has to be verified again on every compiler listed as verified, which nobody can do alone, so open an issue to discuss it before writing it.
- **Generated COBOL is plain COBOL 85**, in fixed format, with no line past column 72.
- **Every message has a code.** A new error or warning goes in the catalog in `src/cobalto/messages.py`, gets a scenario in `tests/cli/selftest.py`, and is listed in the reference.
- **Outputs that other programs read are contracts**: the `--json` outputs, `results.json`, JUnit properties and the files in `build/`. Adding a field is fine. Changing or removing one means a new `schema` version.
- **The documentation says only what has been verified**, with the version of the compiler and the platform. "Should work" is written as "not verified".
- **Never a silent pass.** When Cobalto cannot check something faithfully, it reports an error or a warning.
- **Everything is in English**: code, comments, messages, documentation and commits.

A change comes with its tests: a unit test for the module it touches, a scenario if it changes what the CLI prints or returns, and unit tests for the modules of the extension that do not depend on VS Code. If it changes what the example project produces on purpose, record the new outcome with `python3 tests/examples/selftest.py --update` and read the diff before committing it.

## Pull requests

- One topic per pull request.
- Say what you verified and how: which layers you ran, with which compiler and version. If something could not be verified, say that too.
- CI runs the test layers on Linux and macOS, and the lint, unit tests and packaging of the extension. It has to pass.

## License

Cobalto is licensed under [Apache-2.0](LICENSE). As section 5 of the license states, contributions you submit are under the same license.
