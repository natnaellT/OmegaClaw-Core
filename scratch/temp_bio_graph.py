"""Bio-Claw v3 — Production-grade biological knowledge graph engine.

Three-tier lazy architecture
============================
  Tier 0  Discovery    bin/bio-index (outside janus sandbox)
  Tier 1  SQLite Index  regex-scanned entity/head pointers (lean dictionary mapping)
                        persistent on disk, incremental per-file invalidation
  Tier 2  Demand Parse  full S-expr parsing only for atoms a query touches
                        byte-offset zero-copy retrieval from source files

Design principles
-----------------
  Lazy         nothing is fully parsed until a query demands it
  Incremental  only new / changed files are re-scanned
  Persistent   SQLite index survives process restarts
  Bounded      configurable limits on every result set
  Robust       graceful degradation on every error path

Public API (unchanged from v1):
  bio_index · bio_reindex · bio_query · bio_extract · bio_path
"""
from __future__ import annotations

import os
import re
import shlex
import sqlite3
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from typing import (
    Dict, Iterator, List, Optional, Set, Sequence, Tuple, Union,
)

# ───────────────────────────────────────────────────────────────────
# Configuration
# ───────────────────────────────────────────────────────────────────

DISPLAY_LIMIT = 20      # max atoms in human-readable output
RAW_LIMIT     = 500     # max atoms in raw / extract output
BFS_MAX_HOPS  = 5       # default path-finding depth

# ───────────────────────────────────────────────────────────────────
# Domain types
# ───────────────────────────────────────────────────────────────────

Term = Union[str, List["Term"]]


@dataclass(frozen=True)
class Atom:
    """Immutable representation of a single parsed MeTTa atom."""
    head:     str
    entities: Tuple[Tuple[str, str], ...]   # ((type, id), …)
    raw:      str
    group:    str
    kind:     str
    line:     int


@dataclass
class Stats:
    """Summary snapshot of the index state."""
    root:   str
    files:  int
    atoms:  int
    groups: Dict[str, int]
    heads:  Dict[str, int]


# ───────────────────────────────────────────────────────────────────
# Tier 2 helpers — full S-expression parser  (used ONLY on demand)
# ───────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Lex a MeTTa string into tokens (parentheses, quoted strings, symbols)."""
    tokens: List[str] = []
    cur: List[str] = []
    in_str = escaped = False

    def _flush():
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
                _flush()
        elif ch.isspace():
            _flush()
        elif ch == '"':
            _flush()
            in_str = True
            cur.append(ch)
        elif ch in "()":
            _flush()
            tokens.append(ch)
        else:
            cur.append(ch)
    _flush()
    return tokens


def _parse_term(tokens: Sequence[str], i: int = 0) -> Tuple[Term, int]:
    if i >= len(tokens):
        raise ValueError("Unexpected end of tokens")
    tok = tokens[i]
    if tok != "(":
        return (tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] == '"'
                else tok), i + 1
    i += 1
    out: List[Term] = []
    while i < len(tokens) and tokens[i] != ")":
        term, i = _parse_term(tokens, i)
        out.append(term)
    if i >= len(tokens):
        raise ValueError("Unbalanced parentheses")
    return out, i + 1


def _collect_entities(term: Term, out: Set[Tuple[str, str]]) -> None:
    """Recursively collect (type, id) leaf pairs from a parsed term."""
    if isinstance(term, str):
        return
    if (len(term) == 2
            and isinstance(term[0], str)
            and isinstance(term[1], str)):
        out.add((term[0], term[1]))
    for child in term[1:]:
        _collect_entities(child, out)


def _strip_comments(text: str) -> str:
    """Remove ; comments while respecting quoted strings."""
    out: List[str] = []
    for line in text.splitlines():
        clean: List[str] = []
        in_str = escaped = False
        for ch in line:
            if in_str:
                clean.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
            elif ch == ";":
                break                       # rest of line is comment
            elif ch == '"':
                in_str = True
                clean.append(ch)
            else:
                clean.append(ch)
        out.append("".join(clean))
    return "\n".join(out)


# ───────────────────────────────────────────────────────────────────
# Tier 1 helpers — lightweight extractors  (no full parse)
# ───────────────────────────────────────────────────────────────────

