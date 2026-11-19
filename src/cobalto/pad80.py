"""pad80 - converts fixed-format COBOL source files to 80-column records.

  python3 -m cobalto.pad80 FILE... --out DIR [--upper] [--ext .CBL]

Each line ends up exactly 80 characters long (padded with spaces on the
right), with no tabs, no previous trailing spaces, terminated by LF. VSI
COBOL with /ANSI_FORMAT reads 80-column "cards": 1-6 sequence, 7
indicator, 8-72 code, 73-80 identification. A line longer than 80
columns is an error (code would be lost); text in 73-80 only warns
because the compiler ignores it. No dependencies: the Cobalto CLI uses
it, and it can also be run by hand on a kit.
"""
import argparse, os, sys


class Pad80Error(Exception):
    pass


def pad80_text(text, name="?", width=80):
    """Returns (converted_text, warnings)."""
    out, warns = [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.expandtabs(8).rstrip()
        if len(line) > width:
            raise Pad80Error(f"{name}:{n}: {len(line)} columns, maximum {width}")
        if len(line) > 72:
            warns.append(f"{name}:{n}: text in columns 73-{width}, the compiler ignores it")
        out.append(line.ljust(width))
    return "\n".join(out) + "\n", warns


def pad80_file(src, dst, width=80):
    with open(src, encoding="utf-8", errors="replace") as fh:
        text, warns = pad80_text(fh.read(), src, width)
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return warns


def main():
    ap = argparse.ArgumentParser(prog="pad80", description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True, help="destination directory")
    ap.add_argument("--upper", action="store_true", help="uppercase file name")
    ap.add_argument("--ext", help="replaces the extension (e.g. .CBL or .LIB)")
    ap.add_argument("--width", type=int, default=80)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rc = 0
    for f in a.files:
        base, ext = os.path.splitext(os.path.basename(f))
        name = base + (a.ext if a.ext else ext)
        if a.upper:
            name = name.upper()
        dst = os.path.join(a.out, name)
        try:
            for w in pad80_file(f, dst, a.width):
                print(f"warning: {w}", file=sys.stderr)
            print(f"{f} -> {dst}")
        except Pad80Error as e:
            print(f"error: {e}", file=sys.stderr)
            rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
