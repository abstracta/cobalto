# AGENTS.md

Instructions for coding agents that work on Cobalto itself. To use Cobalto from an agent, to write and run test suites for COBOL programs, see [Using Cobalto from a coding agent](docs/coding-agents.md) instead.

[CONTRIBUTING.md](CONTRIBUTING.md) is the source for the rules below; this file picks out the ones an agent is most likely to break. [docs/design.md](docs/design.md) gives the reasons behind them, and is worth reading before any change larger than a small fix.

## Where things are

- [src/cobalto/](src/cobalto/): the CLI, a Python package. The module map is in the [reference](docs/reference.md#source-layout). It also holds the COBOL core (`lib/`) and the built-in profiles (`profiles/`).
- [vscode-cobalto/](vscode-cobalto/): the VS Code extension, in TypeScript. Its [DEVELOPMENT.md](vscode-cobalto/DEVELOPMENT.md) covers its build and checks.
- [tests/](tests/): Cobalto's own tests.
- [examples/](examples/): the example project, seven synthetic programs and their suites.
- [docs/](docs/): the reference, the design document and the guides.

## Setup

You need Python 3.9 or later and GnuCOBOL 3.x. From the root of the working copy:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

That installs the `cobalto` command, and its alias `cblt`, from the working copy. The tests do not need it: they import the package from `src/`.

## Tests

```bash
python3 tests/run.py
```

It runs every layer of the CLI's tests (`unit`, `cli`, `interface`, `examples` and `dialects`) and ends with 0 when all of them pass. Run it before you report a change as done.

- `python3 tests/run.py --extension` also runs the lint and the unit tests of the VS Code extension. It needs Node.js and `npm ci` run once in `vscode-cobalto/`. Run it whenever you touch `vscode-cobalto/`.
- `python3 tests/run.py unit cli` runs only those layers, and `--list` names them all. `python3 tests/cli/selftest.py E401 W305` runs only those scenarios.
- [tests/README.md](tests/README.md) says what each layer covers.

Two traps:

- `cobalto test` in `examples/` ends with exit code 1 on purpose: two test cases fail by design. That is not a regression. The check for the examples is `python3 tests/examples/selftest.py`, which compares their outcome with `tests/examples/expected.json`.
- `python3 tests/examples/selftest.py --update` rewrites `expected.json`. Run it only when a change to the outcome of the examples is intended, and read the diff before committing it. Never run it to make a failing layer pass.

## Rules a change has to respect

- **Standard library only, on Python 3.9.** No dependencies in `pyproject.toml`, no imports from outside the standard library, and no syntax newer than 3.9, such as `match` or `X | Y` type unions. CI runs the CLI's layers on Python 3.9 and 3.13, so a newer local Python does not catch a mistake here.
- **COBOL 85 in fixed format**, in the core (`src/cobalto/lib/`) and in everything the CLI generates: no extensions, no intrinsic functions, no line past column 72. `tests/dialects/` checks it in eight strict dialects of GnuCOBOL. Do not change the core without an issue that discusses it first: every compiler listed as verified would have to be verified again.
- **A code for every message.** A new error or warning goes in the catalog in `src/cobalto/messages.py`, gets a scenario in `tests/cli/selftest.py`, and is listed in the "Output" section of [docs/reference.md](docs/reference.md#output).
- **Outputs that other programs read are contracts, versioned with `schema`.** These are the `--json` outputs, `build/results.json`, the JUnit properties and the JSON files in `build/`, and the VS Code extension is one of their readers. Adding a field is fine. Changing or removing one means raising `SCHEMA` in `src/cobalto/messages.py`, updating `SUPPORTED_SCHEMA` in `vscode-cobalto/src/dap/schema.ts` when the extension reads the new format, and listing the change in [CHANGELOG.md](CHANGELOG.md).
- **Never a silent pass.** When Cobalto cannot check something faithfully, it reports an error or a warning. Do not make a check pass by skipping it, by catching and ignoring an exception, or by loosening a comparison.
- **The documentation says only what has been verified**, with the compiler, its version and the platform. Write "not verified" instead of "should work".
- **Everything is in English**: code, comments, messages, documentation and commits.
- **Synthetic data only.** Programs, suites and test fixtures use made-up names and data. Never add COBOL, output, host names or paths from a real system.

## What a change comes with

- A unit test in `tests/unit/` for each module it touches.
- A scenario in `tests/cli/selftest.py` if it changes what the CLI prints, writes or returns.
- Unit tests for the modules of the extension that do not depend on VS Code, if it touches `vscode-cobalto/`.
- An entry in [CHANGELOG.md](CHANGELOG.md) if it changes the CLI, the suite language, the COBOL core, the built-in profiles or the files the CLI writes.

When you report a change or open its pull request, say which test layers you ran, with which compiler and version, and what could not be verified.
