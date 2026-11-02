#!/usr/bin/env python3
"""Find directories whose contents have not been updated within a threshold.

A directory is stale when nothing at or below it has been modified for
longer than the threshold (default: 1 year): its own mtime, and every
file or directory beneath it, are all older than the cutoff (symlinks
count as the leaf entries they are and are never followed; a directory's
own mtime moves when its direct entries are added, removed or renamed).
Hidden entries — dot-directories such as .git, and dotfiles — are
ignored entirely (not scanned, not counted, not reported) unless
--include-hidden is given, so churn inside .git does not keep an
otherwise untouched project looking fresh. Only directories within
--depth levels of the scan point are listed (default: 3); deeper stale
branches are counted in the summary but not listed. Results are
ordered newest change first, so the longest-neglected branch is the
last thing read. A stale directory makes its whole subtree stale, so
when one is reported its stale descendants are suppressed and it
stands for the entire branch.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SECONDS_PER_DAY = 86400


def is_excluded(path, excludes):
    return any(path == ex or ex in path.parents for ex in excludes)


def iso(ts):
    """UTC ISO-8601 timestamp, second precision."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def list_entries(directory, on_error):
    """Snapshot of one directory's entries ([] when unreadable, after
    telling on_error). A snapshot keeps at most one scan open at a
    time, where keeping an open iterator per directory would need one
    per depth level."""
    try:
        with os.scandir(directory) as it:
            return list(it)
    except OSError as exc:
        on_error(directory, exc)
        return []


def scan(root, excludes, cutoff, include_hidden, on_error):
    """(path, newest mtime) for every stale directory in the tree rooted
    at root — a directory whose own mtime, and every mtime beneath it
    (symlinks not followed), is at or before the cutoff. Depth-first on
    an explicit stack: each frame is [directory, entry iterator, running
    max mtime], a frame is popped (and classified) only once its whole
    subtree has been walked, and its final max is folded into the
    parent's. Excluded directories stop the walk and contribute nothing,
    as if absent; without include_hidden the same goes for hidden
    entries (dot-prefixed names), which are neither entered nor counted.
    The named root is always scanned, hidden or not. A directory that
    cannot be listed is measured by its own mtime alone."""
    if is_excluded(root, excludes):
        return []
    try:
        root_mtime = os.lstat(root).st_mtime
    except OSError as exc:
        on_error(root, exc)
        return []
    stale = []
    frames = [[root, iter(list_entries(root, on_error)), root_mtime]]
    while frames:
        frame = frames[-1]
        entry = next(frame[1], None)
        if entry is None:
            frames.pop()
            if frame[2] <= cutoff:
                stale.append((frame[0], frame[2]))
            if frames:
                frames[-1][2] = max(frames[-1][2], frame[2])
            continue
        if not include_hidden and entry.name.startswith("."):
            continue
        if entry.is_dir(follow_symlinks=False):
            path = Path(entry.path)
            if is_excluded(path, excludes):
                continue
            try:
                own_mtime = entry.stat(follow_symlinks=False).st_mtime
            except OSError as exc:
                on_error(path, exc)
                continue
            frames.append([path, iter(list_entries(path, on_error)), own_mtime])
        else:
            try:
                frame[2] = max(frame[2], entry.stat(follow_symlinks=False).st_mtime)
            except OSError as exc:
                on_error(Path(entry.path), exc)
    return stale


def keep_topmost(stale):
    """Drop every stale directory whose parent is stale too: a stale
    directory's whole subtree is stale, so a stale ancestor anywhere
    above implies the direct parent is stale as well, and checking the
    direct parent alone is enough."""
    stale_paths = {path for path, _ in stale}
    return [(path, mtime) for path, mtime in stale
            if path.parent not in stale_paths]


