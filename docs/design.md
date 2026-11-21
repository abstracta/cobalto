# Cobalto: design

This document explains how Cobalto is built and why. It is for people who want to change the tool, port it to another compiler, or judge whether its approach holds for their code. How to use it is in the [reference](reference.md); what has been verified, and on which compilers, is in the status table of the [README](../README.md).

## 1. Goal and principles

The goal is that a team with COBOL can write and run unit tests with the compiler it already has, with no new license and no dependency on a vendor, and that the same tests keep running when the program moves to another compiler or platform.

Three principles follow from that goal, and most decisions below are one of them applied.

**A portable core, and everything else in a profile.** What runs inside the COBOL process (the assertions, the shared context, the driver) is standard COBOL 85 in fixed format. What depends on the environment (how to compile, link and run, where the results file lives, whether the build happens on another machine) is a declarative profile of the CLI. Supporting a compiler means writing a profile, not changing the core.

**The COBOL never interprets results.** The COBOL side writes a plain text file and nothing else. Reading it, deciding what passed, rendering reports and choosing the exit code all happen in the CLI. This keeps the COBOL minimal, which is what makes it portable, and lets the CLI change without recompiling anything on the host.

**Generated COBOL is ordinary COBOL.** A suite, an in-program copy and an instrumented copy are all plain COBOL 85 sources written to `build/`. They can be read, compiled by hand, uploaded to a host with no Python, and debugged like any other program. Nothing depends on a runtime hook.

## 2. Architecture

```
 code under test            Cobalto core (COBOL 85)        Cobalto CLI (Python)
 +--------------+           +------------------+           +---------------------+
 | src/*.cbl    |<-- CALL --| build/<suite>.cbl|<-- CALL --| build/CBLTDRV.cbl   | generated
 |              |           | (generated from  |           | (driver)            |
 +--------------+           |  tests/*.cblt)   |           +----------+----------+
                            +--------+---------+                      | writes
                                     | CALL                           v
                            +--------v---------+           +---------------------+
                            | CBLTLIB.cbl      |           | results file        |
                            | CBLTCTX.cpy      |           | (records T A E S C) |
                            +------------------+           +----------+----------+
                                                                      | read by
                                      +-------------------------------v-------+
                                      | CLI: discover, generate, compile and  |
                                      | run (profile), read, build the model, |
                                      | render console, JUnit, JSON, coverage |
                                      +---------------------------------------+
```

A run of `cobalto test` goes through these steps:

1. **Discover.** The files matched by `tests` in `cblt.json` are read: `.cblt` suites are parsed, and hand-written test programs are found by their `PROGRAM-ID` prefix.
2. **Generate.** Each suite becomes a COBOL program in `build/`. With coverage, each program under test gets an instrumented copy in `build/cov/`. A driver program that calls every suite is written last.
3. **Compile and run.** The profile's commands are filled in and executed, locally or on another host.
4. **Read.** The results file and the captured standard output are turned into one model of the run.
5. **Render.** The console, `junit.xml`, `sonar-tests.xml`, `results.json` and the coverage reports are all written from that model. The exit code is decided here.

Everything is linked into one executable: the driver, the library, the suites and the programs under test. A test reaches the program under test with a static `CALL`.

## 3. The COBOL core

The core is two files, `CBLTLIB.cbl` and `CBLTCTX.cpy`, in `src/cobalto/lib/`.

### 3.1 Shared context

One record travels by `USING` between the driver, the suites and the assertion programs. Whoever copies it declares the 01 level:

```cobol
       01  CBLT-CTX.
           COPY CBLTCTX.
```

It holds the name of the running suite, the assert and failure counters, an optional message for the next assert, the comparison buffers (`CBLT-EXP` and `CBLT-ACT`, alphanumeric; `CBLT-EXP-NUM`, `CBLT-ACT-NUM` and `CBLT-EXP-NUM2`, numeric) and a log of the asserts of the suite.

