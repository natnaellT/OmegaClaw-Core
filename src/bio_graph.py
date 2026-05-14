from __future__ import annotations

import os
import shlex
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Sequence, Set, Tuple, Union

Term = Union[str, List["Term"]]


@dataclass
class AtomRecord:
    atom_id: int
    relation_group: str
    file_kind: str
    file_path: str
    line: int
    raw: str
    head: str
    entities: List[Tuple[str, str]]


@dataclass
class BioIndex:
    root: str
    signature: Tuple[int, int, int]
    files_scanned: int = 0
    parse_errors: int = 0
    atoms: List[AtomRecord] = field(default_factory=list)
    by_folder: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))
    by_head: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))
    by_entity: Dict[Tuple[str, str], List[int]] = field(default_factory=lambda: defaultdict(list))
    by_entity_id: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))


_CACHE: Dict[str, BioIndex] = {}


def _normalize_entity_type(entity_type: str) -> str:
    return entity_type.strip().lower()


def _normalize_entity_id(entity_id: str) -> str:
    return entity_id.strip().lower()


def _strip_line_comments(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        if ";" in line:
            line = line.split(";", 1)[0]
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _iter_top_level_atoms(text: str) -> Iterator[Tuple[str, int]]:
    depth = 0
    start = -1
    start_line = 1
    line = 1

    for idx, char in enumerate(text):
        if char == "\n":
            line += 1

        if char == "(":
            if depth == 0:
                start = idx
                start_line = line
            depth += 1
            continue

        if char == ")":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                atom = text[start : idx + 1].strip()
                if atom:
                    yield atom, start_line
                start = -1


def _tokenize(atom: str) -> List[str]:
    tokens: List[str] = []
    current: List[str] = []
    in_string = False
    escaped = False

    def flush_current() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    for char in atom:
        if in_string:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                flush_current()
            continue

        if char.isspace():
            flush_current()
            continue

        if char == '"':
            flush_current()
            in_string = True
            current.append(char)
            continue

        if char in "()":
            flush_current()
            tokens.append(char)
            continue

        current.append(char)

    flush_current()
    return tokens


def _parse_term(tokens: Sequence[str], i: int = 0) -> Tuple[Term, int]:
    if i >= len(tokens):
        raise ValueError("Unexpected end of token stream")

    token = tokens[i]
    if token != "(":
        if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
            return token[1:-1], i + 1
        return token, i + 1

    i += 1
    out: List[Term] = []
    while i < len(tokens) and tokens[i] != ")":
        term, i = _parse_term(tokens, i)
        out.append(term)

    if i >= len(tokens) or tokens[i] != ")":
        raise ValueError("Unbalanced parentheses")

    return out, i + 1


def _parse_atom(atom: str) -> Term:
    tokens = _tokenize(atom)
    parsed, idx = _parse_term(tokens, 0)
    if idx != len(tokens):
        raise ValueError("Trailing tokens after parse")
    return parsed


def _collect_entities(term: Term, out: Set[Tuple[str, str]]) -> None:
    if isinstance(term, str):
        return

    if len(term) == 2 and isinstance(term[0], str) and isinstance(term[1], str):
        out.add((term[0], term[1]))

    for child in term[1:]:
        _collect_entities(child, out)


def _walk_metta_files(root: str) -> Iterator[Tuple[str, str, str]]:
    for dirpath, _, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        relation_group = rel_dir.split(os.sep, 1)[0] if rel_dir != "." else "_root"

        for filename in sorted(filenames):
            if not filename.endswith(".metta"):
                continue
            file_path = os.path.join(dirpath, filename)
            file_kind = os.path.splitext(filename)[0].lower()
            yield file_path, relation_group, file_kind


def _compute_signature(file_paths: List[str]) -> Tuple[int, int, int]:
    latest_mtime = 0
    total_size = 0
    for path in file_paths:
        stat = os.stat(path)
        latest_mtime = max(latest_mtime, int(stat.st_mtime))
        total_size += int(stat.st_size)
    return len(file_paths), latest_mtime, total_size


def _build_index(output_root: str) -> BioIndex:
    file_specs = list(_walk_metta_files(output_root))
    file_paths = [spec[0] for spec in file_specs]
    signature = _compute_signature(file_paths)

    index = BioIndex(root=output_root, signature=signature)
    index.files_scanned = len(file_specs)

    next_atom_id = 0
    for file_path, relation_group, file_kind in file_specs:
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            content = _strip_line_comments(handle.read())

        for atom_raw, line in _iter_top_level_atoms(content):
            try:
                parsed = _parse_atom(atom_raw)
            except ValueError:
                index.parse_errors += 1
                continue

            if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], str):
                index.parse_errors += 1
                continue

            head = parsed[0]
            entities: Set[Tuple[str, str]] = set()
            _collect_entities(parsed, entities)
            sorted_entities = sorted(entities)

            record = AtomRecord(
                atom_id=next_atom_id,
                relation_group=relation_group,
                file_kind=file_kind,
                file_path=file_path,
                line=line,
                raw=atom_raw,
                head=head,
                entities=sorted_entities,
            )
            index.atoms.append(record)

            index.by_folder[relation_group].append(next_atom_id)
            index.by_head[head].append(next_atom_id)

            for entity_type, entity_id in sorted_entities:
                t_norm = _normalize_entity_type(entity_type)
                i_norm = _normalize_entity_id(entity_id)
                index.by_entity[(t_norm, i_norm)].append(next_atom_id)
                index.by_entity_id[i_norm].append(next_atom_id)

            next_atom_id += 1

    return index