def rows_of(results, now):
    """(changed-on date, whole days since that change, path) for each
    result, in the order given."""
    return [(iso(mtime).split("T")[0],
             int((now - mtime) // SECONDS_PER_DAY),
             str(path))
            for path, mtime in results]


def print_results(results, now, file=sys.stdout):
    """The stale directories, newest change at the top so the longest
    untouched branch is read last: when it changed, how long ago that
    was, and where it is."""
    rows = rows_of(results, now)
    days_width = max((len(str(days)) for _, days, _ in rows), default=0)
    for i, (when, days, path) in enumerate(rows, 1):
        print(f"[{i}] {when}  {days:>{days_width}} days ago  {path}", file=file)


def print_summary(shown, stale, days, max_depth, file=sys.stdout):
    """Bottom summary: how many stale branches were listed, how many
    stale subdirectories those results stand for (hidden beneath them),
    and how many stale directories were not listed because they are
    deeper than max_depth below the scan point."""
    print(file=file)
    if not shown:
        print(f"No directory has gone {days} day(s) without a change.", file=file)
        return
    shown_paths = {path for path, _ in shown}
    beneath = sum(1 for path, _ in stale
                  if any(parent in shown_paths for parent in path.parents))
    deeper = len(stale) - len(shown) - beneath
    notes = []
    if beneath:
        sub = "subdirectory" if beneath == 1 else "subdirectories"
        notes.append(f"{beneath} stale {sub} hidden beneath them")
    if deeper:
        notes.append(f"{deeper} deeper than {max_depth} level(s)")
    note = f" ({'; '.join(notes)})" if notes else ""
    plural = "y" if len(shown) == 1 else "ies"
    print(f"Found {len(shown)} stale director{plural}{note}.", file=file)


def main():
    parser = argparse.ArgumentParser(
        description="List the directories under a directory whose "
        "contents, and everything beneath them, have not been updated "
        "within a threshold (default: 1 year). Only a branch's topmost "
        "stale directory is reported (children of a stale directory are "
        "stale by definition), newest change first, and only for "
        "--depth levels below the scan point (default: 3). Hidden "
        "entries (dot-directories such as .git, and dotfiles) are "
        "ignored unless --include-hidden is given."
    )
    parser.add_argument("root", nargs="?", help="directory to scan (default: $HOME)")
    parser.add_argument(
        "-x", "--exclude", action="append", default=[], metavar="DIR",
        help="directory to skip (and ignore entirely); may be given multiple times",
    )
    parser.add_argument(
        "--days", type=int, default=365, metavar="N",
        help="stale threshold in days (default: 365, one year)",
    )
    parser.add_argument(
        "--depth", type=int, default=3, metavar="N",
        help="how many levels below the scan point to list (default: 3); "
        "deeper stale directories are counted in the summary only",
    )
    parser.add_argument(
        "--include-hidden", action="store_true",
        help="also scan, count and report hidden entries (dot-directories "
        "such as .git, and dotfiles); by default they are ignored entirely",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output one JSON object per line to stdout (JSON Lines)",
    )
    args = parser.parse_args()
    if args.days < 0:
        parser.error("--days must not be negative")
    if args.depth < 0:
        parser.error("--depth must not be negative")

    root = Path(args.root).expanduser().absolute() if args.root else Path.home()
    excludes = [Path(d).expanduser().absolute() for d in args.exclude]
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    now = time.time()
    cutoff = now - args.days * SECONDS_PER_DAY

    def warn(path, exc):
        print(f"skipping {path}: {exc}", file=sys.stderr)

    status = sys.stderr if args.json else sys.stdout
    print(f"Scanning {root} for directories with no change in the last "
          f"{args.days} day(s) (before {iso(cutoff)})...", file=status)
    stale = scan(root, excludes, cutoff, args.include_hidden, warn)
    # The walk always visits the whole tree — deep mtimes decide whether
    # shallower directories are stale — so depth only trims the report.
    results = [item for item in keep_topmost(stale)
               if len(item[0].relative_to(root).parts) <= args.depth]
    results.sort(key=lambda item: (-item[1], str(item[0])))

    if args.json:
        for path, mtime in results:
            record = {
                "path": str(path),
                "last_updated": iso(mtime),
                "days_since_update": int((now - mtime) // SECONDS_PER_DAY),
                "threshold_days": args.days,
            }
            print(json.dumps(record, separators=(",", ":")))
    else:
        print_results(results, now)
    print_summary(results, stale, args.days, args.depth, file=status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