A record passed by reference was chosen over `EXTERNAL` items or any other form of shared storage because it is the one mechanism that behaves the same in every compiler and does not depend on how a linker resolves shared symbols.

### 3.2 Assertion programs

| Program | What it does |
|---|---|
| `CBLTINI` | Initializes the context. Called by the driver before each suite |
| `CBLTEQ`, `CBLTNE` | `CBLT-EXP` equal or not equal to `CBLT-ACT`, by the alphanumeric comparison rule of COBOL |
| `CBLTEQN` | `CBLT-EXP-NUM` equal to `CBLT-ACT-NUM`, by value |
| `CBLTGT`, `CBLTLT`, `CBLTBT` | Greater than, less than, between two bounds, by value |
| `CBLTCT` | `CBLT-ACT` contains `CBLT-EXP` |
| `CBLTCAS` | Marks the start of a test case, or of an ignored one, in the log |
| `CBLTREC` | Records an assert in the log. Internal |
| `CBLTCOV` | Collects coverage counters (section 7) |

An assert is two `MOVE`s and a `CALL`:

```cobol
           MOVE "PREMIUM"   TO CBLT-EXP
           MOVE WS-CATEGORY TO CBLT-ACT
           CALL "CBLTEQ" USING CBLT-CTX
```

That is more verbose than a call with two arguments, on purpose. Without `ANY LENGTH` or intrinsic functions a subprogram cannot know the size or the type of the caller's field. The `MOVE` solves it with standard rules: a COMP-3, a binary or a display field moved to `CBLT-ACT-NUM` arrives as the same value, so the numeric asserts compare values and never storage. Nobody is expected to write this by hand: the DSL (section 5) expands `EXPECT WS-CATEGORY TO BE 'PREMIUM'` into those three lines.

Program names have at most seven characters and no hyphens, so they fit linkers that limit external names to eight characters.

### 3.3 What the core does not use

Each of these would have made the core shorter, and each ties it to a family of compilers.

| Construct | Why it is avoided | What is used instead |
|---|---|---|
| Procedure pointers (`SET ... TO ENTRY`) to find tests at run time | Compiler extension | A generated driver with one explicit `CALL` per suite |
| Intrinsics that name the current module or its caller | Compiler extension | The driver knows the name of each suite and passes it |
| `PIC X ANY LENGTH` | COBOL 2002 | Fixed buffers filled with `MOVE` |
| Runtime error and exit procedures | Runtime-specific | The CLI detects an abort from the unfinished results file (section 4) |
| Free format and `*>` comments | COBOL 2002 | Fixed format, `*` in column 7 |
| `RETURN-CODE` | Not in the 85 standard | The CLI decides the exit code |
| `LINE SEQUENTIAL` hard-coded | Extension | The file organization is a field of the profile |
| `EXTERNAL` data | Linker-dependent | The context passed by `USING` |
| `GOBACK` | Not in the 85 standard | `EXIT PROGRAM` |

The check that keeps this honest is `tests/dialects/`: the library, the generated driver, the generated suites and the instrumented copies must pass `cobc -fsyntax-only` with no errors and no warnings under eight dialect configurations of GnuCOBOL: its default, `cobol85`, `cobol2002`, `cobol2014`, and the strict IBM, Micro Focus, ACUCOBOL and RM ones. That is a strong approximation, not a replacement for compiling with the real compiler.

### 3.4 Limits fixed in the core

These are constants in the COBOL, chosen to be comfortable. Raising one costs memory and nothing else.

- Alphanumeric comparison uses 256 bytes. The report shows the first 60 characters of the expected and the actual value, and 59 of the description.
- Numeric comparison uses `S9(15)V9(3)`: three decimals.
- The log keeps the first 500 entries of a suite (asserts plus one entry per test case). Further asserts are still counted, and the CLI says how many arrived with no detail (`CBLT-W308`). If one of those failed, the suite is reported as an error: a failure that cannot be shown is never a pass.
- A program can have at most 9999 coverage counters, and a run 30,000 counters across 200 programs.

