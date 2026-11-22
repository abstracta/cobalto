# Changelog

## 0.1.3

- The installation steps install the Cobalto CLI from PyPI (`pip install cobalto`, published with CLI 0.8.0), in a virtual environment in the project folder, where the extension finds it by itself. They also say to keep `.venv/` and `build/` out of version control.
- The messages shown when the CLI cannot be run or does not list the suites say how to install it from PyPI.
- The search for projects skips `.venv` folders.

## 0.1.2

- The extension is also published on Open VSX, for editors built on VS Code that do not use the Visual Studio Marketplace; the README says so.
- More keywords and a banner color for the listing.

## 0.1.1

- The Marketplace page is written for people who use the extension; how it works inside and how it is verified moved to `DEVELOPMENT.md` in the repository.
- The installation steps create a virtual environment for the CLI.

## 0.1.0

First version.

- Test Explorer: the suites and their test cases as the Cobalto CLI lists them, run for the whole project or for one suite, failures with expected and actual as a diff.
- Coverage by statement, branch and paragraph, in the gutter and in the Test Coverage view.
- Debugging with COBOL names on top of `lldb-dap`: breakpoints in the `.cblt` and in the program under test, conditions written in COBOL, groups and `OCCURS` expanded, values changed from the variables panel, one step per COBOL statement.
- Choice of the compiler profile from the status bar.
- Syntax highlighting for `.cblt` files.