def _format_summary(index: BioIndex) -> str:
    relation_count = len(index.by_folder)
    predicate_count = len(index.by_head)
    return (
        f"indexed root={index.root} files={index.files_scanned} atoms={len(index.atoms)} "
        f"relations={relation_count} predicates={predicate_count} parse_errors={index.parse_errors}"
    )


def _ensure_index(output_root: str, force: bool = False) -> BioIndex:
    root = os.path.abspath(output_root)

    if not os.path.isdir(root):
        raise ValueError(f"output folder not found: {output_root}")

    file_paths = [spec[0] for spec in _walk_metta_files(root)]
    if not file_paths:
        raise ValueError(
            f"no .metta files found under {output_root}; expected folders like "
            f"{output_root}/gene/nodes.metta and {output_root}/gene/edges.metta"
        )

    signature = _compute_signature(file_paths)
    cached = _CACHE.get(root)

    if not force and cached is not None and cached.signature == signature:
        return cached

    index = _build_index(root)
    _CACHE[root] = index
    return index


def _pick_unique(ids: List[int]) -> List[int]:
    seen = set()
    out = []
    for atom_id in ids:
        if atom_id in seen:
            continue
        seen.add(atom_id)
        out.append(atom_id)
    return out


def _format_records(index: BioIndex, atom_ids: List[int], limit: int = 20) -> str:
    if not atom_ids:
        return "no matches"

    lines = [f"matches={len(atom_ids)} showing={min(limit, len(atom_ids))}"]
    for atom_id in atom_ids[:limit]:
        record = index.atoms[atom_id]
        rel_path = os.path.relpath(record.file_path, index.root)
        lines.append(
            f"[{record.relation_group}/{record.file_kind}] {rel_path}:{record.line} {record.raw}"
        )

    if len(atom_ids) > limit:
        lines.append(f"... truncated {len(atom_ids) - limit} more")

    return "\n".join(lines)


def _query_stats(index: BioIndex) -> str:
    by_folder = sorted(
        ((folder, len(ids)) for folder, ids in index.by_folder.items()),
        key=lambda item: (-item[1], item[0]),
    )
    top_folders = " ".join(f"{name}:{count}" for name, count in by_folder[:10])

    by_pred = sorted(
        ((head, len(ids)) for head, ids in index.by_head.items()),
        key=lambda item: (-item[1], item[0]),
    )
    top_preds = " ".join(f"{name}:{count}" for name, count in by_pred[:10])

    return (
        f"{_format_summary(index)}\n"
        f"top_relations {top_folders}\n"
        f"top_predicates {top_preds}"
    )


