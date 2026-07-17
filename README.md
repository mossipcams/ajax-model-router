# ajax-model-router

Canonical shared router skill bundle.

## Layout

- `skills/model-router/` — the `model-router` skill. Owns the pipeline:
  structured routing decision, model registry, route table, shared Delegate
  Prompt, report schemas, and Review Gate.
- `skills/` — all canonical skills, including `tdd-implementation-packet`,
  `cursor-delegate`, `opencode-delegate`, `codex-delegate`. The delegate
  skills are thin tool adapters; shared rules live only in the router.
- `.claude/skills/`, `.codex/skills/` — symlink views over the canonical
  files. Never edit through these; every file exists exactly once.
- `CALIBRATION.md` — ledger of routing-calibration rule changes; the decision log lives
  at `~/.ajax-router/log.tsv`, summarized by `scripts/router-log-summary`.

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

## Enforced workflow

- `scripts/check-packet` rejects mechanically incomplete packets before any
  optional critique call.
- `scripts/delegate-snapshot` and `scripts/delegate-delta` generate the
  pre-versus-post patch reviewed by the parent and safely restore only that
  delta on `DISCARD`.
- `scripts/run-delegate` bounds Cursor and OpenCode process groups and keeps
  full raw logs while returning complete structured reports.
- `scripts/router-log` writes validated v2 calibration rows;
  `scripts/router-log-summary` excludes incomplete legacy rows from v2 metrics.

## Expected model calls

| Scenario | Before | After |
|---|---:|---:|
| Localized bounded change | 1 cheap implementation call | 1 cheap implementation call; smaller evidence packet |
| Unfamiliar cross-module change | 1 automatic critique + 1 GLM implementation | 1 GLM implementation; add 1 critique only if evidence leaves recorded uncertainty |
| High-risk backend change | 1 automatic critique + 1 GLM implementation | 1 GLM implementation; add 1 critique only for recorded uncertainty |
| Failed cheap-model implementation | 1 cheap call + 1 critique + 1 GLM revision | 1 cheap call + 1 GLM revision; critique only if uncertainty is recorded |

Tiny one-file edits that satisfy the local rule remain 0 delegated model calls.