## 4. The driver and the results protocol

The CLI generates `build/CBLTDRV.cbl`. For each suite the driver calls `CBLTINI`, writes a `T` record, calls the suite with `CBLT-CTX`, and then dumps the log.

| Record | Meaning |
|---|---|
| `T\|suite` | The suite started |
| `A\|status\|number\|kind\|expected\|actual\|description` | One assert (`P` or `F`), or the start of a test case (kind `CASE`, status `C`, or `I` if ignored) |
| `E\|suite\|asserts\|failures` | The suite ended |
| `C\|program\|index\|count` | One coverage counter, only with coverage |
| `S\|suites\|asserts\|failures` | The run ended |

Records are 200 bytes. The `A` record has fixed columns, and the CLI reads it by position, so a `|` inside a value does not shift the fields. The counts of the `E` record are checked against the `A` records that arrived, which is how asserts beyond the log (section 3.4) are noticed.

**Aborts.** The file is written suite by suite. If a suite kills the process, the suites before it are complete, the one that died has a `T` without an `E` and is reported as an error, and the ones that never started are known because the CLI knows how many it generated. The asserts of the suite that died are lost, because the log lives in memory until the driver writes it. Writing each assert to the file as it happens is not portable: a file belongs to one program.

**Two file shapes.** The profile says how the driver declares the file (`results_org`) and how the CLI reads it (`results_format`): text lines, or fixed 200-byte records with no separator, which is what a `SEQUENTIAL` file is on hosts with record-oriented file systems. The reader also accepts a fixed-record file that gained line breaks on the way back.

**Records that arrive damaged.** When a results file is brought back from a host by hand, for example copied from a terminal, lines can come cut at the screen width. A complete `A` record always reaches a known column, so the CLI can tell a cut record from a short one and says so (`CBLT-W307`) instead of reporting a truncated value as the real one.

**Output per test case.** The driver and the suites write `CBLT-T|suite` and `CBLT-C|case` markers with `DISPLAY`. The CLI captures the standard output and splits it at those markers, so the `DISPLAY`s of a program end up attached to the test case that produced them. `DISPLAY` is standard, and nothing has to be redirected from inside the COBOL.

**Control bytes.** `CBLTREC` replaces bytes below space with `?` in the expected value, the actual value and the description. An assert on an uninitialized record area would otherwise put binary data in a text file, which some runtimes reject.

## 5. Suites: the DSL and its expansion

The DSL is a file format of the CLI, not a feature of the core. A `.cblt` file has a `TESTSUITE` header, its own `WORKING-STORAGE`, optional `BEFORE-EACH` and `AFTER-EACH` blocks, and `TESTCASE`s that mix ordinary COBOL with `EXPECT` lines. The CLI expands it to one COBOL 85 program with a paragraph per test case, where each `EXPECT` becomes the `MOVE`s and the `CALL` of section 3.2 and carries its own text as the description of the assert.

Putting the readable syntax in the CLI is what lets the core stay small. A precompiler written in COBOL would have been portable too, but text processing in COBOL is fragile, and every form the DSL accepts would have had to be compiled and verified on every target.

**Line map.** The writer of generated COBOL (`cobolgen.py`) records, for every line it emits, the file and line it came from. A compile error on a generated line is reported at the line of the `.cblt`, or of the original program in in-program mode. The same map later moves breakpoints for the debugger (section 10).

**Rejecting rather than guessing.** When the DSL cannot express a check faithfully, it is a syntax error. `EXPECT X NOT TO BE NUMERIC 5`, for example, is rejected because the core has no negated numeric assert, and expanding it to something that passes whatever the value is would be worse than refusing.

**Hand-written tests.** A test can also be a COBOL program written by hand: a `PROGRAM-ID` that starts with the configured prefix, the context received by `USING`, and `EXIT PROGRAM` at the end. The CLI finds these by reading `PROGRAM-ID`s, so there is no registration step. They exist for whoever wants full control over the test program.

