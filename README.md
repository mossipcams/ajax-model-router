# ajax-model-router

Canonical shared router skill bundle — a thin control plane, not a workflow
engine.

The router decides who executes, which model, risk, scope, verification
expectation, and fallback. The parent owns planning, routing, and acceptance.
The delegate owns implementation, verification, and user-requested commits and
pull requests.

Pipeline: **route → execute → verify**.

Optional semantic analysis (`scripts/analyze-task`, `libexec/semantic/`) collects
deterministic facts first, applies hard constraints to compute the eligible
routes, and may ask the **routing sensor** to evaluate those eligible routes
directly. The sensor is a local **GLiNER** classifier
(`fastino/GLiNER2.5-Decide` in a router venv, `scripts/setup-gliner`) and
returns one compact decision: a registry route key
(`MINIMAX`/`QWEN`/`CURSOR`/`GLM`/`CODEX`/`OPUS`), route probabilities, and
complexity/ambiguity scores (1–5). The response is validated strictly and fed
into deterministic policy. The sensor is advisory only — it never chooses the
final model, never owns hard policy, safety, execution, retries, verification,
scope enforcement, or fallback execution, and never blocks routing: when the
sensor is unavailable, times out, returns invalid output, or confidence is
below the threshold, the existing deterministic default routing applies.
Configuration: `config/semantic_analysis.toml` (enabled by default; degrades
gracefully without the sensor).

## Layout

- `skills/model-router/` — control plane: execution decision, model registry,
  route table, outcome dispatch, risk-based review, outcome logging, semantic
  policy integration.
- `libexec/semantic/` — replaceable semantic analysis package (`Disabled` and
  `Gliner` analyzers behind one `SemanticAnalyzer` interface).
- `config/semantic_analysis.toml` — sensor engine/model settings (stdlib
  TOML).
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
`delegate-snapshot`, `delegate-delta`, `check-report`, `analyze-task`,
`router-log`, …) into
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

Outcome logging (`scripts/router-log`) is lightweight and non-blocking. Optional
semantic routing events append to `routing-events.jsonl` beside the TSV via
`--routing-event`.

## Expected routing

Deterministic policy retains final authority. The sensor's route probabilities are
the primary fuzzy signal among *eligible* routes (hard constraints applied
first); hard overrides below always win over the sensor.

| Scenario | Agent / model |
|---|---|
| Bounded implementation (default) | `pi` / `qwen3.8-27b` |
| QWEN unavailable | `cursor` / `composer-2.5` |
| Explicit user/model override | the requested model |
| Explicit Codex ask | `codex` / `gpt-6-astra` |
| Recorded spec/architecture uncertainty | `pi` / `glm-5.2` |
| Retry after failed cheap-model attempt | escalate (`GLM` → `OPUS` → `CODEX`) |
| Shallow docs/boilerplate ≤2 files/~60 lines | `pi` / `minimax-m3` |
| High-risk (auth/security/session/PTY/data-loss) | never `minimax-m3` |
| sensor unavailable/invalid/low confidence | existing deterministic default |
| Pure Q&A / architecture planning | `parent` (no write) |

Routing events (`routing-events.jsonl`) record eligible routes, selected
route, route probabilities/confidence, complexity, ambiguity, whether
fallback/default routing was used, and the matched hard override — no
chain-of-thought, no raw task contents.

## Delegate transport

All three delegates (`cursor`, `codex`, `pi`) dispatch through
[acpx](https://github.com/openclaw/acpx) ACP (`npm install -g acpx@0.13.2`, Node
22.13+). Pin that release and ensure `acpx` is on `PATH`; missing
`acpx` is a hard stop with no fallback to harness-native CLIs. The runner
invokes `acpx <profile> exec|prompt --cwd <worktree> --format json --model
<registry-id>` and extracts `DELEGATE_REPORT` markers from agent output.
Unknown or malformed ACP lines are retained in the raw log; terminal ACP
events and acpx exit codes are authoritative. Operator-facing dispatch
diagnostics also land in `run/debug.log` beside `run/raw.log` (timestamped
`[ajax-router]` lines on stderr during execute, including `acpx pid=…` after
launch). Failure reports distinguish ACP event errors, connection closed
during init (`ACP_CONNECTION_CLOSED_INIT`) vs an active turn
(`ACP_CONNECTION_CLOSED_ACTIVE`), filter pipe failures
(`FILTER_NONZERO_EXIT`), missing terminal events, missing structured reports,
agent nonzero exit (`AGENT_NONZERO_EXIT`), timeout, and cancellation. Filter
and acpx stderr captured in the raw log is echoed into debug/failure detail
when present. Cursor may still `end_turn`
after printing `RetriableError: Failed to run step, exceeded max retries`;
the runner treats that as `ACP_EVENT_FAILED`. If that repeats for one
`--cwd`, the per-path Cursor worker under `~/.cursor/projects/` is usually
stuck — remove that project dir and retry. Do not fall back to a native
harness CLI. For `tool=cursor`, `run-delegate` interposes a stdio JSON-RPC
filter (`libexec/cursor_acp_filter.py`) on `cursor-agent`/`agent` so unsupported
`cursor/*` extension requests never reach acpx; unknown request-style
`cursor/*` methods receive JSON-RPC `-32601` locally with `[cursor-acp-filter]`
stderr diagnostics (stdout stays valid ACP NDJSON).

## Subagent status (Ajax Chat)

Each delegate child launched by `scripts/run-delegate` uses
`acpx --format json --json-strict`. The runner assigns `runId`, `harness`,
`model`, `task`, and `parentTaskId` (the parent chat/task id from the
transaction context) and parses ACP NDJSON from the child stdout as it arrives.

Normalized status events are emitted on **stdout** as NDJSON lines with
`type: subagent_status` — separate from the final `DELEGATE_REPORT` text. Raw
child ACP stays in `run/raw.log` for debugging; it is not replayed into the
parent conversation.

Example:

```json
{"type":"subagent_status","runId":"run_123","parentTaskId":"task_456","harness":"cursor","model":"composer-2.5","state":"tool_call","detail":"Reading src/chat/MessageList.tsx","timestamp":"2026-08-21T21:00:00Z"}
```

Child states: `queued`, `starting`, `running`, `tool_call`,
`waiting_for_permission`, `completed`, `failed`, `cancelled`, `stalled`.

**Nested subagents:** agents spawned internally by Cursor, Codex, or Pi are
visible in Ajax Chat only when that harness emits their activity through ACP.
Every child process the router launches directly gets live status from its JSON
stream. Do not poll `acpx status` for this — that only reflects whether the
local session owner is running.
