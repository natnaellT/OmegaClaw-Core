#!/usr/bin/env python3
"""Quick smoke tests for OmegaClaw bio_graph indexing/querying.

Usage:
  python scripts/bio_smoke.py --root /home/natnael/dev/biocypher-kg-/output_human
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


def _add_src_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    sys.path.insert(0, str(src_dir))


def _find_first_entity_id(root: Path, entity_type: str) -> Optional[str]:
    # Match tuple-like terms such as: (gene ENSG00000101349)
    pattern = re.compile(r"\(" + re.escape(entity_type) + r"\s+([^\s\)]+)\)")
    for metta_file in sorted(root.rglob("*.metta")):
        try:
            with metta_file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    m = pattern.search(line)
                    if m:
                        return m.group(1)
        except OSError:
            continue
    return None


def _short(text: str, lines: int = 12) -> str:
    chunks = text.splitlines()
    return "\n".join(chunks[:lines])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bio_graph smoke tests.")
    parser.add_argument("--root", required=True, help="Path to BioCypher MeTTa output root")
    parser.add_argument(
        "--show-lines",
        type=int,
        default=12,
        help="How many lines to show per query output (default: 12)",
    )
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: output root does not exist: {root}")
        return 2

    _add_src_to_path()
    import bio_graph as bg  # pylint: disable=import-error,import-outside-toplevel

    print(f"[smoke] root={root}")

    print("\n== index ==")
    index_summary = bg.bio_index(str(root))
    print(index_summary)
    if " error:" in index_summary:
        return 1

    print("\n== stats ==")
    print(_short(bg.bio_query_in(str(root), "stats"), args.show_lines))

    print("\n== folders ==")
    print(_short(bg.bio_query_in(str(root), "folders"), args.show_lines))

    print("\n== predicates ==")
    print(_short(bg.bio_query_in(str(root), "predicates"), args.show_lines))

    gene_id = _find_first_entity_id(root, "gene")
    if gene_id:
        print(f"\n== sample gene id ==\n{gene_id}")
        print("\n== predicate gene ==")
        print(_short(bg.bio_query_in(str(root), "predicate gene"), args.show_lines))
        print("\n== node gene <id> ==")
        print(_short(bg.bio_query_in(str(root), f"node gene {gene_id}"), args.show_lines))
        print("\n== entity <id> ==")
        print(_short(bg.bio_query_in(str(root), f"entity {gene_id}"), args.show_lines))
        print("\n== neighbors gene <id> ==")
        print(_short(bg.bio_query_in(str(root), f"neighbors gene {gene_id}"), args.show_lines))
    else:
        print("\n[warn] no (gene <id>) tuple found; skipping gene-focused checks")

    transcript_id = _find_first_entity_id(root, "transcript")
    if transcript_id:
        print(f"\n== sample transcript id ==\n{transcript_id}")
        print("\n== node transcript <id> ==")
        print(_short(bg.bio_query_in(str(root), f"node transcript {transcript_id}"), args.show_lines))

    print("\n[smoke] completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
