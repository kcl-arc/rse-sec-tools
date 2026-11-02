# rse-sec-tools

Small security and development utility scripts. Python 3.11+
standard library only — no third-party dependencies.

## Usage

`run.py` discovers and runs the tools in `scripts/`:

```bash
python3 run.py                        # list every tool + one-line description
python3 run.py --help                 # every tool's full --help
python3 run.py list_venvs . --json    # run a tool, arguments pass through
```

Tools can also be called directly: `python3 scripts/list_venvs.py ...`.

## list_venvs

Scans a directory tree (default: `$HOME`) for virtual environments and
reports each venv's Python version, its release status (supported-until /
EOL date and the newest patch release, fetched from endoflife.date), the
command that created it, and its creation/update times — then summaries
by Python version and by interpreter target.

```bash
python3 scripts/list_venvs.py /path/to/scan -x /skip/this
python3 scripts/list_venvs.py --json       # JSON Lines on stdout, summaries on stderr
python3 scripts/list_venvs.py --offline    # skip the lifecycle lookup (no network)
python3 scripts/list_venvs.py --no-exec    # never run discovered interpreters
```

By default the scan executes each discovered `bin/python -I -V`, because
the version recorded in `pyvenv.cfg` can be stale. When the scanned tree
is not trustworthy, pass `--no-exec` and versions come from
`pyvenv.cfg` only.

## check_packages

Reports which packages are installed in the virtual environments under a
directory, and how up to date they are. Only the venvs where a package
was found are listed, with the version found in each; the summary tallies
the versions found, shows the latest published version (from PyPI), and
counts how many found venvs are not on it. Names match the way pip does
(case and `-`/`_` spelling don't matter).

Venvs with a working pip are queried with their own
`bin/python -m pip show` (executed — don't point this at a tree you
don't trust). Venvs without one — uv-created environments, or venvs
whose interpreter is gone or broken — are answered by reading their
`site-packages/*.dist-info` metadata straight off disk instead.

```bash
python3 scripts/check_packages.py . pillow requests
python3 scripts/check_packages.py /path -x node_modules --json
python3 scripts/check_packages.py . --offline pillow   # skip the PyPI lookup
```

Interiors of found venvs are not searched, so venvs nested inside other
venvs are not reported.

## stale_dirs

Finds directories whose contents have not been updated within a threshold
(default: 1 year): the newest modification time of the directory itself
or of anything beneath it — symlinks are not followed — is older than the
cutoff. Hidden entries (dot-directories such as `.git`, and dotfiles) are
skipped by default, so an actively-committed-but-untouched project still
counts as stale; `--include-hidden` counts them. Only the topmost directory
of each stale branch is reported, since children of a stale directory are
stale by definition. Results are ordered newest change first, so the
longest-neglected branches come last, and only for `--depth` levels
below the scan point (default 3) — deeper stale branches are counted in
the summary but not listed.

```bash
python3 scripts/stale_dirs.py /path/to/scan --days 365
python3 scripts/stale_dirs.py -x node_modules -x .venv   # default root: $HOME
python3 scripts/stale_dirs.py --depth 5                  # list deeper branches
python3 scripts/stale_dirs.py --json                    # JSON Lines on stdout
python3 scripts/stale_dirs.py . --include-hidden        # count .git etc.
```
