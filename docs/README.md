# OmegaClaw Documentation

This directory contains the full documentation for OmegaClaw. Every page is a sibling file — no subdirectories. Filename prefixes identify the section:

- `intro-*` — conceptual introduction
- `tutorial-NN-*` — numbered, task-oriented walkthroughs
- `reference-*` — API, engines, orchestration, failure modes, and internals

If you are new, read the Introduction in order, then pick tutorials that match what you want to build, and dip into the reference when you need details.

---

## Introduction

Start here to understand what OmegaClaw is, the hybrid reasoning thesis, how the pieces fit together, and how to get it running.

- [introduction.md](./introduction.md) — What OmegaClaw is, the hybrid thesis, architecture, core vocabulary, design goals, and honest limits (merged conceptual intro).
- [installation instruction](/README.md#installation) — Manual MeTTa setup, environment variables, API keys.

---

## Tutorials

Numbered in suggested reading order. Each tutorial is self-contained.

- [tutorial-01-teaching-memories.md](./tutorial-01-teaching-memories.md) — Use `remember`, `query`, `episodes`, and `pin`
- [tutorial-02-shell-and-files.md](./tutorial-02-shell-and-files.md) — `shell`, `read-file`, `write-file`, `append-file`
- [tutorial-03-writing-a-custom-skill.md](./tutorial-03-writing-a-custom-skill.md) — Add a new MeTTa skill end-to-end
- [tutorial-04-adding-a-channel.md](./tutorial-04-adding-a-channel.md) — Build a new communication channel adapter
- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — Invoke NAL and PLN through `(metta ...)` with worked examples
- [tutorial-06-remote-agentverse-skills.md](./tutorial-06-remote-agentverse-skills.md) — Delegate work to remote Agentverse agents
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — External grounding — the primary reliability mitigation
- [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) — Strategy playbook — chain depth, revision, thresholds, anti-patterns

---

## Reference

### Reasoning engines and orchestration

- [reference-lib-nal.md](./reference-lib-nal.md) — NAL rules with truth formulas; confirmed vs. non-functional patterns
- [reference-lib-pln.md](./reference-lib-pln.md) — Modus Ponens, abduction, revision; current limits
- [reference-lib-ona.md](./reference-lib-ona.md) — OpenNARS for Applications — planned real-time / temporal engine (experimental, not installed by default)
- [reference-orchestration.md](./reference-orchestration.md) — Engine selection, stopping criteria, action thresholds, defense stack
- [reference-failure-modes.md](./reference-failure-modes.md) — Documented failures, error rates, mitigations

### Skills

User-facing MeTTa skills the agent invokes. Each page follows the template **Signature → Purpose → Parameters → Returns → Examples → Notes/Limits**.

- [reference-skills-memory.md](./reference-skills-memory.md) — `remember`, `query`, `episodes`, `pin`
- [reference-skills-io.md](./reference-skills-io.md) — `shell`, `read-file`, `write-file`, `append-file`
- [reference-skills-communication.md](./reference-skills-communication.md) — `send`, `receive`, `search`
- [reference-skills-bio.md](./reference-skills-bio.md) — `bio-index`, `bio-reindex`, `bio-query`, `bio-query-in`
- [reference-skills-reasoning.md](./reference-skills-reasoning.md) — `metta` (NAL/PLN invocation surface)
- [reference-skills-remote-agents.md](./reference-skills-remote-agents.md) — `tavily-search`, `technical-analysis`

### Configuration & Adapters

- [reference-configuration.md](./reference-configuration.md) — `configure` form and all runtime parameters
- [reference-channels.md](./reference-channels.md) — IRC, Telegram, Mattermost, and websearch adapters plus the channel contract
- [reference-python-bridges.md](./reference-python-bridges.md) — `lib_llm_ext.py`, `src/agentverse.py`, `src/helper.py`, `src/skills.pl`
- [reference-integration-biocypher-omegaclaw.md](./reference-integration-biocypher-omegaclaw.md) — handover for BioCypher KG interoperability and smoke tests

### Internals

- [reference-internals-loop.md](./reference-internals-loop.md) — `src/loop.metta` lifecycle and turn structure
- [reference-internals-memory-store.md](./reference-internals-memory-store.md) — The three-tier memory architecture
- [reference-internals-skill-dispatch.md](./reference-internals-skill-dispatch.md) — How `(skill args)` calls resolve
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — Where to hook in new skills, tools, channels, LLMs, engines
