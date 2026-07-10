# ajax-model-router

Canonical shared router skill bundle.

## Layout

- `SKILL.md` (repo root) — the `model-router` skill. Owns the pipeline:
  structured routing decision, model registry, route table, shared Delegate
  Prompt, report schemas, and Review Gate.
- `skills/` — canonical sub-skills: `tdd-implementation-packet`,
  `cursor-delegate`, `opencode-delegate`, `codex-delegate`. The delegate
  skills are thin tool adapters; shared rules live only in the router.
- `.claude/skills/`, `.codex/skills/` — symlink views over the canonical
  files. Never edit through these; every file exists exactly once.

## Install

```bash
# From this repo
scripts/install-symlinks --target ../ajax-cli

# Verify
scripts/check-symlinks --target ../ajax-cli
scripts/check-contracts
```

Use `--force` only when replacing an existing non-canonical install:

```bash
scripts/install-symlinks --target ../ajax-cli --force
```
