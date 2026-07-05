"""Bio-Claw: on-demand biological graph engine for OmegaClaw.

Two-tier architecture:
  Tier 1 — HotIndex: lightweight pointer map (entity/head/folder → file paths).
            Built once per root; invalidated automatically by filesystem signature.
  Tier 2 — ParseCache: bounded LRU of per-file parsed atoms.
            Files are parsed and cached only when a query needs them.

Public API: bio_index · bio_reindex · bio_query · bio_extract · bio_path
"""
from __future__ import annotations

import os
import shlex
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Set, Sequence, Tuple, Union

Term = Union[str, List["Term"]]


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class Atom:
    head: str
    entities: List[Tuple[str, str]]
    raw: str
    relation_group: str
    file_kind: str
    line: int


@dataclass
class HotIndex:
    root: str
    signature: Tuple[int, int, int]
    file_count: int
    atom_count: int
    entity_to_files: Dict[str, Set[str]]
    head_to_files: Dict[str, Set[str]]
    folder_to_files: Dict[str, List[str]]
    folder_counts: Dict[str, int]
    head_counts: Dict[str, int]


# ---------------------------------------------------------------------------
# Tier 1: pointer map cache  |  Tier 2: per-file LRU parse cache
# ---------------------------------------------------------------------------

_INDEX: Dict[str, HotIndex] = {}

_FILE_CACHE: OrderedDict[str, List[Atom]] = OrderedDict()
_FILE_CACHE_MAX = 256


def _cache_get(path: str) -> Optional[List[Atom]]:
    if path not in _FILE_CACHE:
        return None
    _FILE_CACHE.move_to_end(path)
    return _FILE_CACHE[path]


def _cache_set(path: str, atoms: List[Atom]) -> None:
    if path in _FILE_CACHE:
        _FILE_CACHE.move_to_end(path)
    else:
        if len(_FILE_CACHE) >= _FILE_CACHE_MAX:
            _FILE_CACHE.popitem(last=False)
        _FILE_CACHE[path] = atoms


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.strip().lower()


def _strip_comments(text: str) -> str:
    return "\n".join(line.split(";", 1)[0] for line in text.splitlines())


def _iter_atoms(text: str) -> Iterator[Tuple[str, int]]:
    depth, start, start_line, line = 0, -1, 1, 1
    for idx, ch in enumerate(text):
        if ch == "\n":
            line += 1
        if ch == "(":
            if depth == 0:
                start, start_line = idx, line
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                atom = text[start:idx + 1].strip()
                if atom:
                    yield atom, start_line
                start = -1


def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    cur: List[str] = []
    in_str = escaped = False

    def flush() -> None:
        if cur:
            tokens.append("".join(cur))
            cur.clear()

    for ch in text:
        if in_str:
            cur.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
                flush()
        elif ch.isspace():
            flush()
        elif ch == '"':
            flush()
            in_str = True
            cur.append(ch)
        elif ch in "()":
            flush()
            tokens.append(ch)
        else:
            cur.append(ch)
    flush()
    return tokens


def _parse_term(tokens: Sequence[str], i: int = 0) -> Tuple[Term, int]:
    if i >= len(tokens):
        raise ValueError("Unexpected end of tokens")
    tok = tokens[i]
    if tok != "(":
        return (tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] == '"' else tok), i + 1
    i += 1
    out: List[Term] = []
    while i < len(tokens) and tokens[i] != ")":
        term, i = _parse_term(tokens, i)
        out.append(term)
    if i >= len(tokens):
        raise ValueError("Unbalanced parentheses")
    return out, i + 1


def _parse_atom_raw(raw: str) -> Term:
    tokens = _tokenize(raw)
    parsed, consumed = _parse_term(tokens)
    if consumed != len(tokens):
        raise ValueError("Trailing tokens")
    return parsed


def _collect_entities(term: Term, out: Set[Tuple[str, str]]) -> None:
    if isinstance(term, str):
        return
    if len(term) == 2 and all(isinstance(c, str) for c in term):
        out.add((term[0], term[1]))
    for child in term[1:]:
        _collect_entities(child, out)


