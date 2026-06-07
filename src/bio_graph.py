from __future__ import annotations

import os
import shlex
import subprocess
import shutil
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union

Term = Union[str, List["Term"]]


@dataclass
class Atom:
    """One parsed top-level MeTTa s-expression, fully indexed."""
    atom_id: int
    relation_group: str   # first-level directory name under root
    file_kind: str        # file basename without extension (e.g. "nodes")
    file_path: str
    line: int
    raw: str              # original source text of the atom
    head: str             # leading symbol, e.g. "transcribes_to"
    entities: List[Tuple[str, str]]  # [(type, id), ...] extracted from atom


@dataclass
class BioIndex:
    root: str
    signature: Tuple[int, int, int]   # (file_count, max_mtime, total_bytes)
    files_scanned: int = 0
    parse_errors: int = 0
    atoms: List[Atom] = field(default_factory=list)
    by_folder: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))
    by_head: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))
    # (normalised_type, normalised_id) → atom_ids
    by_entity: Dict[Tuple[str, str], List[int]] = field(default_factory=lambda: defaultdict(list))
    # normalised_id → atom_ids  (type-agnostic lookup)
    by_entity_id: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))


# Full index cache: abs_root → BioIndex
_INDEX_CACHE: Dict[str, BioIndex] = {}

# Per-file parse cache for hot/partial queries: abs_path → {"sig": ..., "atoms": ..., "ts": ...}
_FILE_CACHE: Dict[str, dict] = {}
_FILE_CACHE_MAX = 256   # LRU cap

def _norm_type(t: str) -> str:
    return t.strip().lower()


def _norm_id(i: str) -> str:
    return i.strip().lower()


def _strip_comments(text: str) -> str:
    """Strip MeTTa line comments (`;` to end of line)."""
    lines = []
    for line in text.splitlines():
        if ";" in line:
            line = line.split(";", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _iter_top_level_atoms(text: str) -> Iterator[Tuple[str, int]]:
    """Yield (raw_atom_text, start_line) for each top-level parenthesised expression."""
    depth = 0
    start = -1
    start_line = 1
    line = 1
    for idx, ch in enumerate(text):
        if ch == "\n":
            line += 1
        if ch == "(":
            if depth == 0:
                start = idx
                start_line = line
            depth += 1
        elif ch == ")":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                atom = text[start: idx + 1].strip()
                if atom:
                    yield atom, start_line
                start = -1


def _tokenize(atom: str) -> List[str]:
    tokens: List[str] = []
    cur: List[str] = []
    in_str = False
    escaped = False

    def flush():
        if cur:
            tokens.append("".join(cur))
            cur.clear()

    for ch in atom:
        if in_str:
            cur.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
                flush()
            continue
        if ch.isspace():
            flush()
            continue
        if ch == '"':
            flush()
            in_str = True
            cur.append(ch)
            continue
        if ch in "()":
            flush()
            tokens.append(ch)
            continue
        cur.append(ch)
    flush()
    return tokens


def _parse_term(tokens: List[str], i: int = 0) -> Tuple[Term, int]:
    if i >= len(tokens):
        raise ValueError("Unexpected end of token stream")
    tok = tokens[i]
    if tok != "(":
        # strip surrounding quotes from string literals
        if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
            return tok[1:-1], i + 1
        return tok, i + 1
    i += 1
    out: List[Term] = []
    while i < len(tokens) and tokens[i] != ")":
        term, i = _parse_term(tokens, i)
        out.append(term)
    if i >= len(tokens):
        raise ValueError("Unbalanced parentheses")
    return out, i + 1


def _parse_atom(raw: str) -> Term:
    tokens = _tokenize(raw)
    parsed, consumed = _parse_term(tokens, 0)
    if consumed != len(tokens):
        raise ValueError("Trailing tokens after parse")
    return parsed


def _collect_entities(term: Term, out: Set[Tuple[str, str]]) -> None:
    """Recursively find (type, id) pairs: any 2-element list of two strings."""
    if isinstance(term, str):
        return
    if len(term) == 2 and isinstance(term[0], str) and isinstance(term[1], str):
        out.add((term[0], term[1]))
    for child in term[1:]:
        _collect_entities(child, out)


def _walk_metta_files(root: str) -> Iterator[Tuple[str, str, str]]:
    """Yield (abs_file_path, relation_group, file_kind) for every .metta file."""
    for dirpath, _, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        relation_group = rel.split(os.sep, 1)[0] if rel != "." else "_root"
        for name in sorted(filenames):
            if name.endswith(".metta"):
                yield os.path.join(dirpath, name), relation_group, os.path.splitext(name)[0].lower()


def _compute_signature(root: str) -> Tuple[int, int, int]:
    file_paths = [fp for fp, _, _ in _walk_metta_files(root)]
    if not file_paths:
        return 0, 0, 0
    mtime = 0
    size = 0
    for fp in file_paths:
        st = os.stat(fp)
        mtime = max(mtime, int(st.st_mtime))
        size += int(st.st_size)
    return len(file_paths), mtime, size


def _parse_file_into_atoms(file_path: str, relation_group: str, file_kind: str,
                            id_offset: int = 0) -> Tuple[List[Atom], int]:
    atoms: List[Atom] = []
    errors = 0
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            content = _strip_comments(fh.read())
    except OSError:
        return atoms, errors

    next_id = id_offset
    for raw, line in _iter_top_level_atoms(content):
        try:
            parsed = _parse_atom(raw)
        except ValueError:
            errors += 1
            continue
        if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], str):
            errors += 1
            continue
        head = parsed[0]
        ents: Set[Tuple[str, str]] = set()
        _collect_entities(parsed, ents)
        atoms.append(Atom(
            atom_id=next_id,
            relation_group=relation_group,
            file_kind=file_kind,
            file_path=file_path,
            line=line,
            raw=raw,
            head=head,
            entities=sorted(ents),
        ))
        next_id += 1
    return atoms, errors


