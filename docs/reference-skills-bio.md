# Bio-Claw — BioCypher Atomspace Integration

OmegaClaw can consume BioCypher MeTTa exports and reason over them using
PLN / NAL. The integration is file-based: OmegaClaw reads `.metta` files
directly with no runtime dependency on BioCypher.

---

## Expected Output Layout

```text
output_root/
  gene/
    nodes.metta
    edges.metta
  transcript/
    nodes.metta
    edges.metta
  coexpressed/
    edges.metta
  ...
```

- Every first-level subdirectory is a **relation group**.
- Any `.metta` file is indexed.
- Files at the root level go into the `_root` group.

---

## Parsing Model

Every top-level s-expression in a `.metta` file becomes one **Atom** in the
index. The parser extracts:

| Field           | Example                              |
|-----------------|--------------------------------------|
| `relation_group`| `gene` (folder name)                 |
| `file_kind`     | `nodes`, `edges`                     |
| `head`          | `transcribes_to` (leading symbol)    |
| `entities`      | `[("gene","ENSG..."),("transcript","ENST...")]` |

**Example source atom:**

```metta
(transcribes_to (gene ENSG00000125863) (transcript ENST00000353224))
```

The parser walks the parse tree recursively. A `(type id)` pair where both
children are string tokens is an entity. In the example above it finds:

- `("gene", "ENSG00000125863")`
- `("transcript", "ENST00000353224")`

These are indexed by `(type, id)` pair **and** by `id` alone so lookups work
with or without knowing the type.

---

## Skills Reference

All bio skills take an explicit `output_root` as first argument.

### `bio-index "output_root"`

Build (or reuse by signature) the full in-memory index.

Returns a summary line:
```
indexed root=... files=... atoms=... relations=... predicates=... parse_errors=...
```

### `bio-reindex "output_root"`

Force-rebuild the index even if the signature has not changed (e.g. after
a partial file update that kept the same mtime).

### `bio-query "output_root" "command"`

Structured query against the full index. Returns human-readable text.

**Commands:**

| Command                        | Description                                          |
|--------------------------------|------------------------------------------------------|
| `stats`                        | Index summary + top 10 relations and predicates      |
| `folders`                      | All relation groups with atom counts                 |
| `predicates`                   | All predicate heads with atom counts                 |
| `folder <group>`               | All atoms in a relation group                        |
| `predicate <name>`             | All atoms with this predicate head                   |
| `node <type> <id>`             | Atoms containing `(type id)` entity pair             |
| `entity <id>`                  | Atoms containing `id` (any type)                     |
| `help`                         | Print command reference                              |

### `bio-extract "output_root" "command"`

Same query commands as `bio-query`, but returns **raw MeTTa s-expressions**
(one atom per line) instead of formatted text. Use this when you want to feed
the result into the `metta` skill for symbolic inference.

```metta
; Agent calls:
(bio-extract "/data/output" "node gene ENSG00000125863")

; Returns something like:
(transcribes_to (gene ENSG00000125863) (transcript ENST00000353224))
(source (transcribes_to (gene ENSG00000125863) (transcript ENST00000353224)) GENCODE)
```

### `bio-path "output_root" "src_id" "dst_id"`

BFS shortest path between two biological entity IDs across the atomspace.

Returns raw MeTTa atoms connecting the path with a header comment:

```text
; bio-path ENSG00000125863 -> CHEBI:15422  hops=3  via=ENSG... -> ENST... -> P12345 -> CHEBI:15422
(transcribes_to (gene ENSG00000125863) (transcript ENST00000353224))
(translates_to (transcript ENST00000353224) (protein P12345))
(catalyzes (protein P12345) (metabolite CHEBI:15422))
```

---

## Neuro-Symbolic Reasoning Chain (Bio-Claw)

```
bio-index  →  bio-extract / bio-path  →  metta (PLN/NAL)  →  send answer
```

**Step by step:**

```metta
; 1. Index once at startup
(bio-index "/data/output")

; 2. Extract subgraph around a gene of interest
;    Result is raw MeTTa atoms stored in LAST_SKILL_USE_RESULTS
(bio-extract "/data/output" "node gene ENSG00000125863")

; 3. Or find a path between entities
(bio-path "/data/output" "ENSG00000125863" "CHEBI:15422")

; 4. Inject retrieved atoms into PLN / NAL for formal deduction
;    (Paste the bio-extract output as the first premises)
(metta (|~ ((Implication
              (transcribes_to (gene $G) (transcript $T))
              (Inheritance $G protein-coding))
             (stv 1.0 0.9))
            ((transcribes_to (gene ENSG00000125863) (transcript ENST00000353224))
             (stv 1.0 0.9))))

; 5. Send the reasoned conclusion
(send "Gene ENSG00000125863 is protein-coding with confidence 0.9 (PLN inference over GENCODE graph)")
```

**Key principle:** `bio-extract` and `bio-path` produce raw MeTTa atoms
that can be copy-pasted directly as premises into `(|- ...)` or `(|~ ...)`
inference blocks. This closes the loop between the biological knowledge graph
and the formal symbolic reasoning engine.

---

## CLI Tools

### `scripts/bio_query.py`

```bash
# Index and summarise
python scripts/bio_query.py --root /data/output --index

# Human-readable query
python scripts/bio_query.py --root /data/output stats
python scripts/bio_query.py --root /data/output node gene ENSG00000125863

# Raw MeTTa extraction
python scripts/bio_query.py --root /data/output --extract node gene ENSG00000125863

# Path finding
python scripts/bio_query.py --root /data/output --path ENSG00000125863 CHEBI:15422

# Interactive REPL
python scripts/bio_query.py --root /data/output --repl
# Inside REPL: :extract node gene ENSG...  |  :path src dst  |  :reindex  |  :exit
```

Set a default root via environment or `.env`:

```bash
echo 'OMEGACLAW_BIO_OUTPUT_ROOT=/data/output' >> /path/to/OmegaClaw-Core/.env
python scripts/bio_query.py stats   # --root inferred automatically
```

### `scripts/bio_smoke.py`

```bash
python scripts/bio_smoke.py --root /data/output
```

Runs index → stats → folders → predicates → sample node queries →
bio-extract sample → bio-path sample. Good for validating a new dataset.

---

## Index Caching and Signature

The index is cached in memory keyed by `(file_count, max_mtime, total_bytes)`.
It is automatically invalidated if any file changes size or modification time.
`bio-reindex` bypasses the check and forces a rebuild.

---

## Limitations

- Structural index only — no full-text search, no SPARQL, no Cypher.
- Comment stripping is line-based (`;` to end of line).
- `bio-extract` output is truncated to 500 atoms to keep feedback manageable.
- `bio-path` BFS is bounded by `max_hops` (default 5) and uses the in-memory
  adjacency graph, so it requires `bio-index` to have been called first.
