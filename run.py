#!/usr/bin/env python3
"""Discover and run the tools in scripts/.

With no arguments, list every script with a one-line description (the
first line of its docstring). With --help, print every script's full
--help output. Otherwise the first argument names a script (with or
without .py) and everything after it is passed to that script:

    python3 run.py list_venvs . --json
"""

import argparse
import ast
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent / "scripts"


def one_liner(path):
    """First line of a script's docstring (parsed, never executed)."""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (OSError, SyntaxError):
        doc = None
    if not doc or not doc.strip():
        return "(no description)"
    return doc.strip().splitlines()[0].strip()


def scripts():
    return sorted(SCRIPTS.glob("*.py"))


def list_names(files):
    width = max(len(path.stem) for path in files)
    for path in files:
        print(f"{path.stem:<{width}}  {one_liner(path)}")


def self_help():
    """Print run.py's own --help."""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Discover and run the tools in scripts/: list them "
        "(no arguments), show every tool's full --help (--help), or run "
        "a named script with the remaining arguments passed through.",
    )
    parser.add_argument(
        "script", nargs="?",
        help="script from scripts/ to run, e.g. list_venvs (or with .py)",
    )
    parser.add_argument(
        "args", nargs="*", metavar="args",
        help="everything after the script name is passed to it unchanged",
    )
    parser.print_help()


def full_help(files):
    self_help()
    for path in files:
        print(f"\n==> {path.stem}")
        done = subprocess.run(
            [sys.executable, str(path), "--help"],
            capture_output=True, text=True,
        )
        print(done.stdout.strip())
        if done.stderr.strip():
            print(done.stderr.strip(), file=sys.stderr)


def main(argv):
    files = scripts()
    if not files:
        print(f"No scripts found in {SCRIPTS}.", file=sys.stderr)
        return 1

    if not argv:
        list_names(files)
        return 0
    if argv[0] in ("-h", "--help"):
        full_help(files)
        return 0

    by_name = {name: path for path in files
               for name in (path.stem, path.name)}
    script = by_name.get(argv[0])
    if script is None:
        print(f"Unknown script: {argv[0]!r}", file=sys.stderr)
        print(f"Available: {', '.join(path.stem for path in files)}",
              file=sys.stderr)
        return 1
    return subprocess.run(
        [sys.executable, str(script), *argv[1:]]
    ).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
