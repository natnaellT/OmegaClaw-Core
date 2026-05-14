# Reference - BioCypher KG Integration Handover

**Audience:** maintainers working on BioCypher KG and OmegaClaw interoperability.

This page is a concise handover of what was implemented in OmegaClaw for biological graph querying, why it was added, and how to validate it quickly.

---

## Why this was added

OmegaClaw is a general neurosymbolic agent framework. We added a **file-based biological graph index/query layer** so OmegaClaw can directly consume BioCypher-generated MeTTa output folders without embedding or vendoring the BioCypher codebase.

The goal is a stable producer-consumer contract:

- **Producer:** BioCypher KG export (`.metta` files).
- **Consumer:** OmegaClaw bio skills (`bio-index`, `bio-query`, etc.).

---

## What was implemented

### 1) New query engine

- **File:** `src/bio_graph.py`
- Adds:
  - recursive `.metta` file discovery
  - top-level s-expression parsing
  - entity extraction from nested `(type id)` terms
  - in-memory indexes by folder, predicate, entity, and entity-id
  - query dispatcher and query commands

Public functions exposed to MeTTa:

- `bio_index(output_root="output")`
- `bio_reindex(output_root="output")`
- `bio_query(query, output_root="output")`
- `bio_query_in(output_root, query)`

### 2) New MeTTa skills

- **File:** `src/skills.metta`
- Adds wrappers:
  - `(bio-index)` / `(bio-index "...")`
  - `(bio-reindex)` / `(bio-reindex "...")`
  - `(bio-query "...")`
  - `(bio-query-in "..." "...")`

### 3) Runtime import wiring

- **File:** `lib_omegaclaw.metta`
- Adds import of `./src/bio_graph.py` so the Python bridge can resolve skill calls.

### 4) User docs

- **File:** `docs/reference-skills-bio.md`
- Documents expected layout, query commands, examples, usage pattern, and limits.

---

## What this integration is (and is not)

It **is**:

- a data contract integration based on exported `.metta` artifacts.
- a lightweight interoperability path between two independent repositories.

It is **not**:

- a monorepo merge.
- a hard runtime dependency of BioCypher KG on OmegaClaw internals.
- a requirement to vendor the full OmegaClaw repository into BioCypher KG.

---

## Output contract OmegaClaw currently expects

Given an `output_root`:

- recursively indexes all `.metta` files under that root.
- treats the first-level directory under `output_root` as the relation group.
- accepts additional `.metta` files beyond `nodes.metta` and `edges.metta`.
- tolerates missing `nodes.metta` or `edges.metta`.

Notes:

- top-level files under `output_root` are grouped as `_root`.
- folder grouping is first-level; deeper folders are still indexed but mapped to their first top-level group.

---

## 3-command smoke test

Run these inside OmegaClaw as MeTTa skill calls (for your dataset path):

Important: do not run `(bio-index ...)` directly in Bash. These are MeTTa expressions.

```metta
(bio-index "/home/natnael/dev/biocypher-kg-/output_human")
(bio-query-in "/home/natnael/dev/biocypher-kg-/output_human" "stats")
(bio-query-in "/home/natnael/dev/biocypher-kg-/output_human" "node transcript ENST00000353224")
```

Expected high-level outcome:

- command 1 returns `indexed root=... files=... atoms=... relations=... predicates=... parse_errors=...`
- command 2 returns summary plus `top_relations` and `top_predicates`
- command 3 returns `matches=...` and records containing transcript facts (if that transcript exists)

### Running the smoke test from a terminal

Cleanest option (single command):

```bash
wsl -d Ubuntu -- python3 /mnt/c/Users/hp/OmegaClaw-Core/scripts/bio_smoke.py --root /home/natnael/dev/biocypher-kg-/output_human
```

This runs index/stats/folders/predicates plus sample `gene` and `transcript` entity checks automatically.

### Clean query CLI (recommended for day-to-day use)

Instead of pasting multiline Python snippets, use:

Optional default root via `.env` in the OmegaClaw repo:

```bash
echo 'OMEGACLAW_BIO_OUTPUT_ROOT=/home/natnael/dev/biocypher-kg-/output_human' >> /mnt/c/Users/hp/OmegaClaw-Core/.env
```

Then you can omit `--root` for normal query commands.

```bash
wsl -d Ubuntu -- python3 /mnt/c/Users/hp/OmegaClaw-Core/scripts/bio_query.py --root /home/natnael/dev/biocypher-kg-/output_human --index
```

With `.env` configured:

```bash
wsl -d Ubuntu -- python3 /mnt/c/Users/hp/OmegaClaw-Core/scripts/bio_query.py --index
```

Run a normal query:

```bash
wsl -d Ubuntu -- python3 /mnt/c/Users/hp/OmegaClaw-Core/scripts/bio_query.py --root /home/natnael/dev/biocypher-kg-/output_human stats
```

Start interactive mode:

```bash
wsl -d Ubuntu -- python3 /mnt/c/Users/hp/OmegaClaw-Core/scripts/bio_query.py --root /home/natnael/dev/biocypher-kg-/output_human --repl
```

Inside `--repl`, examples:

```text
predicate gene
node gene ENSG00000125863
neighbors gene ENSG00000125863
```

If `metta` is installed, create a small file and run it:

```bash
cat > bio_smoke.metta <<'METTA'
!(import! &self (library lib_omegaclaw))
!(bio-index "/home/natnael/dev/biocypher-kg-/output_human")
!(bio-query-in "/home/natnael/dev/biocypher-kg-/output_human" "stats")
!(bio-query-in "/home/natnael/dev/biocypher-kg-/output_human" "node transcript ENST00000353224")
METTA

metta bio_smoke.metta
```

---

## Suggested PR scope for BioCypher KG (optional)

If you want to improve producer-side compatibility without adding OmegaClaw code:

1. Add a short compatibility doc section describing the export contract.
2. Add a sample command that generates MeTTa output for OmegaClaw consumption.
3. Add a small export validator script (checks `.metta` presence and parseability).
4. Add a smoke-test checklist in CI docs.

This keeps both repos decoupled while making integration reproducible.
