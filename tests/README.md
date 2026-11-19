# Cobalto's own tests

These are the tests of the tool itself. The suites that show how to use Cobalto are in [`examples/`](../examples/).

```bash
python3 tests/run.py
```

runs every layer of the CLI and ends with 0 when all of them pass; `python3 tests/run.py --extension` adds the VS Code extension, and `python3 tests/run.py --list` names the layers. None of them needs Cobalto installed: they use the package in `src/`.

| Layer | Command | What it covers | Needs |
|---|---|---|---|
| `unit` | `python3 -m unittest discover -s tests/unit` | The modules of the CLI one by one: the COBOL parser, coverage, the DSL, the configuration | Python |
| `cli` | `python3 tests/cli/selftest.py` | The CLI end to end on a minimal project per scenario: one scenario per `CBLT-Exxx` / `CBLT-Wxxx` message, the happy paths and the structured outputs | GnuCOBOL |
| `interface` | `python3 tests/interface/selftest.py` | Interface tests: `RUN`, the rewrite of `STOP RUN` / `GOBACK` / `EXIT PROGRAM`, the classification of test cases | GnuCOBOL |
| `examples` | `python3 tests/examples/selftest.py` | The example project with each profile that works on one machine, compared with `tests/examples/expected.json` | GnuCOBOL |
| `dialects` | `python3 tests/dialects/selftest.py` | Everything Cobalto contributes to a build, checked with `cobc -fsyntax-only` in the eight strict dialects of GnuCOBOL | GnuCOBOL |

The extension has its own: `npm run lint` and `npm test` in [`vscode-cobalto/`](../vscode-cobalto/), plus the checks against a debugger and inside VS Code that its [DEVELOPMENT.md](../vscode-cobalto/DEVELOPMENT.md) describes.

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs these layers on every push and pull request: the CLI ones on Linux and macOS, and the lint, unit tests and packaging of the extension. [`.github/workflows/release.yml`](../.github/workflows/release.yml) builds the package, installs the wheel in a clean environment and runs the example regression with it, on the pull requests that touch the packaging and before every release.

## The examples are a demo, and they fail on purpose

Two test cases of the example project fail by design: one shows what a failure looks like in the report and the other finds a defect seeded in a program. `cobalto test` therefore ends with exit code 1 in `examples/`, the same code a real regression would give.

`tests/examples/selftest.py` is what a build runs instead. It runs the examples in a temporary copy and compares the outcome with `expected.json`: the exit code, the totals, every test case that does not pass with its status, and the coverage totals, for each profile. It ends with 0 when the examples behave as recorded, failures included.

When the examples change on purpose, record the new outcome and read the diff before committing it:

```bash
python3 tests/examples/selftest.py --update
```