def _parse_file(file_path: str, relation_group: str, file_kind: str) -> List[Atom]:
    cached = _cache_get(file_path)
    if cached is not None:
        return cached

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            content = _strip_comments(fh.read())
    except OSError:
        return []

    atoms: List[Atom] = []
    for raw, line in _iter_atoms(content):
        try:
            parsed = _parse_atom_raw(raw)
        except ValueError:
            continue
        if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], str):
            continue
        ents: Set[Tuple[str, str]] = set()
        _collect_entities(parsed, ents)
        atoms.append(Atom(
            head=parsed[0],
            entities=sorted(ents),
            raw=raw,
            relation_group=relation_group,
            file_kind=file_kind,
            line=line,
        ))

    _cache_set(file_path, atoms)
    return atoms


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _walk_files(root: str) -> Iterator[Tuple[str, str, str]]:
    for dirpath, _, names in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        group = rel.split(os.sep, 1)[0] if rel != "." else "_root"
        for name in sorted(names):
            if name.endswith(".metta"):
                yield os.path.join(dirpath, name), group, os.path.splitext(name)[0].lower()


def _signature(root: str) -> Tuple[int, int, int]:
    files = [fp for fp, _, _ in _walk_files(root)]
    if not files:
        return 0, 0, 0
    mtime = max(int(os.stat(fp).st_mtime) for fp in files)
    size = sum(os.stat(fp).st_size for fp in files)
    return len(files), mtime, size


# ---------------------------------------------------------------------------
# Tier 1 build: streaming scan — pointer maps only, no atom storage
# ---------------------------------------------------------------------------

def _build(root: str) -> HotIndex:
    specs = list(_walk_files(root))
    if not specs:
        raise ValueError(f"No .metta files found under '{root}'")

    sig = _signature(root)
    entity_to_files: Dict[str, Set[str]] = defaultdict(set)
    head_to_files: Dict[str, Set[str]] = defaultdict(set)
    folder_to_files: Dict[str, List[str]] = defaultdict(list)
    folder_counts: Dict[str, int] = defaultdict(int)
    head_counts: Dict[str, int] = defaultdict(int)
    atom_count = 0

    for fp, group, kind in specs:
        folder_to_files[group].append(fp)
        for atom in _parse_file(fp, group, kind):
            atom_count += 1
            folder_counts[group] += 1
            head_counts[atom.head] += 1
            head_to_files[atom.head].add(fp)
            for _, eid in atom.entities:
                entity_to_files[_norm(eid)].add(fp)

    return HotIndex(
        root=root,
        signature=sig,
        file_count=len(specs),
        atom_count=atom_count,
        entity_to_files=dict(entity_to_files),
        head_to_files=dict(head_to_files),
        folder_to_files=dict(folder_to_files),
        folder_counts=dict(folder_counts),
        head_counts=dict(head_counts),
    )


def _ensure(root: str, force: bool = False) -> HotIndex:
    abs_root = os.path.abspath(root)
    if not os.path.isdir(abs_root):
        raise ValueError(f"Output folder not found: '{root}'")
    sig = _signature(abs_root)
    cached = _INDEX.get(abs_root)
    if not force and cached and cached.signature == sig:
        return cached
    idx = _build(abs_root)
    _INDEX[abs_root] = idx
    return idx


# ---------------------------------------------------------------------------
# On-demand atom retrieval (Tier 2 — reads only what the query needs)
# ---------------------------------------------------------------------------

def _resolve_file_meta(idx: HotIndex, fp: str) -> Tuple[str, str]:
    for group, files in idx.folder_to_files.items():
        if fp in files:
            return group, os.path.splitext(os.path.basename(fp))[0].lower()
    return "_root", os.path.splitext(os.path.basename(fp))[0].lower()


def _atoms_for_entity(idx: HotIndex, entity_id: str,
                       entity_type: Optional[str] = None) -> List[Atom]:
    norm_id = _norm(entity_id)
    norm_type = _norm(entity_type) if entity_type else None
    result: List[Atom] = []
    for fp in idx.entity_to_files.get(norm_id, set()):
        group, kind = _resolve_file_meta(idx, fp)
        for atom in _parse_file(fp, group, kind):
            for et, ei in atom.entities:
                if _norm(ei) == norm_id and (norm_type is None or _norm(et) == norm_type):
                    result.append(atom)
                    break
    return result


