#!/usr/bin/env python3
"""List Python virtual environments under a directory.

Every venv found (any directory containing a pyvenv.cfg) is reported with
its Python version, release status (supported-until / EOL date and the
newest patch release, when online), the command that created it, and its
creation/update times — followed by summaries by Python version and by
interpreter target.

By default each venv's own ``bin/python -I -V`` is executed for its
authoritative version (the version in pyvenv.cfg can be stale or
hand-edited). That runs a binary found in the scanned tree, so pass
--no-exec when scanning an untrusted directory; versions then come from
pyvenv.cfg only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

LIFECYCLE_URL = "https://endoflife.date/api/python.json"
LIFECYCLE_TIMEOUT = 5
VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(version):
    """The (major, minor, micro) embedded in a version string; micro is
    None without a patch level, and the whole result is None when no
    X.Y version is present."""
    m = VERSION_RE.search(version)
    if m is None:
        return None
    micro = int(m.group(3)) if m.group(3) is not None else None
    return int(m.group(1)), int(m.group(2)), micro


def is_excluded(path, excludes):
    return any(path == ex or ex in path.parents for ex in excludes)


def find_venv_cfgs(root, excludes):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        if is_excluded(current, excludes):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not is_excluded(current / d, excludes)]
        if "pyvenv.cfg" in filenames:
            yield current / "pyvenv.cfg"


def parse_cfg(cfg):
    values = {}
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def python_version(python, cfg_version, execute=True):
    if execute:
        try:
            if python.is_file() and os.access(python, os.X_OK):
                result = subprocess.run(
                    [str(python), "-I", "-V"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    if cfg_version:
        return f"Python {cfg_version}"
    if python.is_symlink() and not python.exists():
        return "broken symlink"
    return "unknown"


def interpreter_target(python):
    """The executable a venv's python resolves to ("missing" if there is
    none)."""
    if python.exists() or python.is_symlink():
        return str(python.resolve())
    return "missing"


def iso(ts):
    """UTC ISO-8601 timestamp, second precision."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def venv_times(venv):
    """(created, updated) timestamps for a venv, using lstat so symlinks
    (e.g. bin/python -> base interpreter) are not followed. Created uses
    the birth time where the filesystem exposes it, otherwise the
    earliest modification time."""
    births = []
    mtimes = []

    def record(p):
        try:
            st = p.lstat()
        except OSError:
            return
        if getattr(st, "st_birthtime", None) is not None:
            births.append(st.st_birthtime)
        mtimes.append(st.st_mtime)

    record(venv)
    for dirpath, dirnames, filenames in os.walk(venv, followlinks=False):
        for name in dirnames + filenames:
            record(Path(dirpath) / name)
    if not mtimes:
        return None, None
    return min(births + mtimes), max(mtimes)


