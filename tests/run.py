#!/usr/bin/env python3
"""Runs Cobalto's own tests, one layer after another.

    python3 tests/run.py                  (every layer of the CLI)
    python3 tests/run.py unit cli         (only those)
    python3 tests/run.py --extension      (also the VS Code extension: lint and unit tests)
    python3 tests/run.py --list

It ends with 0 when every layer it ran passed. See tests/README.md for
what each layer covers. Needs Python 3.9+; every layer but "unit" needs
GnuCOBOL (cobc), and --extension needs Node.js with `npm install` done in
vscode-cobalto/.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# name -> (what it is, command, folder it runs in)
LAYERS = {
    "unit": ("unit tests of the CLI modules", [PY, "-m", "unittest", "discover", "-s", "tests/unit"], ROOT),
    "cli": ("the CLI end to end: messages and outputs", [PY, "tests/cli/selftest.py"], ROOT),
    "interface": ("interface tests and the rewrite of STOP RUN", [PY, "tests/interface/selftest.py"], ROOT),
    "examples": ("the example project with each profile", [PY, "tests/examples/selftest.py"], ROOT),
    "dialects": ("syntax in the strict dialects", [PY, "tests/dialects/selftest.py"], ROOT),
}
EXTENSION = {
    "extension-lint": ("the extension: lint", ["npm", "run", "--silent", "lint"], os.path.join(ROOT, "vscode-cobalto")),
    "extension-unit": ("the extension: unit tests", ["npm", "test", "--silent"], os.path.join(ROOT, "vscode-cobalto")),
}


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    layers = dict(LAYERS, **EXTENSION)
    if "--list" in sys.argv:
        for name, (what, _, _) in layers.items():
            print(f"  {name:15s} {what}")
        return 0
    unknown = [n for n in names if n not in layers]
    if unknown:
        print(f"unknown layer(s): {', '.join(unknown)}; available: {', '.join(layers)}")
        return 2
    chosen = names or list(LAYERS) + (list(EXTENSION) if "--extension" in sys.argv else [])
    failed = []
    for name in chosen:
        what, command, folder = layers[name]
        print(f"== {name}: {what}", flush=True)
        start = time.time()
        r = subprocess.run(command, cwd=folder, capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()
        # the whole output when it fails, its last line when it passes
        for line in tail if r.returncode != 0 else tail[-1:]:
            print(f"   {line}")
        print(f"   {'passed' if r.returncode == 0 else f'FAILED (exit {r.returncode})'} in {time.time() - start:.0f} s\n", flush=True)
        if r.returncode != 0:
            failed.append(name)
    print(f"{len(chosen) - len(failed)} of {len(chosen)} layers passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