## 6. In-program mode

An external suite tests a program through its interface. Much legacy COBOL has no usable interface: a batch program with no parameters, files opened in the first paragraph, the logic spread over paragraphs that share `WORKING-STORAGE`. For that code, a suite declares `PROGRAM name` and the CLI generates a **copy of the program with the tests injected**. Test cases `PERFORM` any paragraph, read and set any field, and replace what the program depends on, without refactoring the program first.

### 6.1 The parser

Rewriting a program safely needs to know where each statement starts and ends. `cobparse.py` is a parser written for this purpose, with no dependencies. It is not a full COBOL parser, and it understands only what the rewriter needs:

- fixed and free format, comments, debug lines, continued literals;
- `COPY ... REPLACING`, expanded before tokenizing, with the file and line of origin kept for every expanded line;
- divisions, sections, `PROGRAM-ID`, the `USING` of the `PROCEDURE DIVISION`, `SELECT` with its `FILE STATUS`, `FD` records, data items with level and name;
- paragraphs and sections with their ranges;
- statements with their exact extent: a recursive descent that knows the COBOL 85 verbs and which conditional phrases each one takes (`AT END`, `INVALID KEY`, `ON EXCEPTION`, `ON SIZE ERROR`, `ON OVERFLOW`, `AT EOP`, and their `NOT` forms), and whether a statement was closed by its `END-xxx` or relied on the period.

It does not validate syntax or resolve types, and when it meets something it does not know it advances token by token instead of failing. `REPLACE`, nested programs and several programs in one file are not supported. Existing parsers were considered and set aside because they bring a native binding or another runtime, and the CLI has to run on a machine with nothing but Python.

`cobalto parse FILE` shows what the parser understood of a program, which is the first thing to look at when a `MOCK` does not find its target.

### 6.2 The copy

`build/<suite>.cbl` is built like this:

1. The source up to `WORKING-STORAGE` is copied line by line, with `COPY` expanded and the `PROGRAM-ID` renamed to the id of the suite. The original keeps its name and is still compiled, so external and in-program suites of the same program live in one executable.
2. The `LINKAGE` items of the original move to `WORKING-STORAGE`, where test cases can set them. Cobalto's control items and the suite's own `WORKING-STORAGE` follow. The only `LINKAGE` left is `CBLT-CTX`, and the header becomes `PROCEDURE DIVISION USING CBLT-CTX`. For the driver, an in-program copy is one more suite.
3. At the start of the `PROCEDURE DIVISION`, after `DECLARATIVES` if any, go the test paragraphs: a dispatcher, a reset, the before and after blocks, and one paragraph per test case.
4. The rest of the program is copied line by line, except for the points that are rewritten.

Copying line by line, and rewriting only where needed, keeps the copy recognizable next to the original and keeps the line map exact.

### 6.3 Mocks per test case

Each mocked target (a paragraph, a called program, a file, an SQL statement, the clock) gets a mode variable, and each `MOCK` block declared for it is a numbered variant. Every place in the program that corresponds to the target is rewritten as:

```cobol
           ADD 1 TO CBLT-HIT(c)
           EVALUATE CBLT-MODE(m)
           WHEN 1
               <the code of mock variant 1>
           WHEN OTHER
               <the original statement>
           END-EVALUATE
```

A reset paragraph clears every mode and counter before each test case, and the case sets the modes of the mocks it declares. So a mock lives only in its test case, and the original code is still there for the others. This was the main design choice of the mode: with mocks applied once for a whole suite, testing the real paragraph and a replaced one would need two suites.

`VERIFY` expands to the existing numeric asserts on the hit counters. A target that only has a `VERIFY` gets a counter and no `EVALUATE`.

By kind of target:

- **Paragraph.** The header stays, and the original body goes into the `WHEN OTHER` without its periods. Every statement that relied on a period to end (an `IF` without `END-IF`, a `READ ... AT END` without `END-READ`) gets its terminator inserted, innermost first. This is the most delicate rewrite in the tool, because it depends on the parser nesting statements exactly as the compiler does. `NEXT SENTENCE` changes meaning once the periods are gone, so a paragraph that uses it cannot be mocked (`CBLT-E405`).
- **`CALL`.** The variant is the mock's code followed by the body of the original `NOT ON EXCEPTION`. Static and dynamic calls are both matched.
- **File.** A mocked `READ` runs the mock's `ON READ` block, which fills the record, and then sets the `FILE STATUS` and takes the original `AT END` or `NOT AT END` branch. `WRITE`, `REWRITE`, `DELETE` and `START` work the same way. `OPEN` and `CLOSE` are split into one statement per file, so that one file of a multi-file `OPEN` can be mocked and another left real.
- **SQL.** The variant replaces an `EXEC SQL` statement. The original is kept verbatim in the `WHEN OTHER`.
- **Clock.** `ACCEPT ... FROM DATE`, `DAY`, `DAY-OF-WEEK` and `TIME` become a `MOVE` of the literal the mock declares.

### 6.4 Running the whole program: stops, `RUN` and falling off the end

Testing a batch program as a whole inside a copy raises three problems.

**`STOP RUN` would end the process.** In the copy, `STOP RUN`, `GOBACK` and `EXIT PROGRAM` are rewritten to count the stop and set a flag. Then the statements that follow in the same paragraph are wrapped in a guard, `IF CBLT-NOT-STOPPED ... END-IF`, so that the paragraph does nothing else. Jumping out with `GO TO` was considered and discarded: leaving the range of an active `PERFORM` is valid COBOL but leaves the runtime's `PERFORM` stack pointing at a paragraph that will run again later. The guard is per paragraph: what a calling paragraph does after its `PERFORM` returns still runs, unless it has a stop of its own above.

**The entry point.** `RUN [USING a b c]` moves the arguments to the items of the original `USING`, performs the paragraph or section where the original flow starts, and moves back the arguments that are fields, which gives the semantics of `CALL ... BY REFERENCE`.

**Falling off the end.** A `GO TO` can take the flow out of the paragraph a test case performed, and from there to the end of the program. If test cases were performed by a main paragraph, control would return to the driver in silence, and the remaining cases would not run. So test cases are not performed: a dispatcher reaches each one with `GO TO ... DEPENDING ON` a case number, and each case ends by jumping back to the dispatcher. The last paragraph of the copy is reached only when the flow falls off the end. It records a failed assert for the current case and dispatches the next one.

### 6.5 Interface and internal test cases

A test case either looks at the **interface** of the program (its parameters, the records of its files, the programs it calls, the clock) or at its **interior** (a paragraph executed directly, a `WORKING-STORAGE` field that is not a parameter). The difference matters whenever the program is about to change deeply: interface cases stay valid when the program is rewritten inside or translated to another language, while internal cases pinpoint a defect and support a refactoring for as long as the COBOL lives.

Cobalto classifies each test case and reports the kind in the console, in JUnit and in `results.json`. There is deliberately no third mode and no mandatory tag: the classification is computed from what the case touches. It is syntactic, so a `WORKING-STORAGE` field that a program uses as an output by convention counts as internal.

### 6.6 What in-program mode does not do

- Sections cannot be mock targets, only paragraphs.
- There are no transitive mocks: a `CALL` inside program B cannot be mocked while testing A. B gets its own suite.
- A mocked indexed `READ` behaves like a sequential one. `SORT` input and output procedures (`RETURN`, `RELEASE`) are not mockable.
- `MOCK SQL` leaves the original `EXEC SQL` in the copy, so the copy still goes through the site's precompiler.

## 7. Portable coverage