def _atoms_for_head(idx: HotIndex, head: str) -> List[Atom]:
    result: List[Atom] = []
    for fp in idx.head_to_files.get(head, set()):
        group, kind = _resolve_file_meta(idx, fp)
        result.extend(a for a in _parse_file(fp, group, kind) if a.head == head)
    return result


def _atoms_for_folder(idx: HotIndex, group: str) -> List[Atom]:
    result: List[Atom] = []
    for fp in idx.folder_to_files.get(group, []):
        _, kind = _resolve_file_meta(idx, fp)
        result.extend(_parse_file(fp, group, kind))
    return result


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _fmt_records(atoms: List[Atom], limit: int = 20) -> str:
    if not atoms:
        return "no matches"
    lines = [f"matches={len(atoms)} showing={min(limit, len(atoms))}"]
    for a in atoms[:limit]:
        lines.append(f"[{a.relation_group}/{a.file_kind}]:{a.line} {a.raw}")
    if len(atoms) > limit:
        lines.append(f"... {len(atoms) - limit} more")
    return "\n".join(lines)


def _fmt_raw(atoms: List[Atom], limit: int = 500) -> str:
    parts = [a.raw for a in atoms[:limit]]
    if len(atoms) > limit:
        parts.append(f"; ... {len(atoms) - limit} more atoms truncated")
    return "\n".join(parts)


def _help() -> str:
    return (
        "commands: stats | folders | predicates | "
        "folder <group> | predicate <name> | node <type> <id> | entity <id>"
    )


# ---------------------------------------------------------------------------
# Query dispatcher
# ---------------------------------------------------------------------------

def _dispatch(idx: HotIndex, query: str, raw: bool = False) -> str:
    try:
        parts = shlex.split(query)
    except ValueError as exc:
        return f"query parse error: {exc}"
    if not parts:
        return _help()

    cmd, args = parts[0].lower(), parts[1:]

    if cmd == "help":
        return _help()

    if cmd == "stats":
        top_f = " ".join(f"{k}:{v}" for k, v in
                         sorted(idx.folder_counts.items(), key=lambda x: -x[1])[:10])
        top_p = " ".join(f"{k}:{v}" for k, v in
                         sorted(idx.head_counts.items(), key=lambda x: -x[1])[:10])
        return (
            f"root={idx.root} files={idx.file_count} atoms={idx.atom_count} "
            f"relations={len(idx.folder_counts)} predicates={len(idx.head_counts)}\n"
            f"top_relations {top_f}\ntop_predicates {top_p}"
        )

    if cmd == "folders":
        return "\n".join(
            f"{k} atoms={v}"
            for k, v in sorted(idx.folder_counts.items(), key=lambda x: -x[1])
        )

    if cmd == "predicates":
        return "\n".join(
            f"{k} atoms={v}"
            for k, v in sorted(idx.head_counts.items(), key=lambda x: -x[1])
        )

    if cmd == "folder":
        if not args:
            return "usage: folder <group>"
        atoms = _atoms_for_folder(idx, args[0])
        return _fmt_raw(atoms) if raw else _fmt_records(atoms)

    if cmd == "predicate":
        if not args:
            return "usage: predicate <name>"
        atoms = _atoms_for_head(idx, args[0])
        return _fmt_raw(atoms) if raw else _fmt_records(atoms)

    if cmd == "node":
        if len(args) < 2:
            return "usage: node <type> <id>"
        atoms = _atoms_for_entity(idx, args[1], args[0])
        return _fmt_raw(atoms) if raw else _fmt_records(atoms)

    if cmd == "entity":
        if not args:
            return "usage: entity <id>"
        atoms = _atoms_for_entity(idx, args[0])
        return _fmt_raw(atoms) if raw else _fmt_records(atoms)

    return f"unknown command: {cmd}\n{_help()}"


