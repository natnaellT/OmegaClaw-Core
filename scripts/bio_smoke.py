#!/usr/bin/env python3
"""Smoke tests for OmegaClaw bio_graph indexing and querying.

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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _find_first_entity_id(root: Path, entity_type: str) -> Optional[str]:
    pattern = re.compile(r"\(" + re.escape(entity_type) + r"\s+([^\s\)]+)\)")
    for mf in sorted(root.rglob("*.metta")):
        try:
            for line in mf.open(encoding="utf-8", errors="replace"):
                m = pattern.search(line)
                if m:
                    return m.group(1)
        except OSError:
            continue
    return None


def _short(text: str, n: int = 12) -> str:
    return "\n".join(text.splitlines()[:n])


def _section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bio_graph smoke tests.")
    parser.add_argument("--root", required=True, help="Path to BioCypher MeTTa output root")
    parser.add_argument("--lines", type=int, default=12, help="Lines to show per result (default: 12)")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: output root does not exist: {root}")
        return 2

    _add_src_to_path()
    import bio_graph as bg  # noqa: PLC0415

    n = args.lines
    print(f"[smoke] root={root}")

    _section("index")
    summary = bg.bio_index(str(root))
    print(summary)
    if "error:" in summary:
        return 1

    _section("stats")
    print(_short(bg.bio_query(str(root), "stats"), n))

    _section("folders")
    print(_short(bg.bio_query(str(root), "folders"), n))

    _section("predicates")
    print(_short(bg.bio_query(str(root), "predicates"), n))

    # Gene checks
    gene_id = _find_first_entity_id(root, "gene")
    if gene_id:
        print(f"\n== sample gene id ==\n{gene_id}")

        _section("node gene <id>")
        print(_short(bg.bio_query(str(root), f"node gene {gene_id}"), n))

        _section("entity <id>")
        print(_short(bg.bio_query(str(root), f"entity {gene_id}"), n))

        _section("bio-extract node gene <id>  (raw MeTTa)")
        print(_short(bg.bio_extract(str(root), f"node gene {gene_id}"), n))
    else:
        print("\n[warn] no (gene <id>) tuple found — skipping gene checks")

    # Transcript checks
    transcript_id = _find_first_entity_id(root, "transcript")
    if transcript_id:
        print(f"\n== sample transcript id ==\n{transcript_id}")

        _section("node transcript <id>")
        print(_short(bg.bio_query(str(root), f"node transcript {transcript_id}"), n))

    # Path check — try gene→transcript if both found
    if gene_id and transcript_id:
        _section(f"bio-path gene={gene_id} -> transcript={transcript_id}")
        print(_short(bg.bio_path(str(root), gene_id, transcript_id, max_hops=4), n))

    print("\n[smoke] completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