GnuCOBOL can report coverage through gcov, and Cobalto has a profile for that. Other compilers have their own tools or none. Portable coverage measures the same thing on any of them, by instrumenting the source before it is compiled. It reuses the parser and the rewriter of in-program mode.

**One counter per statement.** Each program gets a table of counters in `WORKING-STORAGE` and an `ADD 1` before every statement, nested ones included. Statement granularity costs the same mechanism as paragraph granularity and gives a line for LCOV and the basis for branches. A paragraph is derived: executed if any of its statements was, and entered as many times as its first statement.

**Local counters, flushed by a `CALL`.** The counters are local to each program. On every exit (`EXIT PROGRAM`, `GOBACK`, or falling off the end) the program calls the collector `CBLTCOV`, which adds the table to its own and zeroes it, so `CANCEL` or an `INITIAL` program loses nothing. A `CALL` per statement was discarded for cost, and `EXTERNAL` counters for the reason given in section 3.1.

**The COBOL carries numbers, the CLI carries names.** The `C` record holds a program, an index and a count. The map from index to paragraph, file and line is built by the CLI while it instruments and saved in `build/cov/map.json`. Putting names in the COBOL would mean text in `WORKING-STORAGE` for every statement.

**Both modes add up.** The counters are numbered from the parse of the original program, so the instrumented copy that external suites call and the in-program copy of the same program report under the same name with the same indexes, and the collector merges them without knowing. A mocked paragraph counts only when the original runs, because its counters sit in the `WHEN OTHER`.

**Branches are derived, not instrumented.** The entries to an explicit branch (the `THEN` and the `ELSE` of an `IF`, a `WHEN` group, a conditional phrase) are those of the first statement of its body, which already has a counter. The implicit branch (an `IF` with no `ELSE`, a `READ` with no `NOT AT END`) is the entries to the statement minus the entries to its explicit branches. Inserting an `ELSE ADD 1` was discarded: it means touching the end of every statement, and the statements that in-program mode rewrites with a mock do not emit that end, so the implicit branch would always read zero inside a mocked `READ`. Only a body that is `NEXT SENTENCE` gets a counter of its own.

**Compound conditions by evaluating twice.** An `IF` with `AND` or `OR`, and each `WHEN` of an `EVALUATE TRUE`, is measured per operand. COBOL offers no way to instrument inside an expression, and rewriting the condition into flags would change the statement. Instead, a tree of nested `IF`s is inserted before the statement. It evaluates the condition again in the same order and with the same short circuit as the compiler, counts each operand as true or false only when the program would have evaluated it, and discards the result. The statement itself is untouched. The cost is evaluating the condition twice, which does not matter in a test run, and the assumption is that a condition has no side effects. When the condition parser is in doubt (an abbreviated condition with `NOT`, more than eight operands, a condition that would not fit in column 72), the statement keeps plain branch coverage. This is operand coverage, not MC/DC: it does not show the independent effect of each operand.

**Remote hosts need nothing special.** The instrumented copies are sources like any other, and the counters come back in the same results file.

What is left out: `DECLARATIVES`, a bare `EXIT`, conditions in `PERFORM UNTIL` and `SEARCH WHEN`, and `ALTER`. A source file with several programs, or with a copybook that cannot be found, is compiled without instrumentation and a warning (`CBLT-W305`).

**Reports.** LCOV, Cobertura XML and SonarQube's generic coverage format, all written from the same map and counters. Sonar has no coverage importer for COBOL, so the generic format is the only documented route.

## 8. Profiles and remote hosts

A profile is a JSON object: command templates for compile and run, the organization and format of the results file, and for remote hosts how to upload, invoke and fetch. The built-in profiles ship inside the package, and a project's `cblt.json` declares only what differs: it can override fields of a built-in profile, extend one under a new name, or define its own. A long script is kept as a file next to the profile rather than as a JSON string.

