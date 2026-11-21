# Changelog

Changes to the Cobalto CLI: the commands, the suite language, the COBOL core, the built-in profiles and the files it writes. The VS Code extension has its own [changelog](vscode-cobalto/CHANGELOG.md).

Until 1.0, a minor version can change the CLI, the suite language and the file formats. Every such change is listed here. Each section is headed `## X.Y.Z - YYYY-MM-DD`, or `## X.Y.Z - Unreleased` while it is being prepared; the release workflow refuses to publish a version whose section has no date.

## 0.8.0 - Unreleased

First release published on PyPI: `pip install cobalto` installs the `cobalto` command and its short alias `cblt`.

- Test suites written in a DSL that reads like COBOL and expands to standard COBOL 85. External suites call the program under test through its interface; in-program suites run inside a copy of it and can `PERFORM` any paragraph, read and set its fields, and run the whole flow with `RUN` or `RUN USING`.
- Mocks per test case for paragraphs, `CALL`, files, `EXEC SQL` and the clock, and `VERIFY` to count how many times each of them happened. The program's `STOP RUN`, `GOBACK` and `EXIT PROGRAM` end the test case, not the process.
- Each test case classified as an interface case or an internal case.
- Portable coverage by statement, branch, condition and paragraph, without gcov or a special runtime, with reports in LCOV, Cobertura XML and SonarQube's generic format. Test results in JUnit and in SonarQube's generic execution format.
- Built-in profiles for GnuCOBOL (plain, with gcov coverage, for debugging, and with the IBM and Micro Focus dialects), a local simulator of a remote host, VSI COBOL on OpenVMS and a Micro Focus template. The profiles table of the [reference](docs/reference.md#profiles) says how far each one has been verified. A project adds or adjusts profiles in its `cblt.json`.
- Remote profiles that build and run on another machine over ssh, and `--generate-only` with `cobalto report` for a host without ssh.
- Structured outputs for programs and agents: `--json` in `test`, `report`, `parse`, `list` and `profiles`, and `build/results.json`, all with `schema` 1.
- A run of `test` or `report` that stops with exit code 2 writes the error to `build/results.json`, `build/junit.xml` and `build/sonar-tests.xml`, with `"ok": false` and an `error` object in the JSON, instead of leaving the reports of an earlier run for a CI step or a script to read as this run's ([#20](https://github.com/abstracta/cobalto/issues/20)). With `--json`, standard output carries the same document. The coverage reports keep the last run with `--coverage`.
- `cobalto debug` prepares a suite to be debugged in VS Code with COBOL names.
- `cobalto suggest` asks an AI model for a draft suite, compiles it, runs it with coverage and feeds the results back in rounds, for a person to review.
- Python 3.9 or later, standard library only.
