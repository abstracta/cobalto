---
name: Compiler report
about: Tell us how Cobalto behaved with a COBOL compiler, whether it worked or not
title: "Compiler report: <compiler> <version> on <platform>"
---

<!--
Thank you. A report is useful whether the compiler worked, needed changes or
could not work. The steps are in docs/adding-a-compiler.md.

Do not paste source code or build output that is not yours to share, and
leave out host names, user names and paths of a private environment.
-->

## Compiler and platform

- Compiler and exact version (its version banner):
- Operating system and version:
- Cobalto version (`cobalto --version`):
- Where the CLI ran: on the same machine / on another machine over ssh / on another machine, with the files carried by hand

## The core alone

Did `CBLTLIB.cbl` compile cleanly by hand? If not, the compiler's messages:

## The profile

```json

```

## Results on the example project

The totals line of `cobalto test --profile NAME --coverage`:

```

```

The reference is 105 test cases, 415 asserts, 2 intentional failures, 6 skipped, 0 errors.
Test cases that differ from it, and the reason for each if you know it:

## What was not tried

For example: coverage, in-program suites, the remote transport, the VS Code extension.

## Anything that needed a workaround
