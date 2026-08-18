# ajax-model-router

Canonical shared router skill bundle — a thin control plane, not a workflow
engine.

The router decides who executes, which model, risk, scope, verification
expectation, and fallback. The parent owns planning, routing, and acceptance.
The delegate owns implementation, verification, and user-requested commits and
pull requests.

Pipeline: **route → execute → verify**.

## Layout

- `skills/model-router/` — control plane: execution decision, model registry,
  route table, outcome dispatch, risk-based review, outcome logging.
- `skills/cursor-delegate`, `pi-delegate`, `codex-delegate` — thin tool
  adapters. Shared rules live only in the router.
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

Install wires skill symlinks under `.cursor` / `.codex` / `.claude` and also
links the execute helpers (`scripts/run-delegate`, `run-transaction`,
`delegate-snapshot`, `delegate-delta`, `check-report`, `router-log`, …) into
the target's `scripts/` so a task worktree can run them as written. Re-run
install for each worktree that needs dispatch.

Use `--force` only when replacing an existing non-canonical install:

```bash
scripts/install-symlinks --target ../ajax-cli --force
```

## Safety controls (kept)

| Control | Why |
|---|---|
| Worktree / branch safety | No accidental commits, branch switches, or new worktrees |
| Bounded write scope | Reject edits outside `SCOPE` |
| Pre/post snapshot + delta | Reviewable change set; restore on discard |
| Bounded retries | Stop after two failed execute rounds |
| Risk escalation | Auth/security/PTY/supervisor/data-loss stay high-risk |

`scripts/run-transaction` runs only:

```text
before_execute → snapshot → execute → after_execute → log_outcome
```

Outcome logging (`scripts/router-log`) is lightweight and non-blocking.

## Expected routing

| Scenario | Agent / model |
|---|---|
| Bounded implementation (default) | `cursor` / `composer-2.5` |
| Explicit Codex ask | `codex` / `gpt-5.6-sol` |
| Recorded spec/architecture uncertainty | `pi` / `glm-5.2` |
| Shallow docs/boilerplate ≤2 files/~60 lines | `pi` / `minimax-m3` |
| Pure Q&A / architecture planning | `parent` (no write) |

## Delegate transport

All three delegates (`cursor`, `codex`, `pi`) dispatch through
[acpx](https://github.com/openclaw/acpx) ACP (`npm install -g acpx@0.13.0`, Node
22.13+). Pin that release and ensure `acpx` is on `PATH`; missing
`acpx` is a hard stop with no fallback to harness-native CLIs. The runner
invokes `acpx <profile> exec|prompt --cwd <worktree> --format json --model
<registry-id>` and extracts `DELEGATE_REPORT` markers from agent output.
Unknown or malformed ACP lines are retained in the raw log; terminal ACP
events and acpx exit codes are authoritative. Operator-facing dispatch
diagnostics also land in `run/debug.log` beside `run/raw.log` (timestamped
`[ajax-router]` lines on stderr during execute). Cursor may still `end_turn`
after printing `RetriableError: Failed to run step, exceeded max retries`;
the runner treats that as `ACP_EVENT_FAILED`. If that repeats for one
`--cwd`, the per-path Cursor worker under `~/.cursor/projects/` is usually
stuck — remove that project dir and retry. Do not fall back to a native
harness CLI.
