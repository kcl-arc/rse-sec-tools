#!/usr/bin/env python3
"""Report which venvs under a directory have the given packages installed.

Every directory below the root with a bin/activate is asked which of the
requested packages it has installed: with its own ``bin/python -m pip
show`` when it has a working pip, or by reading the site-packages
``*.dist-info`` METADATA files directly when it does not (uv venvs,
broken or missing interpreters). Only the venvs where a package was
found are listed, with the version found in each. The summary then shows
how many venvs run each version, the latest published version (from
PyPI, unless --offline), and how many of the found venvs are not on it.
Executing a venv's interpreter is only needed for pip, so do not aim the
pip path at a tree that is not trusted.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path

PIP_TIMEOUT = 30
PYPI_URL = "https://pypi.org/pypi/{}/json"
PYPI_TIMEOUT = 5
NORMALIZE_RE = re.compile(r"[-_.]+")


class PipError(Exception):
    """A venv's pip could not be asked anything at all."""


def normalize(name):
    """PEP 503 form of a package name, so requested names match the ones
    pip show reports."""
    return NORMALIZE_RE.sub("-", name.strip()).lower()


def version_key(version):
    """Sort key ordering version strings newest first by their numbers."""
    return tuple(-int(n) for n in re.findall(r"\d+", version or ""))


def is_excluded(path, excludes):
    return any(path == ex or ex in path.parents for ex in excludes)


def find_venvs(root, excludes):
    """Root of every virtual environment under root (any directory with
    a bin/activate), skipping excluded directories. The interior of a
    found venv is not searched, so venvs nested inside other venvs are
    not reported."""
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        current = Path(dirpath)
        if is_excluded(current, excludes):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not is_excluded(current / d, excludes)]
        if (current / "bin" / "activate").is_file():
            yield current
            dirnames[:] = []


