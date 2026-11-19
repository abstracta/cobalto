# Interface tests: regression suite

Regression suite for interface tests: `RUN`, the rewrite of `STOP RUN` / `GOBACK` / `EXIT PROGRAM` with one guard per paragraph, `VERIFY STOP`, the classification of test cases (interface or internal) and the deterministic characterization of `suggest`.

- `src/GUARD.cbl`: `STOP RUN` inside an `IF` in the main paragraph and `GOBACK` inside an `IF` in an inner paragraph. `tests/GUARD.cblt`: four test cases, one with a name of exactly 60 characters.
- `src/SECTS.cbl`: the entry is a `SECTION`; a `STOP RUN` at the start followed by multi-line statements with conditional phrases (`READ ... AT END`, inline `PERFORM`) and by a `READ` that the test cases simulate; a second section with two paragraphs (fall-through from one to the other) and a `GOBACK` inside an `IF`. `tests/SECTS.cblt`: five test cases, including `STOP` inside a mocked paragraph and the documented limit of the fall-through between paragraphs.
- `src/FALLS.cbl`: a main flow that falls through from one paragraph to the next without `PERFORM`. `tests/FALLS.cblt`: pins that `RUN` executes only the entry paragraph and that `PERFORM ... THRU` covers the fall-through.
- None of them has any business meaning; that is why they do not live in `examples/src/` and do not change the reference totals.
- `selftest.py`: runs these suites with coverage, the two interface suites of the main project (`--local-only` skips them so that `examples/build` is not touched), two invalid suites that `RUN` must reject, and `suggest.fill_expected` with a fixed run result; it checks what the CLI does not assert by itself (classification in the JUnit, number of guards in each copy, line width, what is replaced and what is not). 27 checks.

```bash
python3 tests/interface/selftest.py
```