def _build_index(root: str) -> BioIndex:
    file_specs = list(_walk_metta_files(root))
    if not file_specs:
        raise ValueError(
            f"No .metta files found under '{root}'. "
            "Expected BioCypher output structure with subdirectories containing .metta files."
        )
    sig = _compute_signature(root)
    idx = BioIndex(root=root, signature=sig, files_scanned=len(file_specs))
    offset = 0
    for fp, rg, fk in file_specs:
        new_atoms, errs = _parse_file_into_atoms(fp, rg, fk, id_offset=offset)
        idx.parse_errors += errs
        for atom in new_atoms:
            idx.atoms.append(atom)
            idx.by_folder[rg].append(atom.atom_id)
            idx.by_head[atom.head].append(atom.atom_id)
            for et, ei in atom.entities:
                nt, ni = _norm_type(et), _norm_id(ei)
                idx.by_entity[(nt, ni)].append(atom.atom_id)
                idx.by_entity_id[ni].append(atom.atom_id)
        offset += len(new_atoms)
    return idx


def _ensure_index(root: str, force: bool = False) -> BioIndex:
    abs_root = os.path.abspath(root)
    if not os.path.isdir(abs_root):
        raise ValueError(f"Output folder not found: '{root}'")
    sig = _compute_signature(abs_root)
    cached = _INDEX_CACHE.get(abs_root)
    if not force and cached is not None and cached.signature == sig:
        return cached
    idx = _build_index(abs_root)
    _INDEX_CACHE[abs_root] = idx
    return idx


def _fmt_summary(idx: BioIndex) -> str:
    return (
        f"indexed root={idx.root} files={idx.files_scanned} "
        f"atoms={len(idx.atoms)} relations={len(idx.by_folder)} "
        f"predicates={len(idx.by_head)} parse_errors={idx.parse_errors}"
    )


def _dedup(ids: List[int]) -> List[int]:
    seen: Set[int] = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _fmt_atom_records(idx: BioIndex, atom_ids: List[int], limit: int = 20) -> str:
    if not atom_ids:
        return "no matches"
    lines = [f"matches={len(atom_ids)} showing={min(limit, len(atom_ids))}"]
    for aid in atom_ids[:limit]:
        a = idx.atoms[aid]
        rel = os.path.relpath(a.file_path, idx.root)
        lines.append(f"[{a.relation_group}/{a.file_kind}] {rel}:{a.line} {a.raw}")
    if len(atom_ids) > limit:
        lines.append(f"... {len(atom_ids) - limit} more")
    return "\n".join(lines)


