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
Detailed usage for each tool lives in [scripts/README.md](scripts/README.md).

## Tools

- **check_packages** — Report which venvs under a directory have the given packages installed.
- **list_venvs** — List Python virtual environments under a directory.
- **stale_dirs** — Find directories whose contents have not been updated within a threshold.

## Development

uv manages the environment, with a one-week package cooldown
([cooldowns.dev](https://cooldowns.dev)) configured in `pyproject.toml` via
uv's `exclude-newer`: releases published within the last week are never
resolved. `prek` runs ruff as the pre-commit hook:

```bash
uv sync                      # install dev dependencies (prek)
uv run prek install          # install the git pre-commit hook (once per clone)
uv run prek run --all-files  # lint everything now
```
