# Cobalto: usage reference

Cobalto is Abstracta's unit testing tool for COBOL. This document is the technical reference for the CLI and the DSL; the general introduction is in the [main README](../README.md).

To start with a hands-on walkthrough, see "First suite in 15 minutes" below.

**CBLT** is the technical abbreviation of Cobalto: it appears in the `PROGRAM-ID`s of the library (`CBLTEQ`, `CBLTCTX`), in the messages (`CBLT-E200`), in the extension of the suites (`.cblt`) and in the project file (`cblt.json`). The command is `cobalto`, and `cblt` is the same command under a shorter name. The core is standard COBOL 85, written to compile with any compiler that follows the standard; that is the design goal, and the profiles table below says what has been verified. The CLI is Python with no dependencies; results come out in JUnit.

## Installing

Cobalto needs Python 3.9 or later and a COBOL compiler; the built-in local profiles use GnuCOBOL 3.x. Install it from PyPI, in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install cobalto
```

The virtual environment keeps the install out of the system Python, which Homebrew and recent Debian and Ubuntu do not let `pip` modify. That installs the `cobalto` command and its alias `cblt`. The COBOL core and the built-in profiles travel inside the package, so a project only holds its own programs, its suites and a `cblt.json`. To install from a clone of the repository instead, run `python3 -m pip install .` from its root; to work on Cobalto itself, `python3 -m pip install -e .` installs it from the working copy.

## Running

The commands are run from the project folder, the one that has `cblt.json`. In this repository the example project is [`examples/`](../examples/).

```bash
cobalto test
```

```bash
cobalto test --profile gnucobol-coverage
```

```bash
cobalto init /path/to/the/project
```

`init` creates `src/`, `tests/` and a `cblt.json` that says where the programs and the suites are (see "Project file").

Options of `test`: `--profile P`, `--filter TEXT` (only suites whose name contains it), `--coverage` (portable coverage by statement, branch and paragraph, see below), `--no-run` (compiles without running), `--generate-only` (only generates the suites, the driver and `build/remote/`; it does not reject remote profiles), `--host user@machine` and `--remote-dir` (remote profiles), `--json` (the result as JSON on standard output, see "Output"), `-v` (commands and output of each test case).

```bash
cobalto test --coverage
```

```bash
cobalto debug --suite TSTINV
```

`debug` compiles a single suite with the debug profile (`gnucobol-debug`, with `-g`) and leaves `.vscode/launch.json` ready to set breakpoints in the COBOL source from VS Code (see "Debugging in VS Code").

```bash
cobalto parse src/INVOICE.cbl
```

```bash
cobalto suggest --program INVOICE
```

`suggest` asks an AI model for a suite for the program, compiles it and runs it with coverage, gives the model back the errors, the failures and the paragraphs not executed, and leaves the best round as a draft in `tests/INVOICE.ai.cblt` (see "AI-assisted test generation"). With `--dry-run` it builds the prompt in `build/ai/` without sending it.

```bash
cobalto list
```

`list` shows the suites of the project and their test cases as the CLI reads them, without generating or compiling anything; with `--json`, as data (`suites` with `id`, `file`, `line`, `description`, `program` and `cases`, and `errors` with the suite files that have a syntax error). The VS Code extension builds its Test Explorer from it.

`parse` shows what Cobalto's own parser understands of a program (format, divisions, files, items, paragraphs, and the CALL, file, SQL and clock statements with their lines). It is useful to diagnose a `MOCK` that cannot find its paragraph or file.

## Cobalto's own tests

```bash
python3 tests/run.py
```

runs every layer of Cobalto's own tests: unit tests of the modules, the CLI end to end, interface tests, the example project with each profile and the syntax check in the strict dialects. [`tests/README.md`](../tests/README.md) says what each layer covers and how to run it alone. The one that goes through the whole CLI is:

```bash
python3 tests/cli/selftest.py
```

Regression of the catalog of errors and warnings: it builds a minimal project per scenario (`cobalto init` plus a synthetic program and a suite), breaks it in the way each code describes (invalid DSL, a program or paragraph that does not exist, a missing copybook, a compile error inside a test case, a suite that aborts, a remote profile without a host or without the marker, a line longer than 80 columns, `suggest` with a fake command) and checks the exit code and the message. It also checks the happy path (external, in-program, coverage), a `FAIL` with expected and actual, and `report` on results and screen output returned by hand from a host (with and without the manifest, in the shape that content copied from an OpenVMS terminal comes back in, and with the lines cut by the terminal). It covers the structured outputs too (`--json`, `results.json`, `parse --json`, `list --json`, `profiles --json`, `--version`, and the location of each compile error in the JSON), that a run that stops with an error writes it to the reports instead of leaving those of an earlier run, and a project that overrides a built-in profile, extends another and keeps a template in a file. There are 56 scenarios that run in parallel in a few seconds and end with the line `56 of 56 scenarios passed`; `--list` enumerates them, `--keep` leaves the temporary projects in place to look at them, and a subset can be passed (`python3 tests/cli/selftest.py E401 W305`). It does not contact any AI provider. Interface tests have their own self-test in `../tests/interface/selftest.py`.

## Example programs

[`examples/src/`](../examples/src/) has seven synthetic programs, each with its suite in [`examples/tests/`](../examples/tests/). The first three are small programs that exercise the tool (they are also the ones the automated checks of the VS Code extension use); the other four model business cases that someone from a bank or an insurer will recognize. All the data is made up.

| Program | What it does | Suite | What it shows |
|---|---|---|---|
| `DISCOUNT` | discount by amount (subprogram) | `DISCOUNT.cblt` (external), `TSTCATEG.cbl` (no DSL) | every kind of `EXPECT`, an intentional failure, `IGNORE` |
| `INVOICE` | invoicing: reads customers, calls `DISCOUNT`, writes a report | `INVOICE.cblt` (in-program) | `MOCK FILE`, `MOCK CALL`, `MOCK CLOCK`, `MOCK PARAGRAPH`, `VERIFY` |
| `LEGACY` | a "legacy style" paragraph (indexed file, dynamic `CALL`, `IF`s closed by the period) | `LEGACY.cblt` (in-program) | regression of the in-program rewriter |
| `LOANCALC` | installment of a loan under the French system, total interest, first due date with end of month and leap years, return codes through `LINKAGE` | `LOANCALC.cblt` (external) | `BEFORE-EACH`, numeric `EXPECT`s with decimals and negatives, `GREATER THAN`, `BETWEEN`, level 88 conditions; it is the suite whose results change with `-std=ibm` |
| `LOANBTCH` | settlement batch: reads the loan master file, calls `LOANCALC`, writes transactions, rejects and a control record | `LOANBTCH.cblt` (in-program) | one **interface** case (the mocked master file and the date go in, only what comes out through the files is checked, and the whole program is executed with `RUN`) and **internal** cases on single paragraphs; master file, transactions, rejects and clock mocked in `BEFORE-EACH` and per case, `MOCK CALL` with `EXPECT` on the parameters, and a case that fails because of a **defect seeded** in the program (the control record also counts the header) |
| `PREMIUM` | annual premium of a life insurance policy by age band (`OCCURS` + `SEARCH`) and coverage (`SEARCH ALL`), minimum premium, return codes | `PREMIUM.cblt` (external) | band limits, tables; in the debugger, the expanded `OCCURS` |
| `DAYCLOSE` | daily close of an account with a long legacy paragraph (`GO TO`, nested `IF`s closed by the period) and a control record with `COMP` fields | `DAYCLOSE.cblt` (in-program) | `PERFORM ... THRU`, `VERIFY PARAGRAPH` on paragraphs reached by `GO TO`, and the two cases that change with the `gnucobol-ibm` and `gnucobol-mf` profiles |

`INVOICE.iface.cblt` and `DISCOUNT.iface.cblt` test the first two programs through their interface: `RUN` on the batch with the files mocked (and a sequence of two calls to `DISCOUNT` told apart with `CBLT-CALL-COUNT`), and `RUN USING` on the subprogram.

In addition, `tests/*.ai.cblt` are the drafts generated by `cobalto suggest` for the first three programs.

Reference state: `cobalto test --coverage` gives **105 test cases, 415 asserts, 2 intentional failures** (the one in `DISCOUNT.cblt` and the seeded defect of `LOANBTCH`), **6 skipped, 0 errors**, and a portable coverage of 218/220 statements (99%) and 109/109 branches (the two statements not executed are the `0000-MAIN` of `DAYCLOSE`, which ends in `STOP RUN`), with 46 interface cases and 58 internal ones (the test without DSL, `TSTCATEG`, counts as one case and is not classified). `--profile gnucobol-coverage` gives the same totals. With `--profile gnucobol-ibm` five more test cases fail (the installment of `LOANCALC`, the two cases of the batch that use it, and the counter and the length of the control record of `DAYCLOSE`) and with `--profile gnucobol-mf`, two more (the two of `DAYCLOSE`). The `Failures` total of the console counts failed asserts: it reads 2 with the default profile, 12 with `gnucobol-ibm` and 5 with `gnucobol-mf`. With `--profile remote-sim` two more test cases fail, the two of `TSTLEG` that use the real indexed file instead of a mock: `LEGACY` assigns it to `build/master.dat`, a path relative to the project folder, and the simulated host runs in `build/sim-host/`, where that folder does not exist. There `Failures` reads 12 and portable coverage 214/220 statements and 105/109 branches.

## First suite in 15 minutes

A hands-on walkthrough on the example project (`examples/`), with `LOANCALC` as the program under test. It requires GnuCOBOL 3.x and Cobalto installed (see "Installing"); the commands are run from `examples/`. The numbers shown are verified with GnuCOBOL 3.2 on macOS.

### 1. Write the first test case

`src/LOANCALC.cbl` receives through `LINKAGE` a group `LN-LOAN` with the principal, the annual rate, the term and the start date, and returns in the same group the installment, the total interest, the first due date and a return code. An external suite declares a group with the same shape, sets it, calls the program and checks.

Create `tests/FIRST.cblt`:

```cobol
       TESTSUITE TSTFIRST 'My first suite: the installment of a loan'

       WORKING-STORAGE SECTION.
       01  WS-LOAN.
           05  WS-PRINCIPAL          PIC 9(9)V99.
           05  WS-ANNUAL-RATE        PIC 9(2)V9(4).
           05  WS-TERM-MONTHS        PIC 9(3).
           05  WS-START-DATE         PIC 9(8).
           05  WS-INSTALLMENT        PIC 9(9)V99.
           05  WS-TOTAL-INTEREST     PIC S9(9)V99.
           05  WS-FIRST-DUE          PIC 9(8).
           05  WS-RETURN-CODE        PIC XX.

       TESTCASE 'installment for 100,000 at 36% a year over 12 months'
           MOVE 100000 TO WS-PRINCIPAL
           MOVE 0.36 TO WS-ANNUAL-RATE
           MOVE 12 TO WS-TERM-MONTHS
           MOVE 20260131 TO WS-START-DATE
           CALL "LOANCALC" USING WS-LOAN
           EXPECT WS-RETURN-CODE TO BE '00'
           EXPECT WS-INSTALLMENT TO BE NUMERIC 10046.21
```

Run only that suite:

```bash
cobalto test --filter TSTFIRST
```

Result: 1 case, 2 asserts, 0 failures. The CLI generated `build/TSTFIRST.cbl` from the `.cblt`, compiled it together with the assertion library and the programs under test, ran it and read `build/cblt-results.txt` to build the console output and `build/junit.xml`.

### 2. Add test cases and fall into the shared state trap

Add two test cases at the end of the suite:

```cobol
       TESTCASE 'zero rate: installment is principal over term'
           MOVE ZERO TO WS-ANNUAL-RATE
           CALL "LOANCALC" USING WS-LOAN
           EXPECT WS-INSTALLMENT TO BE NUMERIC 8333.33

       TESTCASE 'first due date in a leap year'
           MOVE 20280131 TO WS-START-DATE
           CALL "LOANCALC" USING WS-LOAN
           EXPECT WS-FIRST-DUE TO BE NUMERIC 20280229
           EXPECT WS-INSTALLMENT TO BE NUMERIC 10046.21
```

Run it again. The third test case fails:

```
    FAIL  first due date in a leap year  (1 of 2 asserts)
          #5 EQNUM: expected [10046.210] actual [8333.330]
          EXPECT WS-INSTALLMENT TO BE NUMERIC 10046.21
```

The test cases share the `WORKING-STORAGE` of the suite and run in order inside the same generated program: the zero rate case left `WS-ANNUAL-RATE` at zero and the next one inherited it. The fix is to set the typical loan before each test case with `BEFORE-EACH`, and to leave in each case only what makes it different:

```cobol
       BEFORE-EACH
           MOVE 100000 TO WS-PRINCIPAL
           MOVE 0.36 TO WS-ANNUAL-RATE
           MOVE 12 TO WS-TERM-MONTHS
           MOVE 20260131 TO WS-START-DATE
       END-BEFORE

       TESTCASE 'installment for 100,000 at 36% a year over 12 months'
           CALL "LOANCALC" USING WS-LOAN
           EXPECT WS-RETURN-CODE TO BE '00'
           EXPECT WS-INSTALLMENT TO BE NUMERIC 10046.21
```

With the `BEFORE-EACH` block before the first `TESTCASE` and the four `MOVE`s removed from the first case, the suite gives 3 cases, 5 asserts, 0 failures. Rule of thumb: what a test case needs is set in `BEFORE-EACH` or in the case itself; never rely on what the previous one left behind.

### 3. Look at coverage and add the missing test case

```bash
cobalto test --filter TSTFIRST --coverage
```

Below the results comes the portable coverage by program and paragraph. The other programs of the project show 0% because `--filter` ran only this suite. For `LOANCALC`: 39 of 46 statements (84%) and 25 of 42 branches, and in `1100-CHECK-DATE`, 3 of 4 statements, with line 78 not executed. That line is the `MOVE "40" TO LN-RETURN-CODE`: no test case tried an invalid date. Add the case:

```cobol
       TESTCASE 'invalid start date returns 40'
           MOVE 20260230 TO WS-START-DATE
           CALL "LOANCALC" USING WS-LOAN
           EXPECT WS-RETURN-CODE TO BE '40'
           EXPECT WS-INSTALLMENT TO BE ZEROS
```

On the next run, `1100-CHECK-DATE` goes to 4 of 4 and `LOANCALC` to 40 of 46 statements. What is still not executed (zero principal, term out of range, rate above 200%, a month outside 1 to 12, a due date that rolls over into the next year) is the list of the next test cases. The same data is left in `build/lcov.info`, `build/coverage.xml` and `build/sonar-coverage.xml`, ready for CI. Coverage says which code ran, not whether the `EXPECT` was right: a test case with a wrong expected value covers just the same.

### 4. The same suite with another dialect

```bash
cobalto test --filter TSTFIRST --profile gnucobol-ibm
```

Without touching the suite, the profile compiles with `-std=ibm`. The two test cases that check the installment fail:

```
          #2 EQNUM: expected [10046.210] actual [10184.010]
```

With `-std=ibm`, GnuCOBOL limits the precision of the intermediate results of the `COMPUTE` that calculates the installment, and the difference is 137.80 per installment. Nothing failed at compile time: it compiles, runs and gives another number. This is what a portable suite is for: the same suite, with the compiler in use today and with the next one, shows program by program where the behavior changes. It matters in any change of compiler or dialect, and most of all in a migration.

### 5. Ask the AI for a draft of test cases

```bash
cobalto suggest --program LOANCALC --dry-run
```

With `--dry-run` the CLI builds the prompt in `build/ai/LOANCALC.round1.prompt.txt` and sends nothing: it is worth opening it to see exactly what the model receives (the program, the DSL and the rules). With a backend configured and without `--dry-run`, `suggest` proposes test cases, compiles them, runs them with coverage, gives the model back what failed or was left uncovered, and leaves the best round in `tests/LOANCALC.ai.cblt` as a draft for review (see "AI-assisted test generation").

### 6. The same from VS Code (optional)

With the extension installed (`../vscode-cobalto/README.md`), open the `examples/` folder in VS Code: `TSTFIRST` shows up in the Testing view with its test cases, and each one runs with a click. To debug, set a breakpoint on the `CALL` of the first case, run "Cobalto: Debug suite" and choose `TSTFIRST`: the session stops in the `.cblt` and the variables panel shows `WS-LOAN` with its fields and values in COBOL format (see "Debugging in VS Code").

When you are done, delete `tests/FIRST.cblt` so that the example project goes back to its reference totals, or keep it as your first suite.

## Two suite modes

| Mode | How it is declared | What it tests |
|---|---|---|
| External | suite without `PROGRAM` | a whole program through its `LINKAGE`, with `CALL` |
| In-program | `PROGRAM name` or `PROGRAM "path.cbl"` | single paragraphs of the program and its `WORKING-STORAGE`, and it allows `MOCK` / `VERIFY` |

In in-program mode the CLI generates `build/<suite>.cbl` as a **copy of the program under test** with the tests injected at the start of the `PROCEDURE DIVISION`: the `TESTCASE`s `PERFORM` any paragraph and read or set any field of the `WORKING-STORAGE`; when the cases end, the copy does `EXIT PROGRAM` without executing the original flow. The original program is still compiled separately (the copy is renamed to the id of the suite), so external and in-program suites on the same program live side by side. The `COPY` statements are expanded in the copy (they are searched for in the folder of the source, in `lib` and in the `copybooks` folders of `cblt.json`), and compile errors are reported on the line of the `.cblt` or of the original program that caused them.

Within either mode, Cobalto tells apart two **kinds of test case** and marks them in the console and in the JUnit: an **interface** case, if it only touches what goes into the program and what comes out (`LINKAGE` parameters, file records, `CALL`, SQL, clock, `STOP` and the suite's own fields), and an **internal** case, if it executes a paragraph that is not the entry, mocks or counts a paragraph, or uses a field of the program's `WORKING-STORAGE` outside a `MOCK`. Interface cases stay just as valid when the program is rewritten inside or when the target of a migration is another language; internal cases pinpoint a defect and support a refactoring for as long as the COBOL stays alive. An external suite is all interface cases; in an in-program suite both kinds live together, and `RUN` (see below) makes it possible to write interface cases on a batch without parameters. `BEFORE-EACH` and `AFTER-EACH` do not count for the classification, which is syntactic: a `WORKING-STORAGE` field that the program uses as an output by convention counts as internal.

## Writing a suite (DSL)

A file `tests/ANYNAME.cblt`. Everything that is not a keyword is plain COBOL and is copied as is to the generated program.

```cobol
       TESTSUITE TSTDISC 'Discounts by amount'

       WORKING-STORAGE SECTION.
       01  WS-AMOUNT                 PIC 9(7)V99.
       01  WS-RESULT                 PIC 9(7)V99.
       01  WS-CATEGORY               PIC X(10).
           88  WS-IS-PREMIUM         VALUE "PREMIUM".

       BEFORE-EACH
           MOVE ZERO TO WS-RESULT
           MOVE SPACES TO WS-CATEGORY
       END-BEFORE

       TESTCASE 'premium amount gets 20%'
           MOVE 2000 TO WS-AMOUNT
           CALL "DISCOUNT" USING WS-AMOUNT WS-RESULT WS-CATEGORY
           EXPECT WS-RESULT TO BE NUMERIC 1600
           EXPECT WS-CATEGORY TO BE 'PREMIUM'
           EXPECT WS-IS-PREMIUM TO BE TRUE

       IGNORE
       TESTCASE 'pending: negative amounts'
           MOVE 0 TO WS-AMOUNT
           EXPECT WS-RESULT TO BE ZEROS
```

| Keyword | What it does |
|---|---|
| `TESTSUITE id 'desc'` | Name of the generated program (30 characters at most, no spaces) and description |
| `WORKING-STORAGE SECTION.` | The suite's own fields; `COPY` is accepted |
| `BEFORE-EACH` … `END-BEFORE` | COBOL that runs before each test case |
| `AFTER-EACH` … `END-AFTER` | COBOL that runs after each test case |
| `TESTCASE 'desc'` | One test case; it is one testcase in the JUnit |
| `IGNORE` | Marks the next `TESTCASE` as skipped |
| `EXPECT field TO BE 'x'` / `identifier` | Alphanumeric equality (ignores trailing spaces) |
| `EXPECT field NOT TO BE 'x'` | Inequality. `NOT` also goes with `SPACES`, `TRUE` and `FALSE`; with the numeric forms and with `CONTAIN` it is a syntax error (`CBLT-E200`): write the opposite check |
| `EXPECT field TO BE NUMERIC n` | Numeric equality by value (works for COMP-3, binary, display) |
| `EXPECT field TO BE GREATER THAN expr` / `LESS THAN expr` | Numeric comparison; `expr` can be an arithmetic expression |
| `EXPECT field TO BE BETWEEN a AND b` | Inclusive range |
| `EXPECT condition-88 TO BE TRUE` / `FALSE` | Level 88 condition |
| `EXPECT field TO BE SPACES` / `ZEROS` | Figurative constants |
| `EXPECT field TO CONTAIN 'x'` | Substring |

Each `EXPECT` records its own line as the message, so a failure explains itself.

## In-program suite with mocks

Complete example in `tests/INVOICE.cblt` (on `src/INVOICE.cbl`) and `tests/LEGACY.cblt` (on `src/LEGACY.cbl`, "legacy style" code with statements closed only by the period). An excerpt:

```cobol
       TESTSUITE TSTINV 'Invoicing (in-program on INVOICE)'
       PROGRAM INVOICE

       WORKING-STORAGE SECTION.
       01  WS-CAPTURED               PIC X(80).

       TESTCASE 'full process with mocked files'
           MOCK FILE CUST-FILE
               ON READ
                   EVALUATE CBLT-READ-COUNT
                       WHEN 1
                           MOVE "C001ACME      000200000" TO CUST-REC
                       WHEN 2
                           MOVE "C002BETA      000050000" TO CUST-REC
                       WHEN OTHER
                           SET CBLT-AT-END TO TRUE
                   END-EVALUATE
           END-MOCK
           MOCK FILE REPORT-FILE
               ON WRITE
                   MOVE REPORT-REC TO WS-CAPTURED
           END-MOCK
           PERFORM 2000-PROCESS
           EXPECT WS-TOTAL TO BE NUMERIC 2050
           EXPECT WS-CAPTURED TO CONTAIN 'BETA'
           VERIFY PARAGRAPH 2100-CALC HAPPENED 2 TIMES
           VERIFY READ CUST-FILE HAPPENED 3 TIMES
           VERIFY CALL 'DISCOUNT' HAPPENED AT LEAST 2 TIMES
           VERIFY PARAGRAPH 3000-END NEVER HAPPENED

       TESTCASE 'calculation with DISCOUNT mocked'
           MOCK CALL 'DISCOUNT'
               MOVE 999 TO WS-NET
           END-MOCK
           PERFORM 2100-CALC
           EXPECT WS-NET TO BE NUMERIC 999
```

| Keyword | What it does |
|---|---|
| `PROGRAM name` / `PROGRAM "path.cbl"` | Turns on in-program mode; the name is searched for by `PROGRAM-ID` or file name in `sources` |
| `MOCK PARAGRAPH name` … `END-MOCK` | Replaces the body of the paragraph with the COBOL of the block (empty = `CONTINUE`) |
| `MOCK CALL 'PROG'` / `MOCK CALL identifier` … `END-MOCK` | Replaces the `CALL`s to that literal (or to that variable, for a dynamic CALL); the block can set the parameters, which are fields of the program. If the `CALL` had `NOT ON EXCEPTION`, that body runs after the mock |
| `MOCK FILE file` … `END-MOCK` | Replaces `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE` and `START` on that file. Inside go the blocks `ON READ`, `ON READ AT END`, `ON WRITE`, `ON REWRITE`, `ON DELETE`, `ON START`, `ON OPEN`, `ON CLOSE` with COBOL; without blocks, everything is a no-op with `FILE STATUS` "00" and `READ` returns end of file |
| `MOCK SQL ['text']` … `END-MOCK` | Replaces the `EXEC SQL ... END-EXEC` statements (all of them, or the ones that contain the text, ignoring spaces); the block sets the host variables and `SQLCODE` |
| `MOCK CLOCK` … `END-MOCK` | Lines `DATE 'yymmdd'`, `DATE YYYYMMDD '...'`, `DAY 'yyddd'`, `DAY YYYYDDD '...'`, `DAY-OF-WEEK 'd'`, `TIME 'hhmmsscc'`; replaces the `ACCEPT ... FROM DATE/DAY/TIME` statements of that kind |
| `VERIFY PARAGRAPH name HAPPENED n TIMES` | Counts the entries to the paragraph in the test case (by `PERFORM`, `GO TO` or fall-through) |
| `VERIFY CALL 'PROG' ...` / `VERIFY READ\|WRITE\|REWRITE\|DELETE\|START\|OPEN\|CLOSE file ...` / `VERIFY SQL ...` / `VERIFY CLOCK ...` | The same for CALL, file operations, SQL and clock |
| Count forms | `HAPPENED ONCE`, `HAPPENED n TIMES`, `NEVER HAPPENED`, `HAPPENED AT LEAST n TIMES`, `HAPPENED NO MORE THAN n TIMES` |
| `RUN` / `RUN USING a b c` | Executes the whole original flow through its entry (the first paragraph or section of the `PROCEDURE DIVISION`). With `USING`, it sets by position the items of `PROCEDURE DIVISION USING` (which in the copy live in `WORKING-STORAGE`) and on return copies back the ones that are fields, like a `CALL ... BY REFERENCE`; a literal or a figurative constant only goes in |
| `VERIFY STOP ...` | Counts the `STOP RUN`, `GOBACK` and `EXIT PROGRAM` of the program reached in the test case |

Rules:

- A `MOCK` applies **only to the `TESTCASE` that declares it** (or to all of them if it is in `BEFORE-EACH`). When each test case starts, all the mocks are turned off and the counters are set to zero. A mock of one case never affects another.
- If the original flow falls off the end of the program during a test case (a `GO TO` that leaves the paragraph executed with `PERFORM` and ends in the last paragraph), the case is left with a failed assert ("the case did not finish: the program fell off the end") and the suite goes on with the next case. To execute a paragraph that jumps to another, `PERFORM A THRU B` keeps the jump inside the range.
- Inside a `MOCK FILE ... ON READ` the block has to fill in the record of the `FD` (for example `MOVE ... TO CUST-REC`); the CLI takes care of the `INTO`, of the `FILE STATUS` ("00", "10" at end of file, "23" if the statement used `INVALID KEY`) and of executing the original `AT END` / `NOT AT END`. `CBLT-READ-COUNT` is 1 on the first read of the case, 2 on the second, and so on. `SET CBLT-AT-END TO TRUE` returns end of file. In `ON WRITE` the record already has the `FROM` applied and `CBLT-WRITE-COUNT` counts the writes.
- The COBOL of a `MOCK` block goes inside an `EVALUATE`, so it **takes no periods** (if a line ends in a period, the CLI removes it). `EXPECT` is accepted inside a mock, for example to check the parameters of a `CALL`.
- The `LINKAGE` items of the original program move to `WORKING-STORAGE` in the copy, so the tests set them with `MOVE` before doing `PERFORM`.
- Variables that the CLI adds and that are best left alone: `CBLT-CASE-NAME`, `CBLT-CASE-STAT`, `CBLT-MOCK-CTL` (`CBLT-I`, `CBLT-READ-COUNT`, `CBLT-WRITE-COUNT`, `CBLT-CALL-COUNT`, `CBLT-AT-END`, `CBLT-STOPPED`, `CBLT-MODE`, `CBLT-HIT`), and the paragraphs `CBLT-MAIN`, `CBLT-RESET`, `CBLT-BEFORE`, `CBLT-AFTER`, `CBLT-CASE-n`, `CBLT-ORIGINAL-MAIN`.

Known limitations of in-program mode:

- A mocked paragraph is rewritten as an `EVALUATE` with the original body inside, without its periods; the statements that depended on the period to close get their `END-xxx` added. That is why a paragraph that uses `NEXT SENTENCE` cannot be mocked (error `CBLT-E405`), and a `GO TO` inside the body keeps working but a bare `EXIT` becomes `CONTINUE`.
- Only paragraphs are mocked, not `SECTION`s. `OPEN`/`CLOSE` with several files are split into one statement per file and lose clauses such as `WITH NO REWIND`.
- In the copy, the `STOP RUN`, `GOBACK` and `EXIT PROGRAM` of the program **end the test case, not the process**: they set `CBLT-STOPPED` to true (`EXPECT CBLT-STOPPED TO BE TRUE` or `VERIFY STOP HAPPENED ONCE` check it) and the statements that follow in the same paragraph are guarded with `IF CBLT-NOT-STOPPED`. The guard is per paragraph: if the `STOP` happened in a paragraph called with `PERFORM`, the caller goes on with whatever it has after that `PERFORM`, unless it has a `STOP` of its own further up (then it stops too). That is why an interface case looks at what came out, not at what happened after the `STOP`.
- `RUN` executes only the entry (first paragraph or section); if the main flow falls from one paragraph into the next without `PERFORM`, use `PERFORM entry THRU last`.
- Inside a `MOCK CALL`, `CBLT-CALL-COUNT` is 1 on the first call of the case to that program, 2 on the second, and so on.
- `MOCK SQL` leaves the original `EXEC SQL` in the "no mock" branch, so the copy still needs the site's precompiler, and `SQLCA` has to be declared by the program. It is not verified with any real precompiler (GnuCOBOL does not ship one).
- `ACCEPT`/`DISPLAY` are treated as verbs without `ON EXCEPTION` (COBOL 85): in `CALL ... ON EXCEPTION DISPLAY x NOT ON EXCEPTION ...` the `NOT` is assigned to the `CALL`.
- Nested programs or several programs per file are not accepted in in-program mode (`CBLT-E406`). Free format: the parser detects it and parses it, but in-program generation on a free-format source is not verified with a compiler.
- The parser and the rewriter are Cobalto's own (`cobparse.py`, `inprog.py`), with no dependencies and no third-party code; they cover common COBOL 85 plus `END-xxx`, `EVALUATE`, inline `PERFORM`, `COPY ... REPLACING` and continuation of literals. They do not cover `REPLACE`, `COPY` inside a statement, or exotic dialects.

## Writing a test without the DSL

A COBOL program whose `PROGRAM-ID` starts with `TST`, receives `CBLT-CTX` through `USING` and calls the library: see `tests/TSTCATEG.cbl`. Useful when the site's compiler has particular rules and full control is wanted.

## Project file (`cblt.json`)

A project is a folder with a `cblt.json`. The file only states what differs from the defaults; an empty object is a valid project.

| Field | Default | What it is |
|---|---|---|
| `profile` | `gnucobol` | The profile used when `--profile` is not passed |
| `sources` | `["src/*.cbl"]` | The programs under test |
| `tests` | `["tests/*.cblt", "tests/*.cbl"]` | The suites: `.cblt` files and COBOL tests without the DSL |
| `copybooks` | `[]` | Folders with the project's copybooks (see below) |
| `build` | `build` | Where everything generated goes |
| `test_prefix` | `TST` | Start of the `PROGRAM-ID` of a COBOL test without the DSL |
| `lib` | the core inside the package | Folder with the COBOL core, for a project that pins its own copy |
| `profiles` | none | Profiles of the project, added to the built-in ones (see "Profiles") |
| `ai` | see "AI-assisted test generation" | Backend, model and rounds of `suggest` |

Paths are relative to the folder the command is run from. This is what `cobalto init` writes, and the whole `cblt.json` of the example project:

```json
{
  "profile": "gnucobol",
  "sources": ["src/*.cbl"],
  "tests": ["tests/*.cblt", "tests/*.cbl"],
  "copybooks": ["src"]
}
```

## Profiles

A profile says how to compile and run with one compiler on one platform. The built-in ones ship with the CLI, one file each in [`src/cobalto/profiles/`](../src/cobalto/profiles/). `cobalto profiles` lists them together with the project's own and marks the default one. With `--json` the list comes out as data (`default`, and `name`, `kind` and `description` of each profile); the VS Code extension reads it from there.

| Profile | Status |
|---|---|
| `gnucobol` | Verified on macOS with GnuCOBOL 3.2 |
| `gnucobol-coverage` | Verified: coverage by COBOL line with gcov (an exact alternative to portable coverage, GnuCOBOL only) |
| `gnucobol-ibm`, `gnucobol-mf` | Verified: the same GnuCOBOL with `-std=ibm` and `-std=mf`, to show that the same suite changes its results when the dialect changes. They are GnuCOBOL dialects, not the IBM or Micro Focus compilers; there is no profile for IBM Enterprise COBOL |
| `gnucobol-debug` | Verified on macOS: compiles with `-g` from `build/` to debug with lldb or lldb-dap (VS Code) |
| `remote-sim` | Verified: simulates a remote host with `sh -c` in `build/sim-host/`, same mechanics as VMS. Two example cases that use a real file fail there (see "Example programs") |
| `vms-vsi-cobol` | Generated DCL plus ssh/scp. Mechanics verified with `remote-sim`; compile, link, run and results file verified with VSI COBOL V3.1-0007 on OpenVMS V8.4-2L3, with the generated scripts run by hand and the results read by `cobalto report`. The labels of the generated DCL build script were renamed after that verification. ssh/scp is not verified against a real OpenVMS |
| `microfocus` | Template, not verified |

Fields of a local profile: `compile`, `pre`, `run`, `post` (commands with `{lib} {build} {exe} {driver} {tests} {sources}`, plus `{incl}` with one `-I` per `copybooks` folder, and `{lib_rel}`, `{tests_rel}`, `{sources_rel}` and `{incl_rel}`, the same paths relative to the build folder, for a profile that compiles from inside it), `results_org` (`LINE SEQUENTIAL` or `SEQUENTIAL`), `results_format` (`lines` or `fixed200`), `results_path`, `error_regex`, `coverage_glob` (gcov report), `coverage` (`true` to turn on portable coverage without passing `--coverage`).

A project adds or adjusts profiles in the `profiles` field of its `cblt.json`, stating only what changes. A profile with the name of a built-in one overrides those fields of it; a profile with a new name starts from another one with `extends`, or stands on its own if it states every field:

```json
{
  "profiles": {
    "vms-vsi-cobol": { "remote_dir": "DKA0:[TESTS]" },
    "gnucobol-strict": { "extends": "gnucobol", "compile": "cobc -x -std=cobol85 -I {lib} {incl} -o {exe} {driver} {lib}/CBLTLIB.cbl {tests} {sources}" }
  }
}
```

A long script does not have to be a JSON string: a field written as `{"file": "NAME"}` takes the text of that file, searched next to the `cblt.json` (next to the profile, for the built-in ones). That is how the build and run scripts of `vms-vsi-cobol` and `remote-sim` are kept: `vms-vsi-cobol.build.com`, `vms-vsi-cobol.run.com`, `remote-sim.build.sh` and `remote-sim.run.sh`. In a template, a literal brace is written twice (`{{` and `}}`).

To try a compiler that has no profile yet, and to contribute the profile, see [Adding a compiler](adding-a-compiler.md).

Field `copybooks` of the project: folders with the project's copybooks, in addition to the core and the folder of the source. They are used by the parser of in-program mode, by the compiler (through `{incl}`) and by the upload of remote profiles.

## Remote profiles

A profile with the `remote` field compiles and runs on another machine. The CLI:

1. Generates the suites and the driver as usual and prepares `build/remote/` with the sources to upload: names in uppercase, with the extension that the host's compile command accepts (`source_ext`, `.COB` in the VMS profile), in ANSI or terminal format (`source_format`; terminal in the VMS profile, which is what `COBOL` reads without `/ANSI_FORMAT`), padded to 80 columns if the profile asks for it (`pad80`, which only makes sense with ANSI format), the copybook with the extension the compiler expects (`copybook_ext`, `.LIB` in VSI COBOL), optionally the library split into one program per file (`split_lib`), and the build and run scripts generated from the `compile` and `run` templates of the profile (`scripts`, by default `CBLT_BUILD.COM` and `CBLT_RUN.COM`).
2. Uploads everything with `upload` (`{upload_files}`, `{host}`, `{remote_dir}`).
3. Runs each script with `remote` + `invoke` (`ssh {host}` + `@{script}` on VMS) and looks for the markers `CBLT-BUILD-OK` and `CBLT-RUN-OK` in the output; it does not depend on the exit code of ssh.
4. Brings back the results file with `fetch` to `results_local` and parses it the same way as for a local profile.

Without ssh (someone runs the scripts on the host by hand), the cycle is split in two:

```bash
cobalto test --profile vms-vsi-cobol --generate-only
# copy build/remote/ to the host, run the two scripts there and bring back
# CBLT_RESULTS.DAT and, optionally, the screen output saved to a file
cobalto report --results CBLT_RESULTS.DAT --output screen.txt -v
```

`--generate-only` leaves in `build/remote/` a manifest, `cblt-manifest.json`, with the profile, the results format and the suites; it is not uploaded to the host. `report` uses it instead of generating the suites again (another manifest with `--manifest`), accepts the results file as fixed records with no separator, with one line per record or pasted without trailing spaces, removes from the screen output the DCL echoes and the batch queue notices, and produces the same console output, the same `junit.xml` and the same exit code as `test`. If the copy cut the lines (an assert record that does not reach column 141), it warns with `W307`: the totals are still valid, but the description of each assert is missing and a long value may be incomplete.

```bash
cobalto test --profile remote-sim
```

```bash
cobalto test --profile vms-vsi-cobol --host user@vms -v
```

```bash
cobalto test --profile vms-vsi-cobol --generate-only
```

The last one only leaves `build/remote/` ready to be copied by hand; that is how the OpenVMS verification was done. Placeholders of the script templates: `{files}` (COBOL sources in the order driver, library, suites, programs), `{objs}` (the same ones with `obj_ext`, joined by `objs_sep`), `{compile_each}` (one line per source according to `compile_each`, which can be a text or a dictionary by extension, for example `.SCO` for the Rdb precompiler), `{host}`, `{remote_dir}`. The host is passed with `--host`, which keeps it out of the project file; a profile can also set it in its `host` field. The host's compile command goes in `compile_each` and is written as is into the script (in DCL an intermediate symbol does not resolve); the VMS profile comes with `COBOL/LIST`, and a site with its own compile command replaces it there.

`pad80` converts sources to 80-column records outside the CLI: `python3 -m cobalto.pad80 src/*.cbl --out output --upper`.

## Portable coverage

With `--coverage` (or `"coverage": true` in the profile) the CLI measures which statements, branches and paragraphs of the code under test the suites executed, **without depending on the compiler**: it uses neither gcov nor anything from the runtime. It is verified with GnuCOBOL 3.2.

How it works:

1. Each program of `sources` is compiled from an instrumented copy in `build/cov/` (same `PROGRAM-ID`, same `LINKAGE`): a table `CBLT-COV-HIT` in `WORKING-STORAGE` and an `ADD 1 TO CBLT-COV-HIT(n)` before each statement, including the ones nested in `IF`, `EVALUATE`, `AT END`, `INVALID KEY`, `ON EXCEPTION`, inline `PERFORM`, and so on. The in-program copies (`build/<suite>.cbl`) carry the same counters, with the same numbering, so both modes add up on the same program.
2. At each `EXIT PROGRAM` / `GOBACK` (and, if the flow can fall off the end, in an added paragraph `CBLT-COV-END`) the copy calls `CBLTCOV`, a program of the library that accumulates the counters by program name and sets them to zero in the copy.
3. When all the suites have ended, the driver asks `CBLTCOV` for the counters that are not zero and writes a record `C|program|index|count` for each one in the results file, before the `S|`. The COBOL never knows paragraph names or lines: the CLI keeps the map index -> paragraph and line in `build/cov/map.json`.
4. The CLI reads the `C` records and reports.

Branches: besides the statements, the CLI measures the branches of each `IF` (`THEN` and `ELSE`), of each `EVALUATE` and `SEARCH` (each `WHEN` group, the `WHEN OTHER`, the `AT END`) and of each conditional phrase (`AT END` / `NOT AT END`, `INVALID KEY`, `ON SIZE ERROR`, `ON EXCEPTION`, `ON OVERFLOW`, `AT EOP`). An `EVALUATE` with four `WHEN`s and a `WHEN OTHER` is five branches, and each one counts separately even if they are all on one line. No more code is needed in the copy: the entries to a branch are those of the first statement of its body, which is already instrumented (only a `NEXT SENTENCE` body gets a counter of its own), and the branch that the program does not write (`IF` without `ELSE`, `EVALUATE` without `WHEN OTHER`, `SEARCH` without `AT END`, `READ` without `NOT AT END`, `ADD` without `NOT ON SIZE ERROR`) is derived at report time as entries to the statement minus entries to its explicit branches. That is why the metric holds just the same inside a statement that in-program mode rewrites with a `MOCK` (the mocked `READ` that reaches end of file counts its `AT END`, and the one that does not, its implicit `NOT AT END`). The missing branches are listed by line and name: `140 WHEN "10"`, `55 ELSE implicit`, `42 NOT INVALID KEY implicit`.

Compound conditions: an `IF` with `AND` / `OR` (and each `WHEN` of an `EVALUATE TRUE`) is also measured by operand: each elementary condition counts the times it was true and the times it was false, **only when the program evaluated it**. In `IF WS-A > 0 AND WS-ITEM(WS-A) = 1`, the second operand is not counted when the first was false, just as the compiler does not evaluate it. To do that the CLI does not touch the statement: before it, it inserts a tree of nested `IF`s that evaluates the condition again in the same order and with the same short circuit, adds to one counter per outcome of each operand and discards the result (COBOL conditions have no side effects; the exception is `FUNCTION RANDOM` inside a condition, which would give two different values). In an `EVALUATE TRUE` the `WHEN`s are chained: the next one is only evaluated if the previous one was false. It understands `AND`, `OR`, `NOT` on a group in parentheses, nested groups and the abbreviated combined conditions of the standard (`WS-X = 1 OR 2 OR > 8`, which are expanded with the subject and the operator of the previous relation; a level 88 condition name is told apart from an abbreviation by the `DATA DIVISION`). What it does not understand (an abbreviation with `NOT`, a condition that does not fit within column 72, more than eight operands) keeps the ordinary branch coverage. The outcomes by operand are added to the `THEN` / `ELSE` / `WHEN` branches of the statement and are listed with the text of the operand: `98 WS-REM-400 = ZERO true`. In `LOANCALC`, the suite of the walkthrough above executes every statement of `1300-LEAP-YEAR` and still leaves `98 WS-REM-100 NOT = ZERO false` and `98 WS-REM-400 = ZERO true` not executed: no test case goes through a year divisible by 100 or by 400. `tests/LOANCALC.cblt` has the cases for 1900 and 2000 that close them, and it reaches 42 of 42 branches.

`GO TO a b c DEPENDING ON x` is measured the same way: an `EVALUATE x` inserted before the jump counts the target chosen (`11 GO TO 1200-TWO`), and the implicit fall-through, when `x` is 0 or greater than the number of targets and the program goes on with the next statement, is derived as entries minus jumps (`11 no jump implicit`). A plain `GO TO` is not a branch.

What it produces:

- Console: by program and paragraph, entries to the paragraph (count of its first statement), statements executed over the total, percentage, branches executed over the total (outcomes by operand included), `NOT EXECUTED` for the paragraphs that did not run and, in the partial ones, the lines with statements not executed and the branches not executed. A paragraph that only has `EXIT` is not executable and does not count. A mocked paragraph counts only when the original runs (the branch of the mock is not code under test).
- `build/lcov.info` (LCOV format, `DA:line,count` per statement, `FN`/`FNDA` per paragraph and `BRDA`/`BRF`/`BRH` per branch, on the line of the `IF`, `EVALUATE` or statement with a phrase): it is read by the Coverage Gutters extension of VS Code ("Watch" command) and by any CI tool that accepts LCOV. The Cobalto extension paints lines, not branches.
- `build/coverage.xml` (Cobertura XML, with `branch-rate`, `branches-covered`/`branches-valid` and `condition-coverage` per line): for GitLab, Jenkins, Azure DevOps and similar tools.
- `build/sonar-coverage.xml` (generic coverage format of SonarQube and SonarQube Cloud): see below.

Remote profiles: it works without changes, because the instrumented copies are uploaded like any other source and the `C` records come back in the same results file (verified with `remote-sim`). In `gnucobol-coverage` both reports live together; with `--coverage` the gcov lines are those of the instrumented copies.

### SonarQube

Sonar does not import LCOV or Cobertura XML for COBOL: the only route it documents is its generic format (`sonar.coverageReportPaths`). `cobalto test --coverage` writes it to `build/sonar-coverage.xml`, with paths relative to the folder of `cblt.json`, which must be the one the scanner analyzes:

```properties
sonar.projectKey=my-cobol-project
sonar.sources=src
sonar.tests=tests
sonar.coverageReportPaths=build/sonar-coverage.xml
sonar.testExecutionReportPaths=build/sonar-tests.xml
```

`build/sonar-tests.xml` is the generic test execution format, which Sonar imports with `sonar.testExecutionReportPaths` and shows as "Unit Tests", "Test Failures", "Skipped" and "Test Errors" (Sonar does not import JUnit for COBOL). Its paths are the suite files relative to the folder of `cblt.json`, which must be in `sonar.tests`; the `.cblt` files also need a language assigned in Sonar so that the report is not discarded (for example, `sonar.cobol.file.suffixes` with `.cblt`, with the COBOL analyzer). Cobalto does not measure times per test case: `duration` is 0.

With several Cobalto projects or several runs, each property accepts a comma-separated list. What you need to know:

- **Sonar's COBOL analyzer is required (Enterprise edition).** Verified with SonarQube Community 26.11 in Docker: without the analyzer, the `.cbl` files are indexed "with no language", do not appear in the project and the generic coverage sensor discards the report (`Coverage data ignored for 3 unknown files`). With the same files indexed under a language, the same report is imported whole (`Imported coverage data for 3 files`) and the measures match Cobalto's. The import with the real COBOL analyzer was not tried.
- **Statements and branches, not lines.** Sonar counts lines and conditions; Cobalto, statements and branches. The line of an `IF`, `EVALUATE`, `SEARCH` or of a statement with a conditional phrase is declared with `branchesToCover` = its branches, outcomes by operand included, and `coveredBranches` = the ones executed (with the example suites, the five-branch `EVALUATE` of `LOANBTCH` appears as `branchesToCover="5" coveredBranches="5"`, and the three-operand `IF` of `1300-LEAP-YEAR` in `LOANCALC` as `branchesToCover="8" coveredBranches="8"`). A line with no branches but with several statements (`WRITE ... INVALID KEY CONTINUE`) is declared with `branchesToCover` = statements on the line and `coveredBranches` = the ones executed, so Sonar marks it as partially covered. Even so, Sonar's "coverage" percentage (which combines lines and conditions) is not exactly the one on the console.
- **Copybooks.** The statements that come from a `PROCEDURE DIVISION` copybook are reported on the copybook (`cpy/X.cpy`, with its own lines), not on the program that copies it. For Sonar to show them, the copybook folder has to be in `sonar.sources`.
- **What Cobalto does not instrument** (`DECLARATIVES`, a bare `EXIT`, `NEXT SENTENCE`) does not go in the report; if the COBOL analyzer considers them executable, Sonar will count them as not covered.

Limitations: `DECLARATIVES` are not instrumented; a source with several programs or with a copybook that cannot be found is compiled without instrumentation (`CBLT-W305`); a program that exits with `STOP RUN` does not dump its counters (just as the driver would not get to write); `NEXT SENTENCE` counts as a branch but not as a statement; compound conditions are measured in `IF` and `EVALUATE TRUE`, not in `PERFORM UNTIL` or in `SEARCH WHEN` (they are evaluated again on each iteration and the tree cannot follow them without rewriting the loop), and the iterations of a `PERFORM UNTIL` are not measured. A program with more than 9999 counters (statements, `NEXT SENTENCE` bodies, outcomes by operand and targets of `GO TO DEPENDING ON`) cannot be instrumented whole (limit of `CBLTCOV`).

## Debugging in VS Code

The recommended way is Cobalto's VS Code extension (`vscode-cobalto/` in the repository; usage and installation in its [README](../vscode-cobalto/README.md)): Test Explorer, coverage in the gutter, debugging with COBOL names and stepping by COBOL statement, and syntax highlighting for the DSL. What follows describes what the CLI leaves ready, and it also works without the extension, with LLVM's LLDB DAP extension.

```bash
cobalto debug --suite TSTINV
```

That compiles only that suite with the `gnucobol-debug` profile (`cobc -g -fsource-location -save-temps` executed from `build/`, so that the debug map of the executable finds the `.o` files), writes or updates in `.vscode/launch.json` the configuration "Cobalto: debug TSTINV" (type `cobalto`, for the Cobalto extension) and two alternatives that do not need it: "(plain lldb-dap)" for LLVM's **LLDB DAP** extension, `llvm-vs-code-extensions.lldb-dap`, and "(CodeLLDB)" for **CodeLLDB**, `vadimcn.vscode-lldb`. It also leaves three maps in `build/`: `TSTINV.vars.txt` (each COBOL field and the C static that holds it), `TSTINV.lines.json` (each line of the generated source and its file and line of origin, `.cblt` or original program) and `TSTINV.layout.json` (all the data items of each program, with level, PIC, usage, OCCURS and offset inside its 01, taken from the symbol listing of `cobc -ftsymbols`; cobc only generates descriptors for the fields that the program references, and with this map the extension shows and modifies any field and any occurrence). The Cobalto extension runs this same command before launching the session and uses those maps.

With the Cobalto extension: a breakpoint in the `.cblt` or in the program under test, "Cobalto: Debug suite" (or F5), and at the stop you see `Globals` and `Locals` with COBOL names and formatted values, F10/F11 step by COBOL statement and the frames of the generated C are dimmed.

Without the Cobalto extension (LLDB DAP only, verified on macOS with GnuCOBOL 3.2 and the `lldb-dap` of Xcode):

1. Install the LLDB DAP extension. If it cannot find the adapter, in the VS Code settings: `"lldb-dap.executable-path": "/Applications/Xcode.app/Contents/Developer/usr/bin/lldb-dap"` (the CLI prints the path it found with `xcrun`).
2. Open the project folder (the one that has `cblt.json`) in VS Code and set a breakpoint on a COBOL statement: in an in-program suite, in `build/TSTINV.cbl` (the copy that is actually compiled); in a program called with `CALL`, in its source, for example `src/DISCOUNT.cbl`.
3. Run and Debug > "Cobalto: debug TSTINV (plain lldb-dap)".

What you see and what you do not (verified against `lldb-dap` over the DAP protocol and against `lldb`):

- The breakpoint on a COBOL line is verified and stops with the COBOL source in the editor and the stack `TSTINV_` > `TSTINV` > `CBLTDRV_`.
- COBOL variables have no name of their own: GnuCOBOL keeps each field as a static `b_NNN` (the bytes as they are: `b_32 = "000200000"`) and, if it uses it as a field, a descriptor `f_NNN`. In the variables panel, `Locals` shows the `LINKAGE` parameters of the stopped program and `Globals` its `WORKING-STORAGE`. **Each program numbers on its own**: in `TSTINV`, `WS-AMOUNT` is `b_32`; in `DISCOUNT`, `LN-AMOUNT` is `b_18` and `WS-RATE` is `b_17`. The file `build/TSTINV.vars.txt` lists, by program, which field each `b_NNN` is, in which panel it appears and which expression to type in the console.
- In the debug console, with the stack stopped in `DISCOUNT`, `(char*)cob_get_field_str_buffered(&f_17)` returns `WS-RATE` formatted by libcob (`"0.20"`) and `*(char(*)[9])b_18` the bytes of `LN-AMOUNT`. An `f_NNN` of another program gives `use of undeclared identifier`: use the numbering of the program it stopped in.
- Step over advances through the lines of the generated C (`build/TSTINV.c`) between one COBOL statement and the next; to go from statement to statement it is better to use breakpoints.
- These three things (COBOL names in the panel, a formatted value without typing expressions, stepping by COBOL statement) are exactly what the Cobalto extension in `vscode-cobalto/` solves; the above is what you see with plain LLDB DAP.

## AI-assisted test generation

`cobalto suggest --program PROGRAM` asks a language model for a `.cblt` suite for a program and validates it by running it. The result is a **draft for human review**: it documents what the program does today (characterization tests with synthetic data), not what it should do.

How each round works:

1. The CLI builds the prompt with the source of the program (copybooks expanded), the summary of Cobalto's own parser (`cobalto parse`), the suggested mode (external if it is a subprogram with `USING` and no paragraphs to isolate; in-program otherwise), the hand-written suite on that program if there is one (so that it covers what is missing and does not repeat cases), and in the following rounds the previous suite with the output of its run.
2. The model returns the complete suite; the CLI sets the id (`<PROGRAM>AI`), saves it in `build/ai/<PROGRAM>.round<n>.cblt` and runs it on its own with `test --coverage` and the profile of the project.
3. Score of the round: it compiles, no failures or errors, no internal cases when only interface cases were requested, covered statements of the program, cases. It stops when everything passes with the program 100% covered, when a round does not improve on the best one, or when `--rounds` run out (2 by default). The best round is left in `tests/<PROGRAM>.ai.cblt` (or `--out`); if none compiled, `CBLT-W601` and the drafts stay in `build/ai/`; if the best one has failures, `CBLT-W602`.

What is sent to the AI provider, and nothing else: the source of the program, the summary of the parser, the existing suite and the console output of each round. Each request is left in `build/ai/<PROGRAM>.round<n>.prompt.txt` and the raw answer in `.response.txt`, so they can be audited. **Use it only with your own sources or with the authorization of the owner of the code**; `--dry-run` shows exactly what would be sent without sending it.

Backends (`ai` field of `cblt.json`, or `--backend`, `--command`, `--model`):

| `backend` | What it does | Credentials |
|---|---|---|
| `api` | Anthropic's Messages API over HTTP, with no dependencies (`urllib`); default model `claude-opus-5-5`, with server-side `fallbacks` in case of a refusal | environment variable `ANTHROPIC_API_KEY`; it is never printed or stored |
| `command` | A command that receives the prompt on stdin and returns text on stdout. By default `claude -p --permission-mode dontAsk --output-format text` (the Claude Code CLI, with the user's session); it works for any other AI CLI | those of the command |
| `auto` (default) | `api` if there is an `ANTHROPIC_API_KEY`, otherwise `command` if the command is on the PATH | |

Fields of `ai`: `backend`, `command` (accepts `{model}`), `model` (empty = the default of each backend), `rounds`, `max_cases` (test cases per round, 12), `max_tokens`, `effort`, `timeout`, `mode` and `fill_expected`.

Kind of test case requested (`--mode` or `ai.mode`: `auto`, `interface`, `in-program`): with `interface` the prompt asks only for interface cases, and the classification of each round (the same one `cobalto test` shows) gives the model back the cases that touched the internals, with the reason, as an error of the round; the score penalizes them and a round is not perfect while one is left. With `in-program` it asks for single paragraphs; `auto` lets the model choose. Deterministic characterization (`--fill-expected` or `ai.fill_expected`): each equality `EXPECT` that fails (numeric, alphanumeric, `SPACES`/`ZEROS`, `TRUE`/`FALSE`) is changed to expect the value the program produced, with a `REVIEW` comment that keeps the original, and the round is run again without asking the model. It is "the AI proposes inputs, the program decides the expected values": an interface suite that records what the program does today is done in a single round. Recorded result with Claude (`claude -p`) on `INVOICE` and `LOANBTCH` with the hand-written suites present: 10 and 12 test cases, all with `RUN`, none internal, 32/32 and 55/55 statements in the first round; the seeded defect of `LOANBTCH` is flagged by the review comments of the draft.

What the prompt requires from the model: fixed-format COBOL 85 (a line longer than 72 columns is reported and counts as a round that did not compile), one test case per behavior (branches, `AT END`, limits), mocking files, `CALL`, SQL and clock in each case that goes through them, executing the main flow with `RUN` or `RUN USING` (the `STOP RUN`s of the program end the case, not the suite), expected values read from the code (with a `REVIEW` comment when it is not clear), and the suite's own fields with the `T-` prefix.

Recorded result with a real model (Claude through `claude -p`) on the first three example programs, with the hand-written suites already present: `DISCOUNT` 12 test cases and 9/9 statements in two rounds (the first used `NOT TO BE 'text'` on a numeric field, which the DSL does not accept: E201 fixed in round 2); `INVOICE` 12 test cases and 28/32 in the first round (what is missing is `0000-MAIN`, which has `STOP RUN`); `LEGACY` 10 test cases with 5 failures in the first round and 12 test cases with no failures and 21/25 in the second. The suites are in `tests/*.ai.cblt` as reviewed drafts; with them those three programs went from 17 to 53 test cases and their portable coverage from 55/66 to 58/66 statements. Each run took between one and three minutes.

Limitations: the quality of the suites depends on the model and they have to be read; the explanations in the `REVIEW` comments can be wrong even when the expected value is the real one (in `LEGACY` the model attributed to Cobalto a `NOT ON EXCEPTION` that GnuCOBOL binds to the preceding `DISPLAY`). A test case that fails can be a wrongly deduced expected value or a real defect: the loop asks the model to correct the expected value (characterization), so a defect of the program ends up documented as current behavior, not flagged. The score of a round counts covered statements, not branches (the branches not executed do go back to the model with the console output), and there is no guarantee that `max_cases` is respected. If `suggest` is run from inside a Claude Code session, the `command` backend clears the `CLAUDE*` variables and `ANTHROPIC_BASE_URL` from the environment so that the nested `claude -p` finds its session.

## Output

- Console with PASS / FAIL / SKIP / ERROR per test case, the `EXPECT` that failed with expected and actual, the `DISPLAY` output of each case with `-v`, and in in-program suites the mark `· interface` or `· internal` per case (with `-v`, the reason) plus the line `Interface cases: X  internal: Y`.
- `build/junit.xml` with one testcase per `TESTCASE`, `<skipped/>`, `<failure>`, `<error>` if the suite aborted, `<system-out>` and, as properties of the case, `cobalto.kind` (`interface` or `internal`) and, if it failed, `cobalto.expected` and `cobalto.actual` of the first assert that failed. The text of the `<failure>` is for people; whoever needs the values takes them from the properties or from `results.json`.
- `build/results.json`: the complete model of the run, from which the console, the JUnit and the Sonar report are rendered. It carries `schema` (version of the format, 1 today), `cobalto` (version of the CLI), `profile`, `ok`, `totals` (`cases`, `asserts`, `failed_asserts`, `failed_cases`, `skipped`, `errors`, `interface`, `internal`), each suite with its test cases (`status`, `kind`, `reasons`, `asserts` with `expected` and `actual`, `output`) and the asserts that ran with no detail (`unlogged_asserts`, `unlogged_failures`), the warnings (`warnings`) and, with `--coverage`, the coverage by program and paragraph (`coverage`). A run that stopped with an error also carries `error`, with `code` and `message`. After a build failure (`CBLT-E202`), `error` also has `details`, one entry per compile error the profile's `error_regex` matched (`code`, `file` and `line` of the `.cblt` or program that caused it, `generated` with the line of the generated COBOL when the error was mapped back from it, or `null`, and `message`), or, when it matched none, `output`, the compiler's output. The compile step takes standard output and standard error as one stream, in the order the compiler wrote them, so `output`, the console and `-v` show a compiler's messages whichever stream it reports on. The run's `binary_exit` is `null`, since nothing ran, and so is the `profile` of a `report` that stopped before reading the manifest.
- `cobalto test --json` and `cobalto report --json` write that same model to standard output and send the console to stderr, also when they stop with an error, with exit code 2. When `cblt.json` cannot be read, and in the other commands, a fatal error is `{"error": {"code", "message"}}` next to `schema` and `cobalto`. `cobalto parse FILE --json` returns what the parser understands of the program. `cblt --version` shows the version.
- A run of `test` or `report` that stops with exit code 2 once `cblt.json` is read (a configuration, DSL, build or fetch error) writes that error to `junit.xml`, `sonar-tests.xml` and `results.json` instead of leaving those of an earlier run. `results.json` has `ok` false, no suites, `totals.errors` 1 and `error`. `junit.xml` has a single testsuite, `cobalto`, with one testcase named after the code and an `<error>` with the message; after a build failure, the text of the `<error>` lists the `CBLT-E201` lines, or holds the compiler's output. `sonar-tests.xml` has no files, since there is no suite file to put the error in. The coverage reports keep the last run with `--coverage`, and a run with `--no-run` or `--generate-only` that ends without an error leaves every report as it was. When `cblt.json` cannot be read, the CLI cannot tell which folder is the build folder and writes nothing there.
- The JSON files that `cobalto debug` writes (`build/<SUITE>.lines.json`, `build/<SUITE>.layout.json`), the manifest of `--generate-only` and the coverage map (`build/cov/map.json`, with the programs under `programs`) carry the same `schema` field. `report` still reads earlier manifests.
- `build/sonar-tests.xml`, SonarQube's generic test execution format (`sonar.testExecutionReportPaths`): one `<file>` per suite file and one `<testCase>` per test case, with `<failure>`, `<skipped>` or `<error>`; `duration` is 0 because Cobalto does not measure times per test case.
- Exit code 1 on any failure or error; 2 on a configuration, DSL or compile error.
- Compile errors are reported on the line of the `.cblt` that caused them (or of the original program, in in-program mode).
- With `--profile gnucobol-coverage`, the in-program copy appears as `TSTINV.cbl (in-program copy of INVOICE.cbl)` and counts as code under test.
- With `--coverage`, the table of portable coverage by program and paragraph (statements and branches), `build/lcov.info`, `build/coverage.xml`, `build/sonar-coverage.xml` and `build/cov/map.json`.
- With `debug`, `.vscode/launch.json` and, in `build/`, `<suite>.vars.txt`, `<suite>.lines.json` and `<suite>.layout.json`.
- With `suggest`, the draft `tests/<PROGRAM>.ai.cblt` and in `build/ai/` the prompts, answers and suites of each round.

Messages of the CLI (prefix `CBLT-`): `E100` no suites, `E101` profile does not exist, `E102` host missing, `E103` `cblt.json` missing, `E104`/`E105` remote upload or build, `E106` manifest of `--generate-only` not found (`report`), `E200` DSL syntax, `E201` compile error mapped to its source line, `E202` build failed, `E203` source cannot be converted to 80 columns, `E300` no results file, `E400` program of `PROGRAM` not found, `E401` paragraph does not exist, `E402` `CALL` not found, `E403` file not declared or without that operation, `E404` the program could not be parsed (for example, copybook not found), `E405` paragraph with `NEXT SENTENCE`, `E406` program not fit for in-program mode, `E407` `MOCK`/`VERIFY` without `PROGRAM`; `E500` suite does not exist in `debug`, `E501` `debug` with a remote profile, `E600` `suggest` without an AI backend, `E601` the backend failed, `E602` the answer contains no suite; warnings `W301` suites that never started, `W302` `PROGRAM-ID` of a legacy test repeated in a DSL suite (that file is not compiled), `W303` text in columns 73-80, `W304` `MOCK SQL`/`MOCK CLOCK` with no statements to mock, `W305` program that could not be instrumented for coverage (the original is compiled), `W306` it ran with coverage but no `C` record arrived, `W307` assert records cut when the results file was copied (the description is missing and the values may be incomplete), `W308` a suite ran more asserts than its log keeps (500 entries, asserts plus test cases): the rest are counted with no detail, and if one of them failed the suite is reported as `ERROR` and the run fails, `W601` no round of `suggest` compiled, `W602` the best round has failures.

## Source layout

The CLI is the Python package [`src/cobalto/`](../src/cobalto/), standard library only. It also holds the COBOL core (`lib/`: `CBLTLIB.cbl` and the copybook `CBLTCTX.cpy`) and the built-in profiles (`profiles/`). Dependencies go one way: the entry point imports the commands, the commands import the modules below them, and the parser and the 80-column padder import nothing.

| Module | What it holds |
|---|---|
| `cli.py` | Entry point of `cobalto` and `cblt`: arguments, dispatch and the single place where the process exits |
| `commands.py` | The subcommands: `test`, `report`, `debug`, `suggest`, `init`, `list`, `profiles`, `parse` |
| `config.py` | Loading `cblt.json` over the defaults and the built-in profiles, picking a profile, the fields of the command templates |
| `messages.py` | The catalog of `CBLT-Exxx` / `CBLT-Wxxx` messages, `CobaltoError`, versions and the JSON output |
| `model.py` | Records shared across modules: a suite in a run, and what generating the suites produced |
| `dsl.py` | The `.cblt` parser, its records (suite, test case, mock, verify) and the expansion of an external suite |
| `cobolgen.py` | Writer for generated fixed-format COBOL, with the map from each generated line to its source |
| `build.py` | Discovery of the suites and generation of the test programs and the driver |
| `driver.py` | The generated driver program |
| `inprog.py` | The in-program rewriter: test cases, mocks and coverage counters injected into a copy of the program |
| `cobparse.py` | The COBOL parser |
| `coverage.py`, `condcov.py` | Portable coverage: instrumentation plan, compound conditions, summary and report files |
| `runner.py`, `remote.py` | Running a profile locally, and on another host with staged sources, generated scripts and the manifest |
| `results.py`, `reports.py` | Reading the results file into the run model, and rendering it: console, JUnit, Sonar, JSON |
| `debuginfo.py` | Variable map, data layout and `launch.json` for debugging with GnuCOBOL |
| `suggest.py` | The AI backends, the prompts and the scoring of each round |
| `pad80.py` | Standalone converter to 80-column records |

Cobalto's own tests are in [`tests/`](../tests/), with a README that describes each layer. The reasons behind this structure, and behind the COBOL the CLI generates, are in the [design document](design.md).