def fetch_lifecycle(timeout=LIFECYCLE_TIMEOUT):
    """Fetch Python release lifecycle data (EOL date + newest release
    per minor) from endoflife.date and validate its shape. Returns
    {"X.Y": {"eol": date, "latest": (major, minor, patch) or None}};
    malformed entries are skipped. Raises only OSError (network) and
    ValueError (bad JSON or shape), so callers handle just those."""
    req = urllib.request.Request(
        LIFECYCLE_URL, headers={"User-Agent": "rse-sec-tools/0.1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, list):
        raise ValueError("unexpected lifecycle response: expected a list")
    lifecycle = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        cycle = entry.get("cycle")
        eol = entry.get("eol")
        if not (isinstance(cycle, str) and cycle and isinstance(eol, str) and eol):
            continue
        try:
            eol_date = date.fromisoformat(eol)
        except ValueError:
            continue
        latest = entry.get("latest")
        latest_tuple = None
        if isinstance(latest, str):
            parts = latest.split(".")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                latest_tuple = tuple(int(p) for p in parts)
        lifecycle[cycle] = {"eol": eol_date, "latest": latest_tuple}
    return lifecycle


def version_support(version, today, lifecycle):
    """Structured support info: {detected, known, supported, eol, latest,
    patch} - patch is "na", "newer" (a newer patch release exists) or
    "latest"."""
    parsed = parse_version(version)
    if parsed is None:
        return {"detected": False, "known": False, "supported": None,
                "eol": None, "latest": None, "patch": "na"}
    major, minor, micro = parsed
    info = lifecycle.get(f"{major}.{minor}")
    if info is None:
        return {"detected": True, "known": False, "supported": None,
                "eol": None, "latest": None, "patch": "na"}
    latest = info["latest"]
    if latest is None or micro is None:
        patch = "na"
    elif micro < latest[2]:
        patch = "newer"
    else:
        patch = "latest"
    return {"detected": True, "known": True,
            "supported": today <= info["eol"], "eol": info["eol"],
            "latest": latest, "patch": patch}


def version_status(version, today, lifecycle):
    """Human-readable support + newest-patch status for a version."""
    info = version_support(version, today, lifecycle)
    if not info["detected"]:
        return "n/a (no version detected)"
    if not info["known"]:
        return "n/a (no lifecycle data for this version)"
    support = (f"supported until {info['eol']}" if info["supported"]
               else f"EOL {info['eol']} (unsupported)")
    if info["patch"] == "na":
        if info["latest"] is not None:
            patch = f"latest patch: {'.'.join(map(str, info['latest']))}"
        else:
            patch = "patch n/a"
    elif info["patch"] == "newer":
        patch = f"newer patch: {'.'.join(map(str, info['latest']))}"
    else:
        patch = "latest patch"
    return f"{support} | {patch}"


def collect_venvs(root, excludes, execute=True):
    """(records, targets) for every venv under root, where each record
    is {path, python_version, created_with, created_at, updated_at} and
    targets lists the interpreter each venv's bin/python resolves to.
    Unreadable venvs are skipped with a warning on stderr."""
    records = []
    targets = []
    for cfg in find_venv_cfgs(root, excludes):
        try:
            venv = cfg.parent
            values = parse_cfg(cfg)
            created_at, updated_at = venv_times(venv)
            records.append({
                "path": str(venv),
                "python_version": python_version(
                    venv / "bin" / "python",
                    values.get("version") or values.get("version_info", ""),
                    execute=execute,
                ),
                "created_with": values.get("command", "unknown"),
                "created_at": iso(created_at),
                "updated_at": iso(updated_at),
            })
            targets.append(interpreter_target(venv / "bin" / "python"))
        except OSError as exc:
            print(f"skipping {cfg}: {exc}", file=sys.stderr)
    return records, targets


def print_summary(records, lifecycle, today, file=sys.stdout):
    counts = Counter(r["python_version"] for r in records)
    print(file=file)
    if not records:
        print("No virtual environments found.", file=file)
        return
    print(f"Summary by Python version ({len(records)} total):", file=file)
    if not lifecycle:
        for version in sorted(counts):
            print(f"    {version}: {counts[version]}", file=file)
        print("    (support/patch status unavailable: "
              "lifecycle data not fetched)", file=file)
        return
    rows = [(f"{version}: {counts[version]}",
             version_status(version, today, lifecycle))
            for version in sorted(counts)]
    width = max(len(label) for label, _ in rows)
    for label, status in rows:
        print(f"    {label:<{width}}  {status}", file=file)


def print_interpreter_summary(targets, file=sys.stdout):
    counts = Counter(targets)
    print(file=file)
    if not targets:
        print("No virtual environments found.", file=file)
        return
    print(f"Python interpreter targets ({len(targets)} total):", file=file)
    for target in sorted(counts):
        found = target != "missing" and Path(target).exists()
        note = "" if found else "  (not found on this host)"
        print(f"    {counts[target]:>3}  {target}{note}", file=file)


def main():
    parser = argparse.ArgumentParser(
        description="List virtual environments, their Python version and "
        "release status, the command that created them, and their "
        "creation/update times."
    )
    parser.add_argument("root", nargs="?", help="directory to scan (default: $HOME)")
    parser.add_argument(
        "-x", "--exclude", action="append", default=[], metavar="DIR",
        help="directory to skip; may be given multiple times",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output one JSON object per line to stdout (JSON Lines)",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="skip the Python release lifecycle lookup (no network)",
    )
    parser.add_argument(
        "--no-exec", action="store_true",
        help="never run discovered interpreters; Python versions come from "
        "pyvenv.cfg only (safer when scanning an untrusted directory)",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().absolute() if args.root else Path.home()
    excludes = [Path(d).expanduser().absolute() for d in args.exclude]

    lifecycle = {}
    if not args.offline:
        try:
            lifecycle = fetch_lifecycle()
        except (OSError, ValueError):
            lifecycle = {}
    today = datetime.now(timezone.utc).date()

    status_stream = sys.stderr if args.json else sys.stdout
    print(f"Searching for virtual environments under {root}...", file=status_stream)
    records, targets = collect_venvs(root, excludes, execute=not args.no_exec)

    if args.json:
        for r in records:
            print(json.dumps(r, separators=(",", ":")))
        print_summary(records, lifecycle, today, file=sys.stderr)
        print_interpreter_summary(targets, file=sys.stderr)
    else:
        for i, r in enumerate(records, 1):
            print(f"[{i}] {r['path']}")
            print(f"    {r['python_version']}")
            if lifecycle:
                print(f"    {version_status(r['python_version'], today, lifecycle)}")
            print(f"    created with: {r['created_with']}")
            print(f"    created: {r['created_at'] or 'unknown'}")
            print(f"    updated: {r['updated_at'] or 'unknown'}")
        print(f"Found {len(records)} virtual environment(s).")
        print_summary(records, lifecycle, today)
        print_interpreter_summary(targets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