def pip_show(python, packages, timeout=PIP_TIMEOUT):
    """{normalized name: {"name", "version"}} for the packages pip
    reports as installed for this interpreter. Raises PipError when the
    interpreter or its pip cannot be used at all."""
    try:
        result = subprocess.run(
            [str(python), "-m", "pip", "show", *packages],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PipError(str(exc))
    found = {}
    name = None
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Name" and value:
            name = normalize(value)
            found.setdefault(name, {"name": value, "version": None})
        elif key == "Version" and value and name is not None:
            found[name]["version"] = value
    stderr = result.stderr.strip()
    if not found and stderr and "not found" not in stderr.lower():
        raise PipError(" ".join(stderr.split()))
    return found


def fetch_latest(names, timeout=PYPI_TIMEOUT):
    """{normalized name: latest published version} for each name, from
    PyPI's JSON API; a name is absent when the lookup fails (offline,
    not on PyPI, or unexpected data)."""
    latest = {}
    for name in names:
        req = urllib.request.Request(
            PYPI_URL.format(name), headers={"User-Agent": "rse-sec-tools/0.1"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.load(response)
            version = (data.get("info") or {}).get("version")
            if isinstance(version, str) and version:
                latest[name] = version
        except (OSError, ValueError):
            continue
    return latest


def parse_metadata(text):
    """{"name", "version"} (either may be None) from the first Name: and
    Version: fields of a dist-info METADATA file."""
    name = version = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Name" and name is None and value:
            name = value
        elif key == "Version" and version is None and value:
            version = value
        if name is not None and version is not None:
            break
    return {"name": name, "version": version}


def scan_site_packages(venv):
    """{normalized name: {"name", "version}} from the *.dist-info
    METADATA files under the venv's site-packages, without executing
    anything. None when the venv has no site-packages directory at all,
    so nothing can be said either way."""
    sites = [site
             for lib in (venv / "lib", venv / "lib64")
             for site in lib.glob("*/site-packages")]
    if not sites:
        return None
    found = {}
    seen = set()
    for site in sites:
        real = site.resolve()
        if real in seen:
            continue
        seen.add(real)
        for metadata in sorted(site.glob("*.dist-info/METADATA")):
            try:
                info = parse_metadata(
                    metadata.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if info["name"] is not None:
                found.setdefault(normalize(info["name"]), info)
    return found


def check_venv(venv, packages):
    """Report record for one venv: {path, error, checked, pip_error,
    packages} - error is None or why nothing could be checked (packages
    then None), checked is "pip" (the venv's bin/python -m pip show) or
    "site-packages" (METADATA read straight off disk when pip cannot
    run, e.g. in uv venvs; pip_error is then why it could not), and
    packages maps each requested spelling to {"installed": ...} plus
    pip's name and version when installed."""
    record = {"path": str(venv), "error": None, "checked": None,
              "pip_error": None, "packages": None}
    python = venv / "bin" / "python"
    try:
        if not os.access(python, os.X_OK):
            raise PipError("bin/python missing or not executable")
        found = pip_show(python, packages)
        record["checked"] = "pip"
    except PipError as exc:
        scanned = scan_site_packages(venv)
        if scanned is None:
            record["error"] = f"{exc}; no site-packages to inspect"
            return record
        found = scanned
        record["checked"] = "site-packages"
        record["pip_error"] = str(exc)
    record["packages"] = {}
    for package in packages:
        info = found.get(normalize(package))
        if info is None:
            record["packages"][package] = {"installed": False}
        else:
            record["packages"][package] = {
                "installed": True,
                "name": info["name"],
                "version": info["version"],
            }
    return record


def package_hits(records, packages):
    """{package: [(path, version), ...]} in scan order, for every venv
    where that package is installed (version None when pip or the
    metadata did not record one)."""
    hits = {package: [] for package in packages}
    for record in records:
        if record["error"] is not None:
            continue
        for package, info in record["packages"].items():
            if info["installed"]:
                hits[package].append((record["path"], info["version"]))
    return hits


def print_hits(records, packages, hits, file=sys.stdout):
    """Per-package listing of the venvs where each package is installed,
    with the version found in each one."""
    checkable = sum(1 for r in records if r["error"] is None)
    not_checkable = len(records) - checkable
    for package in packages:
        found = hits[package]
        head = f"{package}: installed in {len(found)} of {checkable} venvs"
        if not_checkable:
            head += f" ({not_checkable} not checkable)"
        print(head, file=file)
        width = max((len(path) for path, _ in found), default=0)
        for i, (path, version) in enumerate(found, 1):
            print(f"[{i}] {path:<{width}}  {version or 'unknown'}", file=file)
        print(file=file)


def print_summary(records, packages, hits, latest, file=sys.stdout):
    """Bottom summary: for each package, how many venvs run each version
    (newest first), and when the latest published version is known, how
    many found venvs are not on it."""
    print(file=file)
    if not records:
        print("No virtual environments found.", file=file)
        return
    not_checkable = sum(1 for r in records if r["error"] is not None)
    print(f"Summary by package ({len(records)} total):", file=file)
    for package in packages:
        found = hits[package]
        if found:
            counts = Counter(version or "unknown" for _, version in found)
            ordered = sorted(
                counts.items(),
                key=lambda item: (item[0] == "unknown", version_key(item[0])))
            tally = ", ".join(f"{version} x {count}"
                              for version, count in ordered)
        else:
            tally = "none found"
        note = f" ({not_checkable} not checkable)" if not_checkable else ""
        print(f"    {package}: {tally}{note}", file=file)
        if not found:
            continue
        newest = latest.get(package)
        if newest:
            stale = sum(1 for _, version in found if version != newest)
            print(f"        latest: {newest} - {stale} venvs not on the "
                  "latest version", file=file)
        else:
            print("        latest: unknown (no PyPI data)", file=file)


def main():
    parser = argparse.ArgumentParser(
        description="Report which virtual environments under a directory "
        "have the given packages installed: the venvs and versions where "
        "each is found, a tally of the versions found, and how many found "
        "venvs are not on the latest published version."
    )
    parser.add_argument(
        "root", metavar="DIR",
        help="directory tree to scan for virtual environments",
    )
    parser.add_argument(
        "packages", nargs="+", metavar="PACKAGE",
        help="package name(s) to check, e.g. pillow requests",
    )
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
        help="skip the PyPI lookup of the latest published version",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().absolute()
    excludes = [Path(d).expanduser().absolute() for d in args.exclude]

    status_stream = sys.stderr if args.json else sys.stdout
    print(f"Searching for virtual environments under {root} for "
          f"{', '.join(args.packages)}...", file=status_stream)
    records = [check_venv(venv, args.packages)
               for venv in find_venvs(root, excludes)]
    hits = package_hits(records, args.packages)

    latest = {}
    if not args.offline:
        wanted = sorted({normalize(p) for p in args.packages if hits[p]})
        fetched = fetch_latest(wanted)
        latest = {p: fetched.get(normalize(p)) for p in args.packages}

    if args.json:
        for record in records:
            print(json.dumps(record, separators=(",", ":")))
        print_summary(records, args.packages, hits, latest, file=sys.stderr)
    else:
        print_hits(records, args.packages, hits)
        print(f"Found {len(records)} virtual environment(s).")
        print_summary(records, args.packages, hits, latest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