def _extract_head(raw: str) -> str:
    """Pull the first symbol from a raw atom — O(1), no allocation."""
    i = 1                                   # skip opening '('
    n = len(raw)
    while i < n and raw[i] in " \t\n\r":
        i += 1
    j = i
    while j < n and raw[j] not in " \t\n\r()":
        j += 1
    return raw[i:j] if j > i else "_unknown"


_ENTITY_RE = re.compile(r"\(([a-zA-Z_]\w*)\s+([^\s()]+)\)")


# ───────────────────────────────────────────────────────────────────
# Engine
# ───────────────────────────────────────────────────────────────────

class _Engine:
    """Singleton managing the lifecycle."""

    __slots__ = ("root", "_db_path", "_conn", "_dict_cache", "_readonly")

    def __init__(self) -> None:
        self.root: Optional[str] = None
        self._db_path: Optional[str] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._dict_cache: Dict[str, int] = {}
        self._readonly: bool = True

    def bind(self, root: str, force: bool = False, readonly: bool = True) -> None:
        """Attach to *root*. If force is True, we allow missing index for building."""
        aroot = os.path.abspath(root)
        if not os.path.isdir(aroot):
            raise ValueError(f"Output folder not found: '{root}'")
        if self.root != aroot or self._readonly != readonly:
            self._close()
            self.root = aroot
            self._readonly = readonly
            self._db_path = os.path.join(aroot, ".bioclaw.db")
            if not force and not os.path.exists(self._db_path):
                raise RuntimeError(
                    f"Index missing for {root}. Please run `bin/bio-index` to build it."
                )

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._dict_cache.clear()

    @property
    def db(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._readonly and os.path.exists(self._db_path):
                self._conn = sqlite3.connect(
                    f"file:{self._db_path}?immutable=1",
                    uri=True, timeout=10,
                )
                self._conn.execute("PRAGMA cache_size = -16000")
                self._conn.execute("PRAGMA temp_store = MEMORY")
            else:
                self._conn = sqlite3.connect(self._db_path, timeout=10)
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous  = NORMAL")
                self._conn.execute("PRAGMA cache_size   = -16000")
                self._conn.execute("PRAGMA temp_store   = MEMORY")
                self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS dict (
                did INTEGER PRIMARY KEY,
                val TEXT UNIQUE COLLATE NOCASE
            );
            CREATE TABLE IF NOT EXISTS files (
                fid  INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                grp  TEXT NOT NULL,
                kind TEXT NOT NULL,
                sz   INTEGER NOT NULL,
                mt   REAL    NOT NULL,
                ac   INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS atoms (
                aid  INTEGER PRIMARY KEY AUTOINCREMENT,
                fid  INTEGER NOT NULL,
                hid  INTEGER NOT NULL,
                ln   INTEGER NOT NULL,
                off  INTEGER NOT NULL,
                blen INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ents (
                aid   INTEGER NOT NULL,
                tid   INTEGER NOT NULL,
                eid   TEXT    NOT NULL COLLATE NOCASE
            );
            CREATE INDEX IF NOT EXISTS ix_eid  ON ents (eid);
            CREATE INDEX IF NOT EXISTS ix_tid  ON ents (tid, eid);
            CREATE INDEX IF NOT EXISTS ix_hid  ON atoms (hid);
            CREATE INDEX IF NOT EXISTS ix_afid ON atoms (fid);
            CREATE INDEX IF NOT EXISTS ix_eaid ON ents (aid);
        """)

    def _get_did(self, val: str) -> int:
        if val not in self._dict_cache:
            row = self.db.execute("SELECT did FROM dict WHERE val=? COLLATE NOCASE", (val,)).fetchone()
            if row:
                self._dict_cache[val] = row[0]
            else:
                self.db.execute("INSERT INTO dict (val) VALUES (?)", (val,))
                self._dict_cache[val] = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return self._dict_cache[val]

    def _discover(self) -> List[Tuple[str, str, str]]:
        import glob
        paths = glob.glob(os.path.join(self.root, "**", "*.metta"), recursive=True)
        paths.sort()
        specs: List[Tuple[str, str, str]] = []
        for fp in paths:
            rel = os.path.relpath(os.path.dirname(fp), self.root)
            grp = rel.split(os.sep, 1)[0] if rel != "." else "_root"
            kind = os.path.splitext(os.path.basename(fp))[0].lower()
            specs.append((fp, grp, kind))
        return specs

    def _sync(self, force: bool = False) -> Stats:
        specs = self._discover()
        if not specs:
            raise ValueError(f"No .metta files found under '{self.root}'")

        db = self.db
        indexed: Dict[str, Tuple[int, float, int]] = {}
        if not force:
            for row in db.execute("SELECT path, sz, mt, fid FROM files"):
                indexed[row[0]] = (row[1], row[2], row[3])
        else:
            db.executescript("DELETE FROM ents; DELETE FROM atoms; DELETE FROM files; DELETE FROM dict;")
            self._dict_cache.clear()

        current_paths: Set[str] = set()
        to_scan: List[Tuple[str, str, str, Tuple[int, float]]] = []

        for fp, grp, kind in specs:
            current_paths.add(fp)
            try:
                st = os.stat(fp)
                sig = (st.st_size, st.st_mtime)
            except OSError:
                continue
            if force or fp not in indexed or indexed[fp][:2] != sig:
                to_scan.append((fp, grp, kind, sig))

        if not force:
            deleted = set(indexed) - current_paths
            for dp in deleted:
                fid = indexed[dp][2]
                db.execute("DELETE FROM ents WHERE aid IN (SELECT aid FROM atoms WHERE fid=?)", (fid,))
                db.execute("DELETE FROM atoms WHERE fid=?", (fid,))
                db.execute("DELETE FROM files WHERE fid=?", (fid,))
            if deleted:
                db.commit()

        for fp, grp, kind, sig in to_scan:
            self._scan_file(fp, grp, kind, sig)
        
        if to_scan:
            db.commit()
            db.execute("VACUUM")
            self._close() # Reopen cleanly

        return self._get_stats()

    def _scan_file(self, path: str, grp: str, kind: str, sig: Tuple[int, float]) -> None:
        db = self.db
        old = db.execute("SELECT fid FROM files WHERE path=?", (path,)).fetchone()
        if old:
            fid = old[0]
            db.execute("DELETE FROM ents WHERE aid IN (SELECT aid FROM atoms WHERE fid=?)", (fid,))
            db.execute("DELETE FROM atoms WHERE fid=?", (fid,))
            db.execute("DELETE FROM files WHERE fid=?", (fid,))

        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return

        db.execute(
            "INSERT INTO files (path, grp, kind, sz, mt) VALUES (?,?,?,?,?)",
            (path, grp, kind, sig[0], sig[1]),
        )
        fid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        atom_rows: List[Tuple[int, int, int, int, int]] = []
        atom_ents: List[List[Tuple[int, str]]] = []

        depth = 0
        start = -1
        start_ln = 1
        ln = 1
        in_comment = False
        in_str = False
        escaped = False
        n = len(data)

        for i in range(n):
            b = data[i]
            if b == 0x0A:
                ln += 1
                in_comment = False
                continue
            if in_comment: continue
            if in_str:
                if escaped: escaped = False
                elif b == 0x5C: escaped = True
                elif b == 0x22: in_str = False
                continue
            if b == 0x3B:
                in_comment = True
                continue
            if b == 0x22:
                in_str = True
                continue
            if b == 0x28:
                if depth == 0:
                    start = i
                    start_ln = ln
                depth += 1
            elif b == 0x29 and depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    blen = i + 1 - start
                    raw_text = data[start : i + 1].decode("utf-8", errors="replace")
                    clean = _strip_comments(raw_text)
                    
                    head = _extract_head(clean)
                    hid = self._get_did(head)
                    atom_rows.append((fid, hid, start_ln, start, blen))

                    ents: List[Tuple[int, str]] = [
                        (self._get_did(m.group(1)), m.group(2))
                        for m in _ENTITY_RE.finditer(clean)
                    ]
                    atom_ents.append(ents)
                    start = -1

        if not atom_rows:
            db.execute("UPDATE files SET ac=0 WHERE fid=?", (fid,))
            return

        db.executemany(
            "INSERT INTO atoms (fid, hid, ln, off, blen) VALUES (?,?,?,?,?)",
            atom_rows,
        )
        last_aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        first_aid = last_aid - len(atom_rows) + 1

        ent_rows: List[Tuple[int, int, str]] = []
        for idx, ents in enumerate(atom_ents):
            aid = first_aid + idx
            for tid, eid in ents:
                ent_rows.append((aid, tid, eid))

        if ent_rows:
            db.executemany("INSERT INTO ents (aid, tid, eid) VALUES (?,?,?)", ent_rows)

        db.execute("UPDATE files SET ac=? WHERE fid=?", (len(atom_rows), fid))

    def _read_raw(self, path: str, off: int, blen: int) -> str:
        try:
            with open(path, "rb") as fh:
                fh.seek(off)
                return fh.read(blen).decode("utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _to_atom(self, raw: str, grp: str, kind: str, ln: int) -> Optional[Atom]:
        clean = _strip_comments(raw)
        try:
            parsed = _parse_term(_tokenize(clean))[0]
        except (ValueError, IndexError):
            return None
        if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], str):
            return None
        ents: Set[Tuple[str, str]] = set()
        _collect_entities(parsed, ents)
        return Atom(
            head=parsed[0],
            entities=tuple(sorted(ents)),
            raw=raw,
            group=grp,
            kind=kind,
            line=ln,
        )

    def _rows_to_atoms(self, rows: List[Tuple[str, str, str, int, int, int]]) -> List[Atom]:
        atoms: List[Atom] = []
        for path, grp, kind, ln, off, blen in rows:
            raw = self._read_raw(path, off, blen)
            if raw:
                atom = self._to_atom(raw, grp, kind, ln)
                if atom is not None:
                    atoms.append(atom)
        return atoms

    def query_entity(self, eid: str, etype: Optional[str] = None, limit: int = RAW_LIMIT) -> List[Atom]:
        if etype:
            rows = self.db.execute("""
                SELECT DISTINCT f.path, f.grp, f.kind, a.ln, a.off, a.blen
                FROM   ents e
                JOIN   atoms a ON e.aid = a.aid
                JOIN   files f ON a.fid = f.fid
                JOIN   dict d  ON e.tid = d.did
                WHERE  e.eid = ? AND d.val = ? COLLATE NOCASE
                LIMIT  ?
            """, (eid, etype, limit)).fetchall()
        else:
            rows = self.db.execute("""
                SELECT DISTINCT f.path, f.grp, f.kind, a.ln, a.off, a.blen
                FROM   ents e
                JOIN   atoms a ON e.aid = a.aid
                JOIN   files f ON a.fid = f.fid
                WHERE  e.eid = ? COLLATE NOCASE
                LIMIT  ?
            """, (eid, limit)).fetchall()
        return self._rows_to_atoms(rows)

    def query_head(self, head: str, limit: int = RAW_LIMIT) -> List[Atom]:
        rows = self.db.execute("""
            SELECT f.path, f.grp, f.kind, a.ln, a.off, a.blen
            FROM   atoms a
            JOIN   files f ON a.fid = f.fid
            JOIN   dict d  ON a.hid = d.did
            WHERE  d.val = ? COLLATE NOCASE
            LIMIT  ?
        """, (head, limit)).fetchall()
        return self._rows_to_atoms(rows)

    def query_folder(self, grp: str, limit: int = RAW_LIMIT) -> List[Atom]:
        rows = self.db.execute("""
            SELECT f.path, f.grp, f.kind, a.ln, a.off, a.blen
            FROM   atoms a
            JOIN   files f ON a.fid = f.fid
            WHERE  f.grp = ?
            LIMIT  ?
        """, (grp, limit)).fetchall()
        return self._rows_to_atoms(rows)

    def neighbors(self, eid: str) -> Set[str]:
        rows = self.db.execute("""
            SELECT DISTINCT e2.eid
            FROM   ents e1
            JOIN   ents e2 ON e1.aid = e2.aid
            WHERE  e1.eid = ? COLLATE NOCASE AND e2.eid != ? COLLATE NOCASE
        """, (eid, eid)).fetchall()
        return {r[0].lower() for r in rows}

    def has_entity(self, eid: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM ents WHERE eid = ? COLLATE NOCASE LIMIT 1",
            (eid,),
        ).fetchone() is not None

    def edge_atoms(self, id_a: str, id_b: str) -> List[Atom]:
        rows = self.db.execute("""
            SELECT DISTINCT f.path, f.grp, f.kind, ax.ln, ax.off, ax.blen
            FROM   ents e1
            JOIN   ents e2 ON e1.aid = e2.aid
            JOIN   atoms ax ON e1.aid = ax.aid
            JOIN   files f  ON ax.fid = f.fid
            WHERE  e1.eid = ? COLLATE NOCASE AND e2.eid = ? COLLATE NOCASE
        """, (id_a, id_b)).fetchall()

        atoms: List[Atom] = []
        seen: Set[str] = set()
        for path, grp, kind, ln, off, blen in rows:
            raw = self._read_raw(path, off, blen)
            if raw and raw not in seen:
                seen.add(raw)
                atom = self._to_atom(raw, grp, kind, ln)
                if atom is not None:
                    atoms.append(atom)
        return atoms

    def _get_stats(self) -> Stats:
        db = self.db
        fc = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        ac = db.execute("SELECT COALESCE(SUM(ac), 0) FROM files").fetchone()[0]
        groups = dict(db.execute(
            "SELECT grp, SUM(ac) FROM files GROUP BY grp ORDER BY SUM(ac) DESC"
        ).fetchall())
        
        # Heads logic updated to use dict table
        heads = dict(db.execute("""
            SELECT d.val, COUNT(a.aid) 
            FROM atoms a JOIN dict d ON a.hid = d.did 
            GROUP BY d.val ORDER BY COUNT(a.aid) DESC LIMIT 30
        """).fetchall())
        
        return Stats(
            root=self.root, files=fc, atoms=ac,
            groups=groups, heads=heads,
        )

_E = _Engine()

# ───────────────────────────────────────────────────────────────────
# Formatters
# ───────────────────────────────────────────────────────────────────

def _fmt(atoms: List[Atom], limit: int = DISPLAY_LIMIT) -> str:
    if not atoms: return "no matches"
    lines = [f"matches={len(atoms)} showing={min(limit, len(atoms))}"]
    for a in atoms[:limit]: lines.append(f"[{a.group}/{a.kind}]:{a.line} {a.raw}")
    if len(atoms) > limit: lines.append(f"... {len(atoms) - limit} more")
    return "\n".join(lines)

def _fmt_raw(atoms: List[Atom], limit: int = RAW_LIMIT) -> str:
    parts = [a.raw for a in atoms[:limit]]
    if len(atoms) > limit: parts.append(f"; ... {len(atoms) - limit} more atoms truncated")
    return "\n".join(parts)

def _help() -> str:
    return "commands: stats | folders | predicates | folder <group> | predicate <name> | node <type> <id> | entity <id> | help"

def _dispatch(query: str, raw: bool = False) -> str:
    try: parts = shlex.split(query)
    except ValueError as exc: return f"parse error: {exc}"
    if not parts: return _help()

    cmd, args = parts[0].lower(), parts[1:]
    fmt = _fmt_raw if raw else _fmt

    if cmd == "help": return _help()
    if cmd == "stats":
        s = _E._get_stats()
        top_g = " ".join(f"{k}:{v}" for k, v in sorted(s.groups.items(), key=lambda x: -x[1])[:10])
        top_h = " ".join(f"{k}:{v}" for k, v in sorted(s.heads.items(), key=lambda x: -x[1])[:10])
        return f"root={s.root} files={s.files} atoms={s.atoms} groups={len(s.groups)} predicates={len(s.heads)}\ntop_groups {top_g}\ntop_predicates {top_h}"
    if cmd == "folders":
        s = _E._get_stats()
        return "\n".join(f"{k} atoms={v}" for k, v in sorted(s.groups.items(), key=lambda x: -x[1]))
    if cmd == "predicates":
        s = _E._get_stats()
        return "\n".join(f"{k} atoms={v}" for k, v in sorted(s.heads.items(), key=lambda x: -x[1]))
    if cmd == "folder":
        if not args: return "usage: folder <group>"
        return fmt(_E.query_folder(args[0]))
    if cmd == "predicate":
        if not args: return "usage: predicate <name>"
        return fmt(_E.query_head(args[0]))
    if cmd == "node":
        if len(args) < 2: return "usage: node <type> <id>"
        return fmt(_E.query_entity(args[1], args[0]))
    if cmd == "entity":
        if not args: return "usage: entity <id>"
        return fmt(_E.query_entity(args[0]))

    return f"unknown command: {cmd}\n{_help()}"

def _bfs(src: str, dst: str, max_hops: int = BFS_MAX_HOPS) -> Optional[List[str]]:
    sn, dn = src.strip().lower(), dst.strip().lower()
    if sn == dn: return [sn]
    visited: Set[str] = {sn}
    queue: List[List[str]] = [[sn]]
    while queue:
        path = queue.pop(0)
        if len(path) > max_hops: return None
        for nb in _E.neighbors(path[-1]):
            if nb == dn: return path + [dn]
            if nb not in visited:
                visited.add(nb)
                queue.append(path + [nb])
    return None

# ───────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────

def _root() -> str:
    return os.environ.get("BIOCYPHER_KG_PATH", "./data")

def build_index(root: str, force: bool = False) -> Stats:
    """Out-of-band indexing method called by bin/bio-index."""
    _E.bind(root, force=True, readonly=False)
    return _E._sync(force=force)

def bio_index(*args) -> str:
    """Agent entrypoint - now instructs the user/agent to use the CLI.
    Supports bio_index() and bio_index(root).
    """
    try:
        return "Please use the 'shell' skill to run: python3 bin/bio-index"
    except Exception as exc:
        return f"bio_index error: {exc}"

def bio_reindex(*args) -> str:
    """Agent entrypoint - now instructs the user/agent to use the CLI.
    Supports bio_reindex() and bio_reindex(root).
    """
    try:
        return "Please use the 'shell' skill to run: python3 bin/bio-index --force"
    except Exception as exc:
        return f"bio_reindex error: {exc}"

def bio_query(*args) -> str:
    """Human-readable query against the indexed atomspace.
    Supports:
        bio_query(query)
        bio_query(root, query)
    """
    try:
        if len(args) == 2:
            root, query = args
        elif len(args) == 1:
            root, query = _root(), args[0]
        else:
            raise TypeError("bio_query expects 1 or 2 arguments")
            
        _E.bind(root)
        return _dispatch(query, raw=False)
    except Exception as exc:
        return f"bio_query error: {exc}"

def bio_extract(*args) -> str:
    """Raw MeTTa atom extraction for symbolic injection.
    Supports:
        bio_extract(query)
        bio_extract(root, query)
    """
    try:
        if len(args) == 2:
            root, query = args
        elif len(args) == 1:
            root, query = _root(), args[0]
        else:
            raise TypeError("bio_extract expects 1 or 2 arguments")

        _E.bind(root)
        return _dispatch(query, raw=True)
    except Exception as exc:
        return f"bio_extract error: {exc}"

def bio_path(*args, **kwargs) -> str:
    """Shortest path between two entities.
    Supports:
        bio_path(src_id, dst_id, max_hops=BFS_MAX_HOPS)
        bio_path(root, src_id, dst_id, max_hops=BFS_MAX_HOPS)
    """
    try:
        max_hops = kwargs.get("max_hops", BFS_MAX_HOPS)
        if len(args) == 4:
            root, src_id, dst_id, max_hops_arg = args
            max_hops = int(max_hops_arg)
        elif len(args) == 3:
            root, src_id, dst_id = args
        elif len(args) == 2:
            src_id, dst_id = args
            root = _root()
        else:
            raise TypeError("bio_path expects 2, 3, or 4 positional arguments")

        _E.bind(root)
    except Exception as exc:
        return f"bio_path error: {exc}"

    if not _E.has_entity(src_id): return f"bio_path: source '{src_id}' not found"
    if not _E.has_entity(dst_id): return f"bio_path: destination '{dst_id}' not found"

    path = _bfs(src_id, dst_id, max_hops=int(max_hops))
    if path is None:
        return f"bio_path: no path within {max_hops} hops between '{src_id}' and '{dst_id}'"

    atoms: List[Atom] = []
    seen: Set[str] = set()
    for i in range(len(path) - 1):
        for atom in _E.edge_atoms(path[i], path[i + 1]):
            if atom.raw not in seen:
                seen.add(atom.raw)
                atoms.append(atom)

    header = f"; bio-path {src_id} -> {dst_id}  hops={len(path) - 1}  via={' -> '.join(path)}"
    body = _fmt_raw(atoms)
    return f"{header}\n{body}" if body else f"{header}\n; (no connecting atoms found)"
