# Cobalto DSL reference

Everything that is not a DSL keyword is plain COBOL and is copied as is to the generated program.

Contents: [Structure](#structure) · [Assertions](#assertions) · [Two suite modes](#two-suite-modes) · [Mocks](#mocks-only-with-program) · [Count verifications](#count-verifications-only-with-program) · [RUN](#run-executing-the-original-flow) · [Examples](#examples) · [Known limits](#known-limits)

## Structure

| Keyword | What it does |
|---|---|
| `TESTSUITE id 'desc'` | First line. `id` is the name of the generated program: up to 30 characters (letters, digits and hyphens, starting with a letter), no spaces, by convention with the project's test prefix (`TST` by default) |
| `PROGRAM name` / `PROGRAM "path.cbl"` | Turns on in-program mode; the name is searched by `PROGRAM-ID` or file name in `sources` |
| `WORKING-STORAGE SECTION.` | The suite's own fields; `COPY` is allowed |
| `BEFORE-EACH` … `END-BEFORE` | COBOL that runs before each case |
| `AFTER-EACH` … `END-AFTER` | COBOL that runs after each case |
| `TESTCASE 'desc'` | One test case; it is a testcase in the JUnit report |
| `IGNORE` | Marks the next `TESTCASE` as skipped |

Columns: keywords in column 8, the COBOL of the cases from column 12, nothing after column 72, an asterisk in column 7 for comments. The statements inside `TESTCASE`, `BEFORE-EACH`, `AFTER-EACH` and `MOCK` take no final period. The `WORKING-STORAGE` declarations do take a period, as in any program.

## Assertions

| Form | Purpose |
|---|---|
| `EXPECT field TO BE 'x'` / `TO BE identifier` | Alphanumeric equality (ignores trailing spaces) |
| `EXPECT field NOT TO BE 'x'` | Alphanumeric inequality. `NOT` is not accepted with the numeric forms or with `CONTAIN`: write the opposite check |
| `EXPECT field TO BE NUMERIC n` | Numeric equality by value (works for `COMP-3`, binary and display) |
| `EXPECT field TO BE GREATER THAN expr` / `LESS THAN expr` | Numeric comparison; `expr` may be arithmetic |
| `EXPECT field TO BE BETWEEN a AND b` | Inclusive range |
| `EXPECT condition-88 TO BE TRUE` / `FALSE` | Level 88 condition |
| `EXPECT field TO BE SPACES` / `ZEROS` | Figurative constants |
| `EXPECT field TO CONTAIN 'x'` | Substring |

A subscripted field is written without a space before the parenthesis: `EXPECT T-ID(1) TO BE 'x'`. On a numeric field use only `NUMERIC`, `GREATER THAN`, `LESS THAN`, `BETWEEN` and `ZEROS`. Numeric comparison works with a fixed scale of 3 decimals. Each `EXPECT` records its own line as the message of the failure.

## Two suite modes

| Mode | How it is declared | What it tests |
|---|---|---|
| External | suite without `PROGRAM` | a whole program through its `LINKAGE`, with `CALL "PROG" USING ...` |
| In-program | suite with `PROGRAM` | a copy of the program with the cases injected: `PERFORM` of any paragraph, access to its `WORKING-STORAGE`, `MOCK`, `VERIFY` and `RUN` |

In in-program mode the program's `LINKAGE` items move to `WORKING-STORAGE` in the copy, so they are set with `MOVE`. The original program is still compiled separately, so suites of both modes can coexist on the same program.

External mode suits a subprogram whose whole logic runs in one `CALL` and that touches no files, SQL or other programs. A batch program without parameters, or one with files, needs in-program mode to be able to mock what is external.

## Mocks (only with `PROGRAM`)

| Form | What it replaces |
|---|---|
| `MOCK PARAGRAPH name` … `END-MOCK` | The body of the paragraph (empty is the same as `CONTINUE`) |
| `MOCK CALL 'PROG'` / `MOCK CALL identifier` … `END-MOCK` | The `CALL`s to that program; the block can set the parameters, which are fields of the program |
| `MOCK FILE file` … `END-MOCK` | `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE` and `START` on that file |
| `MOCK SQL ['text']` … `END-MOCK` | The `EXEC SQL` statements (all of them, or those that contain the text); the block sets the host variables and `SQLCODE` |
| `MOCK CLOCK` … `END-MOCK` | The `ACCEPT ... FROM DATE/DAY/TIME` statements, with lines `DATE 'yymmdd'`, `DATE YYYYMMDD '...'`, `DAY 'yyddd'`, `DAY YYYYDDD '...'`, `DAY-OF-WEEK 'd'`, `TIME 'hhmmsscc'` |

Inside `MOCK FILE` go the blocks `ON READ`, `ON READ AT END`, `ON WRITE`, `ON REWRITE`, `ON DELETE`, `ON START`, `ON OPEN` and `ON CLOSE`. Without blocks, every operation is a no-op with `FILE STATUS` "00" and `READ` returns end of file.

- In `ON READ` the block sets the record of the `FD` (for example `MOVE ... TO CUST-REC`). Cobalto takes care of the `INTO`, of the `FILE STATUS` and of executing the original `AT END` or `NOT AT END`.
- `CBLT-READ-COUNT` is 1 on the first read of the case, 2 on the second, and so on. `SET CBLT-AT-END TO TRUE` returns end of file.
- In `ON WRITE` the record already has the `FROM` applied; copy it to a `T-*` field to check it afterwards. `CBLT-WRITE-COUNT` counts the writes.
- Inside a `MOCK CALL`, `CBLT-CALL-COUNT` is 1 on the first call of the case to that program, 2 on the second, and so on.
- `EXPECT` is allowed inside a `MOCK`, for example to check the parameters a `CALL` receives.

A `MOCK` applies only to the `TESTCASE` that declares it, or to all of them if it is in `BEFORE-EACH`. A `MOCK` in `BEFORE-EACH` that takes its data from a `T-*` table (with `OCCURS`) that each case fills avoids repeating the block in every case. When each case starts, every mock is turned off and the counters go back to zero.

## Count verifications (only with `PROGRAM`)

`VERIFY PARAGRAPH name`, `VERIFY CALL 'PROG'`, `VERIFY READ|WRITE|REWRITE|DELETE|START|OPEN|CLOSE file`, `VERIFY SQL`, `VERIFY CLOCK` and `VERIFY STOP`, followed by a count form:

`HAPPENED ONCE` · `HAPPENED n TIMES` · `NEVER HAPPENED` · `HAPPENED AT LEAST n TIMES` · `HAPPENED NO MORE THAN n TIMES`

`VERIFY STOP` counts the `STOP RUN`, `GOBACK` and `EXIT PROGRAM` statements reached in the case. `EXPECT CBLT-STOPPED TO BE TRUE` checks the same thing.

## RUN: executing the original flow

- `RUN` executes the whole original flow through its entry (the first paragraph or section of the `PROCEDURE DIVISION`).
- `RUN USING a b c` sets by position the items of `PROCEDURE DIVISION USING` and on return copies back those that are fields, like a `CALL ... BY REFERENCE`. A literal or a figurative constant only goes in.
- `RUN` executes only the entry. If the main flow falls from one paragraph into the next without a `PERFORM`, use `PERFORM entry THRU last`.

## Examples

External suite on a pure-logic subprogram:

```cobol
       TESTSUITE TSTDISC 'Discounts by amount'

       WORKING-STORAGE SECTION.
       01  T-AMOUNT                  PIC 9(7)V99.
       01  T-RESULT                  PIC 9(7)V99.
       01  T-CATEGORY                PIC X(10).

       BEFORE-EACH
           MOVE ZERO TO T-RESULT
       END-BEFORE

       TESTCASE 'premium amount gets 20%'
           MOVE 2000 TO T-AMOUNT
           CALL "DISCOUNT" USING T-AMOUNT T-RESULT T-CATEGORY
           EXPECT T-RESULT TO BE NUMERIC 1600
           EXPECT T-CATEGORY TO BE 'PREMIUM'
```

Interface case on a batch program with files and a `CALL`:

```cobol
       TESTSUITE TSTIFACE 'INVOICE through its interface'
       PROGRAM INVOICE

       WORKING-STORAGE SECTION.
       01  T-LINE                    PIC X(80).

       TESTCASE 'one customer: writes its line and ends'
           MOCK FILE CUST-FILE
               ON READ
                   EVALUATE CBLT-READ-COUNT
                       WHEN 1
                           MOVE "C001ACME      000200000" TO CUST-REC
                       WHEN OTHER
                           SET CBLT-AT-END TO TRUE
                   END-EVALUATE
           END-MOCK
           MOCK FILE REPORT-FILE
               ON WRITE
                   IF CBLT-WRITE-COUNT = 2
                       MOVE REPORT-REC TO T-LINE
                   END-IF
           END-MOCK
           RUN
           EXPECT T-LINE TO CONTAIN 'ACME'
           VERIFY READ CUST-FILE HAPPENED 2 TIMES
           VERIFY STOP HAPPENED ONCE
```

Internal case on a paragraph, with the `CALL` mocked:

```cobol
       TESTCASE 'the net amount is what DISCOUNT returns'
           MOCK CALL 'DISCOUNT'
               MOVE 999 TO WS-NET
           END-MOCK
           PERFORM 2100-CALC
           EXPECT WS-NET TO BE NUMERIC 999
           VERIFY CALL 'DISCOUNT' HAPPENED ONCE
```

## Known limits

- A paragraph that uses `NEXT SENTENCE` cannot be mocked (`CBLT-E405`). Only paragraphs are mocked, not sections.
- Nested programs or several programs per file do not support in-program mode (`CBLT-E406`).
- There are no transitive mocks: a `CALL` inside B while A is under test is not mocked; B is tested with its own suite.
- After a `STOP` the protection is per paragraph: the calling paragraph goes on with whatever it has after the `PERFORM` that stopped. That is why an interface case looks at what came out, not at what happened after the `STOP`.
- `MOCK SQL` leaves the original `EXEC SQL` in the branch without a mock, so the copy still needs the project's precompiler, and `SQLCA` must be declared by the program.
- The classification of cases is syntactic: a `WORKING-STORAGE` field that the program uses as an output by convention counts as internal.
- Reserved names that Cobalto adds and that should not be reused: everything that starts with `CBLT-`.
- To diagnose a mock that cannot find its paragraph, file or `CALL`: `cobalto parse src/PROGRAM.cbl`.