def _fmt_raw_atoms(idx: BioIndex, atom_ids: List[int], limit: int = 500) -> str:
    """Return bare MeTTa s-expressions, one per line — for neuro-symbolic injection."""
    if not atom_ids:
        return ""
    parts = []
    for aid in atom_ids[:limit]:
        parts.append(idx.atoms[aid].raw)
    if len(atom_ids) > limit:
        parts.append(f"; ... {len(atom_ids) - limit} more atoms truncated")
    return "\n".join(parts)


#query dispatcher
def _help_text() -> str:
    return (
        "bio-query commands:\n"
        "  stats                        — index summary + top relations/predicates\n"
        "  folders                      — list all relation groups with atom counts\n"
        "  predicates                   — list all predicate heads with atom counts\n"
        "  folder   <group>             — all atoms in a relation group\n"
        "  predicate <name>             — all atoms with this predicate head\n"
        "  node     <type> <id>         — atoms containing (type id)\n"
        "  entity   <id>               — atoms containing id (any type)\n"
    )


def _q_stats(idx: BioIndex) -> str:
    folders = sorted(idx.by_folder.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    preds = sorted(idx.by_head.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    top_f = " ".join(f"{k}:{len(v)}" for k, v in folders[:10])
    top_p = " ".join(f"{k}:{len(v)}" for k, v in preds[:10])
    return f"{_fmt_summary(idx)}\ntop_relations {top_f}\ntop_predicates {top_p}"


def _q_folders(idx: BioIndex) -> str:
    items = sorted(idx.by_folder.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return "\n".join(f"{k} atoms={len(v)}" for k, v in items)


def _q_predicates(idx: BioIndex) -> str:
    items = sorted(idx.by_head.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return "\n".join(f"{k} atoms={len(v)}" for k, v in items)


def _q_node(idx: BioIndex, args: List[str]) -> str:
    if len(args) < 2:
        return "usage: node <entity_type> <entity_id>"
    ids = _dedup(idx.by_entity.get((_norm_type(args[0]), _norm_id(args[1])), []))
    return _fmt_atom_records(idx, ids)


def _q_entity(idx: BioIndex, args: List[str]) -> str:
    if not args:
        return "usage: entity <entity_id>"
    ids = _dedup(idx.by_entity_id.get(_norm_id(args[0]), []))
    return _fmt_atom_records(idx, ids)


def _q_predicate(idx: BioIndex, args: List[str]) -> str:
    if not args:
        return "usage: predicate <name>"
    ids = _dedup(idx.by_head.get(args[0], []))
    return _fmt_atom_records(idx, ids)


def _q_folder(idx: BioIndex, args: List[str]) -> str:
    if not args:
        return "usage: folder <relation_group>"
    ids = _dedup(idx.by_folder.get(args[0], []))
    return _fmt_atom_records(idx, ids)


def _dispatch(idx: BioIndex, query: str, raw_metta: bool = False) -> str:
    try:
        parts = shlex.split(query)
    except ValueError as exc:
        return f"query parse error: {exc}"
    if not parts:
        return _help_text()
    cmd, args = parts[0].lower(), parts[1:]
    if cmd == "help":
        return _help_text()
    if cmd == "stats":
        return _q_stats(idx)
    if cmd == "folders":
        return _q_folders(idx)
    if cmd == "predicates":
        return _q_predicates(idx)
    if cmd == "folder":
        ids = _dedup(idx.by_folder.get(args[0] if args else "", []))
        if raw_metta:
            return _fmt_raw_atoms(idx, ids)
        return _q_folder(idx, args)
    if cmd == "predicate":
        ids = _dedup(idx.by_head.get(args[0] if args else "", []))
        if raw_metta:
            return _fmt_raw_atoms(idx, ids)
        return _q_predicate(idx, args)
    if cmd == "node":
        if len(args) < 2:
            return "usage: node <entity_type> <entity_id>"
        ids = _dedup(idx.by_entity.get((_norm_type(args[0]), _norm_id(args[1])), []))
        if raw_metta:
            return _fmt_raw_atoms(idx, ids)
        return _fmt_atom_records(idx, ids)
    if cmd == "entity":
        if not args:
            return "usage: entity <entity_id>"
        ids = _dedup(idx.by_entity_id.get(_norm_id(args[0]), []))
        if raw_metta:
            return _fmt_raw_atoms(idx, ids)
        return _q_entity(idx, args)
    return f"unknown command: {cmd}\n{_help_text()}"

# Path-finding algorithm:
#   1. Build an adjacency map: entity_id → [atom_ids that mention it]
#   2. BFS from src_id, expanding to all entity_ids that appear in those atoms
#   3. Stop when dst_id is reached or max_hops exceeded
#   4. Backtrack to extract the edge atoms along the shortest path
#   5. Return those atoms as raw MeTTa s-expressions

def _build_adjacency(idx: BioIndex) -> Dict[str, Set[str]]:
    """entity_id (normalised) → set of entity_ids co-occurring in the same atom."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    for atom in idx.atoms:
        nids = [_norm_id(ei) for _, ei in atom.entities]
        for nid in nids:
            for other in nids:
                if other != nid:
                    adj[nid].add(other)
    return adj


def _bfs_path(adjacency: Dict[str, Set[str]], src: str, dst: str,
              max_hops: int = 5) -> Optional[List[str]]:
    """Return the shortest entity-id path from src to dst, or None."""
    if src == dst:
        return [src]
    visited = {src}
    # queue of paths
    queue = [[src]]
    while queue:
        path = queue.pop(0)
        if len(path) > max_hops:
            return None
        current = path[-1]
        for neighbour in adjacency.get(current, set()):
            if neighbour == dst:
                return path + [dst]
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(path + [neighbour])
    return None


def _atoms_on_edge(idx: BioIndex, id_a: str, id_b: str) -> List[int]:
    """Return atom_ids where both id_a and id_b appear as entities."""
    set_a = set(idx.by_entity_id.get(id_a, []))
    set_b = set(idx.by_entity_id.get(id_b, []))
    return list(set_a & set_b)


def bio_index(root: str) -> str:
    """Build or reuse the full in-memory index for *root*. Returns a summary string."""
    try:
        idx = _ensure_index(root, force=False)
        return _fmt_summary(idx)
    except Exception as exc:
        return f"bio_index error: {exc}"


def bio_reindex(root: str) -> str:
    """Force-rebuild the index for *root*, bypassing the signature cache."""
    try:
        idx = _ensure_index(root, force=True)
        return _fmt_summary(idx)
    except Exception as exc:
        return f"bio_reindex error: {exc}"


def bio_query(root: str, query: str) -> str:
    """Run a structured query against the full index"""
    try:
        idx = _ensure_index(root, force=False)
        return _dispatch(idx, query, raw_metta=False)
    except Exception as exc:
        return f"bio_query error: {exc}"


def bio_extract(root: str, query: str) -> str:
    """Like bio_query but returns raw MeTTa s-expressions for symbolic injection.

    The output can be fed directly into the ``metta`` skill to assert facts
    to run PLN / NAL inference over them.
    """
    try:
        idx = _ensure_index(root, force=False)
        return _dispatch(idx, query, raw_metta=True)
    except Exception as exc:
        return f"bio_extract error: {exc}"


def bio_path(root: str, src_id: str, dst_id: str, max_hops: int = 5) -> str:
    """BFS shortest path between two biological entities."""
    try:
        idx = _ensure_index(root, force=False)
    except Exception as exc:
        return f"bio_path error: {exc}"

    src_norm = _norm_id(src_id)
    dst_norm = _norm_id(dst_id)

    if src_norm not in idx.by_entity_id:
        return f"bio_path: source entity '{src_id}' not found in index"
    if dst_norm not in idx.by_entity_id:
        return f"bio_path: destination entity '{dst_id}' not found in index"

    adjacency = _build_adjacency(idx)
    path = _bfs_path(adjacency, src_norm, dst_norm, max_hops=int(max_hops))

    if path is None:
        return f"bio_path: no path found between '{src_id}' and '{dst_id}' within {max_hops} hops"

    # Collect edge atoms for each hop
    all_atom_ids: List[int] = []
    seen_aids: Set[int] = set()
    for i in range(len(path) - 1):
        edge_aids = _atoms_on_edge(idx, path[i], path[i + 1])
        for aid in edge_aids:
            if aid not in seen_aids:
                seen_aids.add(aid)
                all_atom_ids.append(aid)

    header = f"; bio-path {src_id} -> {dst_id}  hops={len(path)-1}  via={' -> '.join(path)}"
    body = _fmt_raw_atoms(idx, all_atom_ids)
    return f"{header}\n{body}" if body else f"{header}\n; (no connecting atoms found)"