def _query_folders(index: BioIndex) -> str:
    items = sorted(
        ((folder, len(ids)) for folder, ids in index.by_folder.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return "\n".join(f"{folder} atoms={count}" for folder, count in items)


def _query_predicates(index: BioIndex) -> str:
    items = sorted(
        ((head, len(ids)) for head, ids in index.by_head.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return "\n".join(f"{head} atoms={count}" for head, count in items)


def _query_entity(index: BioIndex, args: List[str], typed: bool) -> str:
    if typed:
        if len(args) < 2:
            return "usage: node <entity_type> <entity_id>"
        entity_type = _normalize_entity_type(args[0])
        entity_id = _normalize_entity_id(args[1])
        ids = _pick_unique(index.by_entity.get((entity_type, entity_id), []))
        return _format_records(index, ids)

    if not args:
        return "usage: entity <entity_id>"

    entity_id = _normalize_entity_id(args[0])
    ids = _pick_unique(index.by_entity_id.get(entity_id, []))
    return _format_records(index, ids)


def _query_folder(index: BioIndex, args: List[str]) -> str:
    if not args:
        return "usage: folder <relation_group>"

    relation_group = args[0]
    ids = _pick_unique(index.by_folder.get(relation_group, []))
    return _format_records(index, ids)


def _query_predicate(index: BioIndex, args: List[str]) -> str:
    if not args:
        return "usage: predicate <name>"

    predicate = args[0]
    ids = _pick_unique(index.by_head.get(predicate, []))
    return _format_records(index, ids)


def _query_neighbors(index: BioIndex, args: List[str]) -> str:
    if not args:
        return "usage: neighbors <entity_id> OR neighbors <entity_type> <entity_id>"

    typed = len(args) >= 2
    if typed:
        target = (_normalize_entity_type(args[0]), _normalize_entity_id(args[1]))
        ids = _pick_unique(index.by_entity.get(target, []))
        target_set = {target}
    else:
        target_id = _normalize_entity_id(args[0])
        ids = _pick_unique(index.by_entity_id.get(target_id, []))
        target_set = {(entity_type, target_id) for entity_type, target_id2 in index.by_entity if target_id2 == target_id}

    if not ids:
        return "no matches"

    neighbor_counts: Counter[Tuple[str, str]] = Counter()
    supporting_predicates: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)

    for atom_id in ids:
        record = index.atoms[atom_id]
        entities_norm = [
            (_normalize_entity_type(t), _normalize_entity_id(i)) for t, i in record.entities
        ]
        if not any(entity in target_set for entity in entities_norm):
            continue

        for entity_norm, entity_raw in zip(entities_norm, record.entities):
            if entity_norm in target_set:
                continue
            neighbor_counts[entity_raw] += 1
            supporting_predicates[entity_raw][record.head] += 1

    if not neighbor_counts:
        return "no neighbor entities found"

    lines = [
        f"neighbors={len(neighbor_counts)} from_atoms={len(ids)} showing={min(20, len(neighbor_counts))}"
    ]
    for (entity_type, entity_id), count in neighbor_counts.most_common(20):
        top_predicates = supporting_predicates[(entity_type, entity_id)].most_common(3)
        pred_text = ", ".join(f"{name}:{n}" for name, n in top_predicates)
        lines.append(f"{entity_type} {entity_id} count={count} via={pred_text}")

    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "commands:",
            "stats",
            "folders",
            "predicates",
            "entity <entity_id>",
            "node <entity_type> <entity_id>",
            "predicate <name>",
            "folder <relation_group>",
            "neighbors <entity_id>",
            "neighbors <entity_type> <entity_id>",
        ]
    )


def _dispatch_query(index: BioIndex, query: str) -> str:
    try:
        parts = shlex.split(query)
    except ValueError as exc:
        return f"query parse error: {exc}"

    if not parts:
        return _help_text()

    command = parts[0].lower()
    args = parts[1:]

    if command == "help":
        return _help_text()
    if command == "stats":
        return _query_stats(index)
    if command == "folders":
        return _query_folders(index)
    if command == "predicates":
        return _query_predicates(index)
    if command == "entity":
        return _query_entity(index, args, typed=False)
    if command == "node":
        return _query_entity(index, args, typed=True)
    if command == "predicate":
        return _query_predicate(index, args)
    if command == "folder":
        return _query_folder(index, args)
    if command == "neighbors":
        return _query_neighbors(index, args)

    return f"unknown command: {command}\n{_help_text()}"


def bio_index(output_root: str = "output") -> str:
    try:
        index = _ensure_index(output_root, force=False)
        return _format_summary(index)
    except Exception as exc:  # noqa: BLE001
        return f"bio_index error: {exc}"


def bio_reindex(output_root: str = "output") -> str:
    try:
        index = _ensure_index(output_root, force=True)
        return _format_summary(index)
    except Exception as exc:  # noqa: BLE001
        return f"bio_reindex error: {exc}"


def bio_query(query: str, output_root: str = "output") -> str:
    try:
        index = _ensure_index(output_root, force=False)
        return _dispatch_query(index, query)
    except Exception as exc:  # noqa: BLE001
        return f"bio_query error: {exc}"


def bio_query_in(output_root: str, query: str) -> str:
    try:
        index = _ensure_index(output_root, force=False)
        return _dispatch_query(index, query)
    except Exception as exc:  # noqa: BLE001
        return f"bio_query_in error: {exc}"
