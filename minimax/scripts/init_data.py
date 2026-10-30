"""Initialise the seekdb material index for a project."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdd_context.cli import main as cli_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Import specs/code/tests into seekdb")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--seekdb-dsn", default=None)
    parser.add_argument("--seekdb-path", default=None)
    args = parser.parse_args()

    argv: list[str] = []
    if args.seekdb_dsn:
        argv += ["--seekdb-dsn", args.seekdb_dsn]
    if args.seekdb_path:
        argv += ["--seekdb-path", args.seekdb_path]
    argv += ["init", "--reset"]
    if args.project_root:
        argv += ["--project-root", args.project_root]
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
