#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _add_src_to_path() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _default_root() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    # Priority: shell env > .env file > fallback
    val = os.environ.get("OMEGACLAW_BIO_OUTPUT_ROOT")
    if val:
        return val
    env_file = repo_root / ".env"
    if env_file.exists():
        try:
            for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip().lstrip("export ").strip()
                if line.startswith("OMEGACLAW_BIO_OUTPUT_ROOT="):
                    return line.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            pass
    return "output"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query BioCypher MeTTa output via OmegaClaw bio_graph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--root",
        default=_default_root(),
        metavar="DIR",
        help="Path to BioCypher output folder (default: OMEGACLAW_BIO_OUTPUT_ROOT or 'output')",
    )
    parser.add_argument("--index",   action="store_true", help="Build/reuse index and print summary")
    parser.add_argument("--reindex", action="store_true", help="Force-rebuild index before querying")
    parser.add_argument("--extract", action="store_true", help="Return raw MeTTa atoms instead of formatted output")
    parser.add_argument("--path",    nargs=2, metavar=("SRC", "DST"), help="Find shortest entity path SRC→DST")
    parser.add_argument("--max-hops", type=int, default=5, help="Maximum hops for --path (default: 5)")
    parser.add_argument("--repl",    action="store_true", help="Start interactive query REPL")
    parser.add_argument("query",     nargs="*", help="Query words, e.g.: stats  OR  node gene ENSG00000125863")
    args = parser.parse_args()

    _add_src_to_path()
    import bio_graph as bg  # noqa: PLC0415

    root = args.root

    # --- index / reindex --------------------------------------------------
    if args.reindex:
        print(bg.bio_reindex(root))
        if not args.query and not args.repl and not args.path:
            return 0
    elif args.index:
        print(bg.bio_index(root))
        if not args.query and not args.repl and not args.path:
            return 0

    # --- path query -------------------------------------------------------
    if args.path:
        src, dst = args.path
        print(bg.bio_path(root, src, dst, args.max_hops))
        return 0

    # --- one-shot query ---------------------------------------------------
    if args.query:
        q = " ".join(args.query)
        if args.extract:
            print(bg.bio_extract(root, q))
        else:
            print(bg.bio_query(root, q))
        return 0

    # --- REPL -------------------------------------------------------------
    if args.repl:
        print(f"[bio-query repl] root={root}")
        print("Commands: stats | folders | predicates | folder <g> | predicate <p> | node <t> <id> | entity <id>")
        print("Prefixes: :extract <cmd> — raw MeTTa atoms  |  :path <src> <dst> — BFS path")
        print("Control:  :reindex  :exit")
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
            if raw.startswith(":extract "):
                print(bg.bio_extract(root, raw[len(":extract "):]))
                continue
            if raw.startswith(":path "):
                parts = raw[len(":path "):].split()
                if len(parts) >= 2:
                    print(bg.bio_path(root, parts[0], parts[1], args.max_hops))
                else:
                    print("usage: :path <src_id> <dst_id>")
                continue
            print(bg.bio_query(root, raw))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
