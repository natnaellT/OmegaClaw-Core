#!/usr/bin/env python3
"""
Simple CLI for querying BioCypher MeTTa outputs via OmegaClaw bio_graph.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _add_src_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    sys.path.insert(0, str(src_dir))


def _read_env_value(repo_root: Path, key: str) -> str | None:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return None

    try:
        with env_path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                current_key, value = line.split("=", 1)
                if current_key.strip() != key:
                    continue
                return value.strip().strip('"').strip("'")
    except OSError:
        return None

    return None


def _default_root() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    # Shell env has highest priority, then repo .env file, then fallback.
    return (
        os.environ.get("OMEGACLAW_BIO_OUTPUT_ROOT")
        or _read_env_value(repo_root, "OMEGACLAW_BIO_OUTPUT_ROOT")
        or "output"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query BioCypher MeTTa output with OmegaClaw bio_graph."
    )
    parser.add_argument(
        "--root",
        default=_default_root(),
        help=(
            "Path to output folder containing .metta files "
            "(default: OMEGACLAW_BIO_OUTPUT_ROOT from env/.env, else output)"
        ),
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Build/reuse index and print summary, then exit",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Force reindex before running queries",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Start interactive query mode",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Query command words, e.g. stats or node gene ENSG...",
    )
    args = parser.parse_args()

    _add_src_to_path()
    import bio_graph as bg  # pylint: disable=import-error,import-outside-toplevel

    root = args.root

    if args.reindex:
        print(bg.bio_reindex(root))
        # If reindex was requested without query/repl/index, exit after summary.
        if not args.query and not args.repl and not args.index:
            return 0
    elif args.index:
        print(bg.bio_index(root))
        if not args.query and not args.repl:
            return 0

    if args.query:
        query_text = " ".join(args.query)
        print(bg.bio_query_in(root, query_text))
        return 0

    if args.repl:
        print(f"[bio-query repl] root={root}")
        print("Type query commands (stats, folders, predicates, node ..., neighbors ...).")
        print("Type help for command help, :reindex to refresh, :exit to quit.")
        while True:
            try:
                raw = input("bio> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not raw:
                continue
            if raw in {":exit", "exit", "quit"}:
                return 0
            if raw == ":reindex":
                print(bg.bio_reindex(root))
                continue
            print(bg.bio_query_in(root, raw))
        
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