**Remote profiles.** For a host that is not this machine, the CLI stages everything it would compile into `build/remote/`, adapted as the profile asks: file names in uppercase, the source extension the host's compiler expects, fixed format converted to the host's terminal format or padded to 80 columns, the copybook under the extension the compiler looks for, the library optionally split into one program per file. It also generates a build script and a run script from the profile's templates. Then it uploads, invokes the scripts and fetches the results file.

Two decisions shape this part:

- **Success is a marker in the output, not an exit code.** The generated scripts print `CBLT-BUILD-OK` and `CBLT-RUN-OK`. Exit codes do not survive every remote shell in a usable form.
- **Every step can be done by hand.** `cobalto test --generate-only` stops after staging and writes a manifest. The folder can be carried to the host by any means, the two scripts run there, and the results file and the screen output brought back and read with `cobalto report`. Many hosts that run COBOL have no ssh, or no permission to use it, and this path is how the OpenVMS verification was done.

The profile `remote-sim` runs the same mechanics against a local folder with `sh`. It exists so that the remote path, the fixed-record results file included, is exercised on every run of Cobalto's own tests.

## 9. One model of a run

Everything the CLI reports comes from a single data structure built once per run: suites, test cases with their status and kind, asserts with expected and actual values, the output of each case, warnings, totals, and coverage. The console, `junit.xml`, `sonar-tests.xml` and `build/results.json` are renderings of it.

A run that stops with an error before it reads any results still has a model: no suites, `ok` false and the error. It is rendered to the same files, so a reader that skips the exit code never takes the reports of an earlier run for this one. The coverage reports are left alone: they describe the last run with coverage, and a run that stopped measured nothing.

This replaced an earlier arrangement in which each consumer formatted its own view and other tools read the console text. Two consumers showed why that does not hold: the VS Code extension and `cobalto suggest` both need exact expected and actual values, and text meant for people changes.

The contracts that other programs can rely on:

- `--json` on `test`, `report`, `parse`, `list` and `profiles` writes JSON to standard output and sends the console to standard error. A fatal error is also JSON.
- Every JSON output and every JSON file left in `build/` carries `schema`, the version of the format, and `cobalto`, the version of the CLI. The VS Code extension does not use a file whose schema is newer than the one it knows, instead of misreading it.
- Exit code 0 means everything passed, 1 means failures or errors in the tests, 2 means the CLI could not do what was asked (configuration, DSL syntax, compile error).
- Every message has a stable code, `CBLT-Ennn` or `CBLT-Wnnn`, from one catalog, and every code is exercised by a scenario of Cobalto's own tests.

JUnit has no place for some of this, so the kind of a test case and the expected and actual values of its first failed assert go in properties of the test case. One JUnit test case is one `TESTCASE`, not one assert.

## 10. Debugging

Debugging works with GnuCOBOL, which compiles COBOL to C. `cobalto debug --suite X` builds one suite with debug information and leaves files that describe it: the map from generated lines to source lines, the layout of every data item (level, picture, usage, offset within its record), and a `launch.json`. The VS Code extension does the rest through a proxy in front of `lldb-dap`.

- **A proxy, not a debug adapter.** `lldb-dap` already handles breakpoints, the stack, threads and memory on the generated C. What is missing is translation, so the extension sits between the editor and `lldb-dap` and rewrites messages. The proxy does not care about the transport, so the same class serves inside VS Code and over standard input in the headless checks.
- **Layout from the compiler's own listing.** Field offsets come from the symbol listing that `cobc` writes, not from a data parser of Cobalto's. It is exact by construction. A group whose children do not add up to its size is marked unreliable and shown the simpler way.
- **Values read from memory.** With the layout, the proxy reads a whole record once per stop and formats each field from its picture and usage. Changing a value encodes it with the same table and writes it back. When the adapter has no memory requests, as `lldb-dap` 18 does not, the proxy falls back to the debugger's memory commands.
- **Stepping by repetition.** A COBOL statement is several lines of C. The proxy repeats the step until the top frame leaves the C and the statement it started from. A table of addresses would have meant reading DWARF.
- **Conditions in COBOL.** A breakpoint condition written in COBOL is kept by the proxy. The breakpoint is sent without it, and at each stop the proxy reads the records, evaluates the condition and continues silently if it is false.
- **Breakpoints follow the line map.** A breakpoint set in a `.cblt`, or in the original program under an in-program suite, is moved to the generated source that is actually compiled.

