# Reference - Biological Graph Skills

These skills provide a generalized index/query layer for biological annotations stored as MeTTa atoms in folder-per-relation datasets.

Implementation is backed by `src/bio_graph.py` and exposed through `src/skills.metta`.

---

## Expected folder layout

The default root is `output/`.

```text
output/
  gene/
    nodes.metta
    edges.metta
  coexpressed/
    nodes.metta
    edges.metta
  pathway/
    nodes.metta
    edges.metta
  ...
```

Notes:

- Each first-level directory under `output/` is treated as a relation group.
- Any `.metta` file is indexed (`nodes.metta`, `edges.metta`, and additional files if present).
- Missing `nodes.metta` or `edges.metta` files are tolerated.

---

## Parsing model

Every top-level s-expression is indexed as one atom record with:

- relation group (folder name under `output/`)
- file kind (basename without extension, for example `nodes` or `edges`)
- file path + line number
- predicate (head symbol)
- extracted entities from nested `(type id)` terms

Examples:

```metta
(transcribes_to (gene ENSG00000101349) (transcript ENST00000353224))
(source (transcribes_to (gene ENSG00000101349) (transcript ENST00000353224)) GENCODE)
(source_url (transcribes_to (gene ENSG00000101349) (transcript ENST00000353224)) https://www.gencodegenes.org/)
```

### Hyperedges

Hyperedges are supported implicitly: any atom containing more than two extracted entities is treated as an n-ary relationship. Neighbor queries include all co-occurring entities in such atoms.

---

## `bio-index`

### Signature

```metta
(bio-index)
(bio-index "output_root")
```

### Purpose

Build or reuse an in-memory index for the target output folder.

### Returns

A summary string:

```text
indexed root=... files=... atoms=... relations=... predicates=... parse_errors=...
```

---

## `bio-reindex`

### Signature

```metta
(bio-reindex)
(bio-reindex "output_root")
```

### Purpose

Force-refresh the index even when cached data exists.

---

## `bio-query`

### Signature

```metta
(bio-query "command")
```

Queries the default `output/` index.

## `bio-query-in`

### Signature

```metta
(bio-query-in "output_root" "command")
```

Queries a specific output folder.

---

## Query commands

Important: these are **query strings** passed to `bio-query` / `bio-query-in`, not shell commands. For example, run `(bio-query "stats")`, not `stats` in Bash.

```text
stats
folders
predicates
entity <entity_id>
node <entity_type> <entity_id>
predicate <name>
folder <relation_group>
neighbors <entity_id>
neighbors <entity_type> <entity_id>
help
```

### Examples

```metta
(bio-index "output")
(bio-query "stats")
(bio-query "folder gene")
(bio-query "predicate transcribes_to")
(bio-query "entity ENSG00000101349")
(bio-query "node transcript ENST00000353224")
(bio-query "neighbors gene ENSG00000101349")
```

---

## Recommended usage pattern

1. Run `(bio-index "output")` once after startup.
2. Use `(bio-query "...")` repeatedly while exploring/querying.
3. Run `(bio-reindex "output")` when files change.

---

## Limits

- This is a structural index/query layer, not a full SPARQL/Cypher engine.
- Comment stripping is line-based (`;` comments).
- Query outputs are truncated to keep feedback manageable for the loop context.