# ---------------------------------------------------------------------------
# Demand-driven BFS (never builds a full adjacency map)
# ---------------------------------------------------------------------------

def _neighbors(idx: HotIndex, entity_id: str) -> Set[str]:
    norm_id = _norm(entity_id)
    neighbors: Set[str] = set()
    for fp in idx.entity_to_files.get(norm_id, set()):
        group, kind = _resolve_file_meta(idx, fp)
        for atom in _parse_file(fp, group, kind):
            atom_nids = {_norm(ei) for _, ei in atom.entities}
            if norm_id in atom_nids:
                neighbors.update(atom_nids - {norm_id})
    return neighbors


def _bfs(idx: HotIndex, src: str, dst: str, max_hops: int) -> Optional[List[str]]:
    src_n, dst_n = _norm(src), _norm(dst)
    if src_n == dst_n:
        return [src_n]
    visited = {src_n}
    queue: List[List[str]] = [[src_n]]
    while queue:
        path = queue.pop(0)
        if len(path) > max_hops:
            return None
        for nb in _neighbors(idx, path[-1]):
            if nb == dst_n:
                return path + [dst_n]
            if nb not in visited:
                visited.add(nb)
                queue.append(path + [nb])
    return None


def _edge_atoms(idx: HotIndex, id_a: str, id_b: str) -> List[Atom]:
    na, nb = _norm(id_a), _norm(id_b)
    result: List[Atom] = []
    seen_raw: Set[str] = set()
    for fp in idx.entity_to_files.get(na, set()):
        group, kind = _resolve_file_meta(idx, fp)
        for atom in _parse_file(fp, group, kind):
            if atom.raw in seen_raw:
                continue
            nids = {_norm(ei) for _, ei in atom.entities}
            if na in nids and nb in nids:
                seen_raw.add(atom.raw)
                result.append(atom)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def bio_index(root: str) -> str:
    try:
        idx = _ensure(root)
        return (
            f"indexed root={idx.root} files={idx.file_count} atoms={idx.atom_count} "
            f"relations={len(idx.folder_counts)} predicates={len(idx.head_counts)}"
        )
    except Exception as exc:
        return f"bio_index error: {exc}"


def bio_reindex(root: str) -> str:
    try:
        idx = _ensure(root, force=True)
        return (
            f"indexed root={idx.root} files={idx.file_count} atoms={idx.atom_count} "
            f"relations={len(idx.folder_counts)} predicates={len(idx.head_counts)}"
        )
    except Exception as exc:
        return f"bio_reindex error: {exc}"


def bio_query(root: str, query: str) -> str:
    try:
        return _dispatch(_ensure(root), query, raw=False)
    except Exception as exc:
        return f"bio_query error: {exc}"


def bio_extract(root: str, query: str) -> str:
    try:
        return _dispatch(_ensure(root), query, raw=True)
    except Exception as exc:
        return f"bio_extract error: {exc}"


def bio_path(root: str, src_id: str, dst_id: str, max_hops: int = 5) -> str:
    try:
        idx = _ensure(root)
    except Exception as exc:
        return f"bio_path error: {exc}"

    if _norm(src_id) not in idx.entity_to_files:
        return f"bio_path: source '{src_id}' not found"
    if _norm(dst_id) not in idx.entity_to_files:
        return f"bio_path: destination '{dst_id}' not found"

    path = _bfs(idx, src_id, dst_id, max_hops=int(max_hops))
    if path is None:
        return f"bio_path: no path within {max_hops} hops between '{src_id}' and '{dst_id}'"

    atoms: List[Atom] = []
    seen: Set[str] = set()
    for i in range(len(path) - 1):
        for atom in _edge_atoms(idx, path[i], path[i + 1]):
            if atom.raw not in seen:
                seen.add(atom.raw)
                atoms.append(atom)

    header = f"; bio-path {src_id} -> {dst_id}  hops={len(path)-1}  via={' -> '.join(path)}"
    body = _fmt_raw(atoms)
    return f"{header}\n{body}" if body else f"{header}\n; (no connecting atoms found)"