The extension contains no test logic. It lists suites with `cobalto list --json` and profiles with `cobalto profiles --json`, runs `cobalto test`, and reads the `junit.xml`, the `lcov.info` and the coverage map that the run leaves. Anything it shows can be reproduced from a terminal.

## 11. AI-assisted drafts

`cobalto suggest` asks a language model for a suite and checks the answer by running it.

- **The model writes the DSL, not COBOL.** The suite it proposes is expanded and compiled like any other, so it gets mocks per test case, coverage and mapped error messages for free. A generated suite is indistinguishable from one written by hand.
- **Feedback is the tool's output, not the model's opinion.** Each round is run with coverage, and what goes back to the model is what Cobalto reported: compile errors at their `.cblt` line, failures with expected and actual, statements not executed. Rounds are scored on that and the best one is kept.
- **Characterization tests.** When a case fails, the expected value is corrected to what the program produces, with a comment that keeps the original. This protects current behavior, which is what a refactoring, a change of compiler or a migration needs, and stops the model from inventing business rules. The cost is stated plainly: a real defect ends up documented as behavior, marked for review, not flagged as a defect. The result is a draft for a person to review.
- **What leaves the machine is explicit.** The request carries the program source with its copybooks, the parser's summary, the existing suite if there is one, and the output of each round. Every request is saved, and `--dry-run` builds it without sending it. Whether a source may be sent to a provider is for the owner of the code to decide, not for the tool.
- **No dependency.** One backend talks to an HTTP API with the standard library, the other pipes the prompt to any command-line client.

## 12. Prior art

Cobalto took ideas from earlier open source COBOL unit testing projects and no code from any of them. The parser, the rewriter, the COBOL library, the CLI and the extension were written from scratch.

The largest debt is to [cobol-unit-test](https://github.com/neopragma/cobol-unit-test). Testing inside a copy of the program, with access to its `WORKING-STORAGE` and its paragraphs, is its idea, and so is the shape of the DSL: `TESTSUITE`, `TESTCASE`, `EXPECT`, `MOCK`, `VERIFY`, with ordinary COBOL in between. It is licensed under GPL-3.0, so only ideas were taken: architecture and the form of a syntax, not code.

Where Cobalto chose differently, as that project stood when it was studied in November 2026:

- The rewriter lives in the CLI, on top of a parser, instead of in a precompiler written in COBOL. That is what allows multi-line statements, `READ INTO` and `WRITE FROM`, and inserted terminators.
- A mock is active per test case, not for the whole suite.
- The original statement stays in the copy even where a mock exists.
- A test case, not an assert, is the unit reported, and reports are written for CI.
- Mocks cover `EXEC SQL` and the clock as well as paragraphs, calls and files.

## 13. Open decisions

- **Buffer and log sizes** (section 3.4) are fixed. They could become fields of the profile, at the price of generating the copybook.
- **Numeric precision.** Three decimals cover money in most systems. Amounts with more decimals would need an assert with a larger scale or a tolerance.
- **A suite that aborts loses its asserts** (section 4). Running each suite in its own process would fix it, at the price of one driver per suite.
- **Negated numeric checks** are rejected by the DSL. Supporting them means new assert programs in the core, and with that a new round of verification on every compiler.
- **Coverage is per run.** Counters are not attributed to the suite or the test case that executed the statement.
- **Compilers.** The core is written to the 85 standard and checked against strict dialects, but a compiler counts as supported only once the suites have been compiled and run with it. The README lists which ones have.
