# ajax-model-router

Canonical shared router skill bundle.

Ajax Model Router requires evidence that the implementation works.
It does not require test-first development or TDD.
Tests should be used when they are the most effective verification method.

## Layout

- `skills/model-router/` — the `model-router` skill. Owns the pipeline:
  structured routing decision, model registry, route table, shared Delegate
  Prompt, report schemas, and Review Gate.
- `skills/` — all canonical skills, including `tdd-implementation-packet`
  (implementation packet lane; outcome-based verification, not mandatory TDD),
  `cursor-delegate`, `pi-delegate`, `codex-delegate`. The delegate
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

Install wires skill symlinks under `.cursor` / `.codex` / `.claude` and also
links the delegation helpers (`scripts/run-delegate`, `run-transaction`,
`delegate-snapshot`, `delegate-delta`, `check-packet`, `check-dispatch`, …)
into the target's `scripts/` so a task worktree can run the skill commands as
written. Re-run install for each worktree that needs dispatch (git worktrees do
not share untracked scripts).

Use `--force` only when replacing an existing non-canonical install:

```bash
scripts/install-symlinks --target ../ajax-cli --force
```

## Enforced workflow

- `scripts/check-packet` rejects mechanically incomplete packets before any
  optional critique call. Legacy TDD packets remain readable with a deprecation
  warning; RED/GREEN sequencing is not enforced.
- `scripts/check-dispatch` validates `direct` / `compact` / `full` dispatch
  packages (`full` delegates to `check-packet`).
- `scripts/run-transaction` runs the deterministic lifecycle
  (before_dispatch → … → before_review) and emits `review_bundle.json` for the
  parent Review Gate; resume with `--from-stage after_review`.
  `before_dispatch` rejects known `estimated_lines` ≥ 250
  (`pre-dispatch-size-split` / `R-SIZE-SPLIT`); split packets before DELEGATE.
  The ~400 changed-line stop remains the post-delta Review Gate backstop.
- `scripts/delegate-snapshot` and `scripts/delegate-delta` generate the
  pre-versus-post patch reviewed by the parent and safely restore only that
  delta on `DISCARD`.
- `scripts/run-delegate` bounds Cursor and Pi process groups and keeps
  full native JSONL logs while returning complete structured reports.
- `scripts/router-log` writes validated v2 calibration rows (optional v3
  verification-metric trailer); `scripts/router-log-summary` excludes
  incomplete legacy rows from metrics.

## Expected model calls

| Scenario | Before | After |
|---|---:|---:|
| Localized bounded change | 1 cheap implementation call | 1 cheap implementation call; smaller evidence packet |
| Unfamiliar cross-module change | 1 automatic critique + 1 GLM implementation | 1 GLM implementation; add 1 critique only if evidence leaves recorded uncertainty |
| High-risk backend change | 1 automatic critique + 1 GLM implementation | 1 GLM implementation; add 1 critique only for recorded uncertainty |
| Failed cheap-model implementation | 1 cheap call + 1 critique + 1 GLM revision | 1 cheap call + 1 GLM revision; critique only if uncertainty is recorded |

Tiny one-file edits that satisfy the local rule remain 0 delegated model calls.

## Native delegate transports

Pi uses one `pi --mode rpc --model MODEL --no-session --no-context-files
--no-skills` process per active delegation. The runner sends JSONL `prompt` and
`follow_up` commands, keeps the process alive for that delegation, and closes
stdin during cleanup. Pi's native events map to the router's small normalized
set: `started`, `activity/tool started`, `activity/tool finished`,
`message/progress`, `completed`, and `failed`.

Cursor uses `cursor-agent -p -f --trust --model MODEL --output-format
stream-json --stream-partial-output`, preserving `--resume CHAT_ID`. Cursor's
native JSONL events feed the same normalized set without an invented RPC layer.
Unknown or malformed lines are retained in the raw log and skipped when safe;
native terminal events are authoritative, with process exit as the final safety
signal. Worktree isolation, READY packets, model selection, report schema,
timeouts, cancellation, and Review Gate behavior remain unchanged. Sessions
are not persisted beyond the lifetime of a Pi delegation.
