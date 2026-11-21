# Developing the extension

This file is for people who work on the extension. To use it, see the [README](README.md).

## Build

```bash
npm install && npm run compile
```

`npm run watch` recompiles on save and `npm run lint` runs ESLint. `npm test` runs the unit tests in `src/test/unit/`, which need no compiler, debugger or VS Code. `package.json` declares the contributions; the code is in `src/`. No runtime dependencies.

| Module | What it holds |
|---|---|
| `extension.ts` | Activation: it wires everything below |
| `project.ts`, `cli-path.ts`, `cli-result.ts` | Finding the projects and the `cobalto` executable, running the CLI and reading how it ended |
| `tests.ts`, `suites.ts`, `junit.ts` | Test Explorer: the suites as the CLI lists them, runs and results |
| `coverage.ts`, `lcov.ts`, `cov-map.ts` | Coverage in the gutter and in the Test Coverage view, from `build/lcov.info` and the branch labels of `build/cov/map.json` |
| `profile.ts` | Compiler profile selector |
| `debug.ts`, `hover.ts` | Debug configuration, adapter factory and hover expressions |
| `dap/proxy.ts` | The DAP proxy: it only routes messages to the modules below |
| `dap/channel.ts`, `dap/protocol.ts` | Connections to the client and to `lldb-dap`, and DAP framing |
| `dap/session.ts` | What a session knows once launched: options and the maps of the suite |
| `dap/stack.ts` | Frames shown at their COBOL source, one step per statement |
| `dap/breakpoints.ts` | Breakpoints moved to the generated source, conditions written in COBOL |
| `dap/records.ts`, `dap/variables.ts` | Reading and writing COBOL data in the memory of the program, and showing it as variables |
| `dap/layout.ts`, `dap/cobol-map.ts`, `dap/line-map.ts`, `dap/schema.ts` | Readers of the files `cobalto debug` leaves in `build/` |

To install a local build in VS Code:

```bash
npm run package
```

```bash
code --install-extension vscode-cobalto-0.1.1.vsix
```

VS Code does not replace an installed extension with a package of the same version: uninstall it first, or raise the version. After installing from a `.vsix`, reload the open windows (Developer: Reload Window).

## How debugging works

`cobalto debug --suite X` compiles with `cobc -g -fsource-location -save-temps` from `build/` and leaves, besides the executable, `build/X.lines.json` (generated line → source file and line), `build/X.layout.json` (every data item of each program with level, PIC, usage, `OCCURS`, `REDEFINES` and offset within its 01, taken from the symbol listing of `cobc -ftsymbols`) and cobc's `build/<program>.c.l.h` files, where each COBOL field is a `static cob_u8_t b_NNN[len]; /* NAME */` and each descriptor a `static cob_field f_NN = {size, b_NNN + offset, &a_K}; /* NAME */`. The proxy (`src/dap/proxy.ts`) reads those files when it receives `launch` and:

