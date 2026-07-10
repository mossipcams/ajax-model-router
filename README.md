# ajax-model-router

Canonical shared router skill bundle.

## Layout

- `SKILL.md` (repo root) — the `model-router` skill. Owns the pipeline:
  route table, lanes, the shared Delegate Prompt, and the Review Gate.
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
```

Use `--force` only when replacing an existing non-canonical install:

```bash
scripts/install-symlinks --target ../ajax-cli --force
```
