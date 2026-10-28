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
