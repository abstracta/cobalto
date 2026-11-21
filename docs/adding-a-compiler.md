# Adding a compiler

Cobalto reaches a new compiler through a **profile**: a JSON object that says how to compile, link and run there, and how the results file comes back. The COBOL core and the CLI do not change. This guide takes a profile from a first try in your own project to a built-in profile that ships with Cobalto.

You do not need to modify Cobalto to try a compiler. Steps 1 to 4 happen in a project of yours. Only step 5 is a contribution, and a report of what you found is useful even without it.

Before starting, read ["Profiles"](reference.md#profiles) in the reference for the meaning of every field, and ["Remote profiles"](reference.md#remote-profiles) if the compiler runs on another machine.

## What "verified" means

A compiler is listed as verified when the example project has been compiled and run with it, and the results match the reference or the differences are explained. Passing the syntax check of GnuCOBOL's dialects is not verification: it is the approximation Cobalto uses while nobody has run the real compiler.

The reference is in ["Example programs"](reference.md#example-programs): 105 test cases, 415 asserts, 2 intentional failures, 6 skipped, 0 errors. A compiler with different arithmetic or binary field rules can legitimately fail more cases. GnuCOBOL's own IBM and Micro Focus dialects do, and the reference says which cases and why. What matters is that every difference is understood.

## 1. Compile the core alone

The core is two files in [`src/cobalto/lib/`](../src/cobalto/lib/): `CBLTLIB.cbl`, with eleven small programs, and the copybook `CBLTCTX.cpy`. Compile `CBLTLIB.cbl` with your compiler by hand before writing any profile, with the copybook where the compiler looks for it.

If it does not compile cleanly, stop here and [open an issue](../CONTRIBUTING.md#reporting-a-problem) with the compiler's messages. The core is meant to be standard COBOL 85 in fixed format, so a message from a compiler that follows the standard is a defect in Cobalto.

Things that have needed attention on real compilers so far:

- **Source format.** The core is fixed format, with the sequence area in columns 1 to 6. A compiler that expects another layout needs the profile to convert it (`source_format`, `pad80`).
- **Copybook name and extension.** `COPY CBLTCTX` has to find the copybook. Some compilers want a given extension (`copybook_ext`) or uppercase names (`upper_names`).
- **One program per file.** `CBLTLIB.cbl` holds several programs, each closed with `END PROGRAM`. A compiler that takes one program per file needs `split_lib`.

## 2. Write the profile in your project

Add the profile under `profiles` in the `cblt.json` of a project. Start in a copy of [`examples/`](../examples/), so that there is something to run.

A local profile, for a compiler on the machine where the CLI runs:

```json
{
  "profiles": {
    "acme-cobol": {
      "description": "ACME COBOL 1.0 on Linux. Not verified yet.",
      "compile": "acmecob -o {exe} -I {lib} {incl} {driver} {lib}/CBLTLIB.cbl {tests} {sources}",
      "run": "{exe}",
      "results_org": "LINE SEQUENTIAL",
      "results_format": "lines",
      "results_path": "build/cblt-results.txt"
    }
  }
}
```

| Field | What to decide |
|---|---|
| `compile` | One command that compiles and links everything into `{exe}`: the driver, the library, the suites and the programs under test. If the compiler needs several steps, chain them with `&&` or keep a script in a file with `{"file": "NAME"}` |
| `run` | How to start the executable. Usually `{exe}` |
| `results_org` | The `ORGANIZATION` the driver declares for its results file: `LINE SEQUENTIAL` where the compiler has it, `SEQUENTIAL` otherwise |
| `results_format` | How the CLI reads that file: `lines` for text lines, `fixed200` for 200-byte records with no separator |
| `results_path` | What goes in the `ASSIGN TO` of the driver: a path, or a logical name that the `run` command maps to a file |
| `error_regex` | Optional. A regular expression with the groups `file`, `line` and `msg` that matches a compile error, so that Cobalto reports it at the line of the `.cblt` that caused it, also in the `details` of the JSON error object. Without it, the compiler's output is shown as is, and the JSON error object carries it in `output` |
| `pre`, `post` | Optional commands before running and after it |

If the compiler runs on another machine, start from a remote profile with `extends` and change what differs. `remote-sim` is the one to read first: it does everything a remote profile does against a local folder, and its two script templates are short.

```json
{
  "profiles": {
    "acme-host": {
      "extends": "remote-sim",
      "description": "ACME COBOL on a remote host. Not verified yet.",
      "remote": "ssh {host}",
      "remote_dir": "/tmp/cobalto",
      "upload": "scp -q {upload_files} {host}:{remote_dir}/",
      "invoke": "cd {remote_dir} && sh {script}",
      "fetch": "scp -q {host}:{remote_dir}/CBLT_RESULTS.DAT {results_local}",
      "compile": { "file": "acme-host.build.sh" },
      "run": { "file": "acme-host.run.sh" }
    }
  }
}
```

The build script has to print `CBLT-BUILD-OK` when it succeeds and the run script `CBLT-RUN-OK`: Cobalto looks for those markers in the output, because an exit code does not survive every remote shell. In a template file, a literal brace is written twice. The folder named in `remote_dir` has to exist on the host. This example is a starting point: the ssh transport has only been exercised through the local simulator so far, so expect to adjust it.

**A host with no ssh is fine.** `cobalto test --profile NAME --generate-only` stages the sources and the two scripts in `build/remote/`. Carry that folder to the host by whatever means you have, run the scripts there, bring back the results file and, if you can, the screen output, and read them with `cobalto report --results FILE --output SCREEN`. That is how the OpenVMS verification was done.

## 3. Get one suite through

Work from the smallest thing that can fail, with `-v` to see every command:

```bash
cobalto profiles
cobalto test --profile acme-cobol --filter TSTDISC --no-run -v
cobalto test --profile acme-cobol --filter TSTDISC -v
```

The first command confirms the profile is read. The second compiles and links without running. The third runs `DISCOUNT.cblt` and its interface suite: 6 test cases, 17 asserts, 1 intentional failure and 1 skipped, with exit code 1 because of that failure.

If the run ends with `CBLT-E300`, the executable did not leave a results file where `results_path` says. If the totals are right and the values look shifted or cut, `results_format` does not match what the compiler wrote.

## 4. Run everything

```bash
cobalto test --profile acme-cobol --coverage
```

Compare the totals and the test cases that do not pass with the reference. For each difference, find the reason: it is usually a documented difference between compilers (rounding, the size of binary fields, truncation), and it is exactly what Cobalto exists to show. A suite that aborts, a case that fails with no visible reason or a coverage table that does not add up is worth an issue.

Then try what the example project does not cover on its own:

- `--coverage` off and on give the same test results.
- An in-program suite with a mocked file (`INVOICE.cblt`) and one with a paragraph closed by periods (`LEGACY.cblt`) pass. They exercise the rewriter, which is where a compiler is most likely to disagree with Cobalto's parser.
- A compile error in a `.cblt` is reported at its line, if you wrote an `error_regex`.

## 5. Contribute it

Whether or not you send the profile, please report what you found with the "Compiler report" issue template: a compiler that works, one that needs a change in the core and one that cannot work are all worth knowing about.

To make the profile built-in, open a pull request with:

1. **The profile**, as `src/cobalto/profiles/NAME.json`, with script templates next to it if it uses them. Name it after the compiler and, if it matters, the platform, in lowercase with hyphens: `vms-vsi-cobol`, `gnucobol-ibm`.
2. **A `description` that says what was verified**: the exact version of the compiler and of the operating system, and what was not tried. Look at the existing profiles for the tone. "Verified" with no version is not accepted.
3. **The compiler in the tables**: the compilers table of the [README](../README.md#status) and the profiles table of the [reference](reference.md#profiles).
4. **The evidence in the pull request**: the totals line of `cobalto test`, the list of cases that differ from the reference with the reason for each, and the compiler's version banner.

Do not paste source code or build output that belongs to someone else, and do not describe a private environment: host names, user names, paths and site-specific commands stay out. The example project is synthetic precisely so that results on it can be shared.

A profile for a compiler that CI cannot run, which is every commercial one, is not added to the example regression in `tests/examples/`. It is covered by the unit test that checks every built-in profile is well formed, and by your report. That is why the description has to be precise about what a person verified by hand.

If the compiler needed a change in the core or in the generated COBOL, send that as a separate pull request. Such a change has to keep `python3 tests/run.py` green, the dialects layer included, and it affects every other compiler, so it gets a closer review.