- in `variables`, replaces `b_NNN` with the COBOL name; with the layout, it evaluates once the address of the 01 (or of the pointer of the `LINKAGE` parameter), reads the whole record with `readMemory` (or, with an `lldb-dap` that does not have that request, such as version 18, with lldb's `memory read` command) and formats each field in the extension according to its PIC and usage (`src/dap/layout.ts`: DISPLAY with overpunch or separate sign, COMP-3, COMP, COMP-5, COMP-1/2, POINTER, INDEX, edited fields and groups as text), with the subordinates and the occurrences as children; without a layout for an 01, it asks lldb-dap for `(char*)cob_get_field_str_buffered(&f_NN)`. The `LINKAGE` parameters are named from the `linkage for` comment of the `.c` (cobc 3.2) or from the `USING` list of the `.i` (cobc 3.1);
- in `evaluate`, resolves a COBOL name with subscripts on the layout and formats it the same way (it serves hover, watch and console); a group is returned expandable;
- in `setVariable`, encodes the new value with the same table and writes it with `writeMemory`;
- in `setBreakpoints`, keeps the conditions written in COBOL and sends the breakpoint without them; on each stop with `hitBreakpointIds` it reads the records the condition needs, evaluates it and, if it is false, does `continue` without telling the client;
- in `next`, `stepIn` and `stepOut`, repeats the step while the top frame is in a `.c` or on the same COBOL statement it started from (cobc interleaves `#line` directives of the `.c` between statements);
- in `stackTrace`, marks as `subtle` the frames in `.c` or without a source and maps the frames of `build/X.cbl` to the `.cblt` or to the original program;
- in `setBreakpoints`, moves the breakpoints of a `.cblt` or of an original program to the matching lines of the generated sources, keeping the union with the breakpoints set directly in them.

A group with `SYNC` and padding (its children do not add up to its size) is marked in the layout and falls back to the earlier mode: only the fields with a descriptor.

## Verification

Headless, against the proxy over stdio (like any DAP client):

```bash
cd ../examples && cobalto debug --suite TSTINV
```

```bash
node out/test/verify-dap.js ../examples TSTINV
```

It checks `initialize`, `launch`, breakpoints in `build/TSTINV.cbl`, `src/DISCOUNT.cbl` and `tests/INVOICE.cblt`, a false COBOL condition that does not stop and a true one that does, the stack with a COBOL source, `Globals` with `WS-AMOUNT` and without `b_NNN`, the group `WS-CUST` expandable with its three subfields and offsets, `setVariable` on a subfield and on an 01, `evaluate` with subscripts (`CBLT-MODE(2)`, out of range rejected, `CBLT-LOG-NR(1)` in `LINKAGE`), `next` and `stepOut` landing on COBOL lines, `Locals` with the `LINKAGE` parameters of DISCOUNT.

On Linux, the same inside a Docker container (Ubuntu 24.04, GnuCOBOL 3.1.2, lldb-dap 18, Node 18; it needs `--cap-add=SYS_PTRACE`): it builds the image, copies the project and the compiled extension and runs the suites, `cobalto debug` and `verify-dap`:

```bash
test/linux/run.sh
```

Formatting and encoding of fields (`src/dap/layout.ts`), against GnuCOBOL: a generated program with DISPLAY with overpunch and separate sign, COMP-3, COMP, COMP-5, COMP-1/2, edited fields, `OCCURS` and a group writes its record to a file; the test takes the layout from the same symbol listing `cobalto debug` uses, formats those bytes and encodes each value again expecting the same bytes. Also references with subscripts, exact decimals, rejections of `setVariable` and the grammar of the conditions (`AND` before `OR`, `NOT`, parentheses, `EQUAL TO`, `NOT GREATER THAN`, space padding):

```bash
node out/test/verify-layout.js
```

Inside an actual VS Code (it opens the installed VS Code with the extension in development mode on the project and runs `src/test/suite` in the extension host; the script looks for VS Code in `/Applications` on macOS, and the `COBALTO_VSCODE` variable sets another executable):

```bash
node out/test/run-in-vscode.js ../examples
```

It checks the activation, the Test Explorer (suites, test cases, `IGNORE`, location, 105 test cases with 2 failures and 6 skipped after running them), the list of profiles taken from the CLI, a run the CLI cannot start (every test case shows the error instead of the earlier results), the coverage (`LOANCALC.cbl` at 100%, `DAYCLOSE.cbl` with statements not executed), a `cobalto` debug session with a breakpoint in `tests/INVOICE.cblt` (stop, stack, `Globals` with COBOL names, hover, Watch and `next`) and a second one on `TSTCLOSE`: a COBOL condition on an occurrence (`WS-MOV-AMOUNT(3) > 50000`) that is false in one test case and true in the next, `WS-MOVEMENTS` → `WS-MOV` with 50 occurrences → `WS-MOV(3)` expanded, hover and Watch with subscripts, `setVariable` on the occurrence, Watch of a signed `COMP` and *step into* the program. A third session, on `TSTBATCH`, sets a breakpoint on the `PERFORM 3000-END` of the failing test case, *steps into* down to the `MOVE WS-LINE-COUNT TO WS-T-COUNT` of `2600-WRITE-TRAILER` in `src/LOANBTCH.cbl` and watches `WS-LINE-COUNT` (3) and `WS-DEBIT-COUNT` (2). It leaves the detail in `build/vscode-verify.log` of the project.

## Publishing

The [Publish VS Code extension](../.github/workflows/publish.yml) workflow publishes to the Visual Studio Marketplace and to [Open VSX](https://open-vsx.org/extension/abstracta/vscode-cobalto) with Trusted Publishing, so no token is involved. Raise `version` in `package.json` and `package-lock.json`, add the entry to [CHANGELOG.md](CHANGELOG.md), merge to `main` and start the workflow by hand from the Actions tab. Both registries reject a version that is already published. The two jobs are independent: if one fails, run that job again from the same run.
