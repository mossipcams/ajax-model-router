---
name: model-router
description: Thin control plane — pick executor, model, risk, scope, verification, and fallback for one bounded coding task.
---

# Model Router

Thin control plane for one bounded coding task. Decide who runs, which model,
risk, scope, verification expectation, and fallback — then execute and verify.
Do not prescribe the delegate’s implementation procedure.

This skill owns shared routing and acceptance rules. Delegate skills
(`cursor-delegate`, `pi-delegate`, `codex-delegate`) are thin tool adapters.
If a delegate skill conflicts with this file, this file wins.

## Pipeline

```text
route → execute → verify
```

Semantic analysis (optional, enabled by default) informs routing but never
chooses the final model:

```text
facts → eligible routes → optional Laya decision → deterministic policy → delegate
```

1. **Route** — collect deterministic facts; apply hard constraints to compute
   eligible routes; optionally let Laya (local System-1 sensor, `scripts/analyze-task`)
   evaluate the eligible routes; validate its decision; apply deterministic
   policy and registry keys; emit one `EXECUTION` decision. Laya failure never
   blocks routing.
2. **Execute** — run under the selected delegate, model, and scope. `R-PARENT` is
   Q&A and planning only — never parent-local implementation writes.
3. **Verify** — accept, revise, discard, or escalate using risk-proportional review.

Do not reroute between artificial lifecycle stages. Reroute only when:

- the selected executor fails,
- required scope materially changes,
- new information changes the risk level, or
- the task cannot be completed by the selected model.

## Roles

| Role | Owns |
|---|---|
| **Router** | Classification; executor and model; risk; scope; verification expectation; fallback |
| **Delegate** | Investigation inside scope; implementation; test selection; verification; user-requested commits, pushes, and `gh pr create` |
| **Parent** | Planning; routing; acceptance; proportional review; retry, rejection, or escalation |

The parent writes the plan when required. The parent (orchestrator) never
performs implementation: no product or docs writes, no commits, pushes, merges,
rebases, branch creation, branch switches, or `gh pr create`. Route
(`EXECUTION`), review the delta, and accept.

Before dispatch, the parent must not Grep, Read, or search the repository to
gather context or reconstruct the implementation. Name outcome, acceptance,
bounded `SCOPE`, and `VERIFY` on `EXECUTION` and dispatch. If `SCOPE` is wrong,
the delegate stops and the parent emits a new `EXECUTION` — do not explore to perfect scope first. The delegate investigates inside `SCOPE`. After execute,
risk-based review of the delegate report and actual delta is allowed; do not
read the whole subsystem for that review unless risk requires it.

## Model Registry

Only this table owns provider model IDs. Route rules refer to registry keys;
the decision copies the corresponding exact ID into `MODEL`.

| Key | Model ID | Agent | Provider | Base URL | Context | Max output |
|---|---|---|---|---|---:|---:|
| `CODEX` | `gpt-6-astra` | `codex` | — | — | — | — |
| `CURSOR` | `composer-2.5` | `cursor` | — | — | — | — |
| `MINIMAX` | `minimax-m3` | `pi` | — | — | — | — |
| `QWEN` | `qwen3.8-27b` | `pi` | `local` | `http://127.0.0.1:18000/v1` | 65536 | 4096 |
| `GLM` | `glm-5.2` | `pi` | — | — | — | — |

## Execution Decision

Emit exactly one decision per task before execution. Omit inapplicable optional
fields rather than inventing placeholders.

```yaml
EXECUTION:
  AGENT: parent | cursor | codex | pi
  MODEL: <exact ID from Model Registry or NONE>
  RISK: low | medium | high
  SCOPE:
    - <allowed paths or subsystem>
  VERIFY:
    - <commands or acceptance checks>
  FALLBACK: <agent/model or STOP>
  REASON: <one sentence>
```

`AGENT: parent` is for pure Q&A, architecture planning, and parent-owned
acceptance — not for writing the change when a delegate can do it.

## Invariants

- Current directory is already the task worktree.
- All implementation — including user-requested commits and pull requests —
  runs through the selected delegate.
- When the user asks to create a PR, the delegate runs the repository's local
  verification gate, commits if needed, pushes, and runs `gh pr create`. The
  parent reports the PR URL after reviewing the delta. Still no merge, rebase,
  force-push, or branch switch unless the user explicitly asked.
- Never create worktrees or new branches without explicit user authority.
- Delegates must not commit, push, merge, rebase, create branches, or switch
  branches unless the user explicitly requested that behavior (a PR request
  implies commit, push, and `gh pr create`).
- Edit only paths inside `SCOPE`. Expanding scope requires a new `EXECUTION`.
- Empty diff plus a success claim is failure.
- Stop after two failed execute rounds (bounded retry).
- Escalate destructive, security-sensitive, authentication, session, PTY,
  supervisor, and data-loss risks rather than forcing a low-risk path.

## Route

Follow the first matching rule. Copy a selected registry value into `MODEL`.

**Required for bounded implementation routes:** before emitting `EXECUTION`, run
`scripts/analyze-task` with the task payload (stdin JSON or `--input`). Copy
`AGENT`, `MODEL`, `RISK`, `REASON`, and `FALLBACK` from `output.execution` —
deterministic policy selects the executor and registry model; never copy model
choices from raw Laya fields. When present, also copy `SCOPE` and `VERIFY` from
the same block. Laya failure still emits `execution` via the existing fallback;
parents copy that block unchanged. Do **not** call `analyze-task` from
`run-transaction`, `run-delegate`, or execute — routing must finish before
dispatch. Skip `analyze-task` for `R-PARENT` (pure Q&A or architecture
planning with no implementation write).

| Rule | Condition | `AGENT` | Model key | Notes |
|---|---|---|---|---|
| `R-PARENT` | Pure Q&A or architecture planning (no implementation write) | `parent` | none | Local only |
| `R-EXPLICIT-MODEL` | Explicit user/model override | requested | requested | Always wins over Laya |
| `R-CODEX` | User explicitly asked Codex to implement | `codex` | `CODEX` | Always wins over Laya |
| `R-GLM` | Recorded unresolved specification or architecture uncertainty | `pi` | `GLM` | Always wins over Laya |
| `R-RETRY-ESCALATE` | Retry after failed cheap-model attempt | `pi`/`codex` | `GLM`/`CODEX` | Always wins over Laya |
| `R-LAYA` | No exception matched; Laya names an eligible route at/above the confidence threshold | registry | Laya route key | Fuzzy lane among eligible routes |
| `R-MINIMAX` | Routine docs, generated cleanup, exact replacements, or named boilerplate; at most 2 files and roughly 60 changed lines; no auth/security/data-loss concerns | `pi` | `MINIMAX` | Deterministic default |
| `R-QWEN` | No exception matched; Laya unavailable, invalid, or low confidence | `pi` | `QWEN` | Default implementation |
| `R-CURSOR` | QWEN unavailable | `cursor` | `CURSOR` | Fallback implementation |
| `R-STOP` | Selected tool unavailable and every fallback exhausted; or task exceeds one bounded behavior | — | — | `FALLBACK: STOP` |

Default implementation agent is `pi` / `QWEN`, with `cursor` / `CURSOR` as
its availability fallback. Divert only when an
exception row matches. Do not divert to MiniMax or GLM just because the change
is backend, PTY, frontend, multi-file, or under `ajax-web`.

If the selected tool is unavailable, reroute once via `FALLBACK` to the next
matching agent; never retry the same unavailable tool. `STOP` only when no
agent remains.

### Risk

Assign `RISK` from observable task facts — not from ceremony:

| `RISK` | Typical signals |
|---|---|
| `low` | Localized, well-specified, reversible; docs/boilerplate/exact edits |
| `medium` | Multi-file behavior change inside one subsystem; unclear but bounded |
| `high` | Auth, security, session, PTY, supervisor, destructive ops, data-loss, or architecture-wide impact |

Escalate to `high` (and prefer `FALLBACK` / parent review) for destructive,
security-sensitive, authentication, session, PTY, supervisor, and data-loss
work. Do not apply high-risk ceremony to routine changes.

## Dispatch

Replace detailed implementation packets with this outcome-based prompt. The
parent owns planning and routing only — no pre-dispatch repo exploration. The
delegate owns investigation, edit selection, test selection, and verification.
Every dispatch is stateless: the parent assembles the full prompt for initial
work and for every revision; delegates run one-shot `acpx exec` with no saved
sessions.

```text
You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
You are already the selected implementation worker. Implement in-process.
Never spawn native Cursor Task, best-of-n, or any other subagent.
Never merge, rebase, force-push, or switch branches.
If the user explicitly requested a commit or pull request, you may create a
branch when needed, commit, push, and run `gh pr create` after the repository's
local verification gate. Otherwise never commit, push, or create branches.

Implement the requested outcome.
Allowed scope:
- <paths or subsystem>
Acceptance criteria:
- <required behavior>
Investigate the repository as needed.
Choose the implementation approach.
Run appropriate verification.
Return changed files, verification results, and remaining concerns.
Stop if completing the task requires expanding beyond the allowed scope.

Return exactly this report between marker lines:
ROUTER_REPORT_BEGIN
DELEGATE_REPORT:
  STATUS: COMPLETE | BLOCKED | FAILED
  CHANGED_FILES: [<paths>]
  VERIFICATION:
    - TYPE: test | existing_test | build | typecheck | lint | static_analysis | integration | browser | manual | other
      COMMAND: <command or NONE>
      RESULT: pass | fail | skipped | blocked
      DETAILS: <short result note>
  CONCERNS: []
ROUTER_REPORT_END

<outcome / acceptance / scope from EXECUTION>
```

A success claim without verification entries is failure. Failed verification
items make `COMPLETE` invalid.

## Execute controls

Write-mode work uses `scripts/run-transaction` for deterministic safety only:

```text
before_execute → snapshot → execute → after_execute → log_outcome
```

During `execute`, `scripts/run-delegate` streams `subagent_status` NDJSON on
stdout for Ajax Chat while preserving the normal delegate report stream. Raw
child ACP remains in `run/raw.log`. Nested agents created inside Cursor/Codex/Pi
are visible only when that harness emits them through ACP; every router-launched
child gets live status from its acpx JSON stream (not from polling
`acpx status`). Cursor delegates also wrap `cursor-agent` with
`libexec/cursor_acp_filter.py` so unsupported `cursor/*` extension RPCs are
answered locally instead of killing the acpx turn.

Kept because removing them causes concrete failures:

| Control | Failure prevented |
|---|---|
| Worktree / branch safety | Accidental commits, branch switches, new worktrees |
| Bounded write scope | Edits outside `SCOPE` |
| Pre/post snapshot + delta | Invisible or unreviewable changes |
| Restore on reject | Leaving rejected edits in the tree |
| Bounded retries | Infinite revise loops |
| Risk escalation | Low-ceremony path for destructive/security work |

```bash
SNAP="$(mktemp -d)"
# context.json: task_id, agent, model, risk, allowed_files, acceptance,
# verify, fallback, working_directory, snapshot_directory, user_request
scripts/run-transaction --context context.json --until-stage after_execute
# parent review (risk-proportional) over delta.json / delta.patch
# on DISCARD:
scripts/delegate-delta restore "$SNAP"
# optional re-run for outcome log:
scripts/run-transaction --context context.json \
  --from-stage log_outcome --until-stage log_outcome \
  --gate-result ACCEPT
```

Manual snapshot equivalents remain valid for recovery:

```bash
scripts/delegate-snapshot "$SNAP" pre
# ... delegate ...
scripts/delegate-snapshot "$SNAP" post
scripts/delegate-delta inspect "$SNAP" --allowed <path> [--allowed <path>...]
```

`delta.json` records delegate-created/modified/deleted paths and scope
violations. Keep `$SNAP` until acceptance finishes. Snapshot failure → `STOP`
before execute.

## Risk-based review

Parent-local. No delegate review lane.

**Low risk**

- Delegate verification is sufficient by default.
- Parent reviews the summary, diff statistics, and failures.
- Inspect changed hunks only when something looks wrong.

**Medium risk**

- Parent reads all changed hunks.
- Parent checks acceptance criteria against the implementation.
- Rerun important verification when useful.

**High risk**

- Parent independently reviews affected behavior.
- Rerun critical verification.
- Reject unresolved ambiguity or unsafe behavior.

Accept when scope held, acceptance is demonstrated, and verification is
meaningful. Use `REVISE` once for incomplete work inside scope. A failed
`MINIMAX` round revises on `GLM` with findings; never pay for a second
`MINIMAX` attempt. Every revision — same tool or cross-tool — sends a full
Dispatch prompt assembled by the parent (outcome, scope, acceptance,
findings, and constraints). Use `DISCARD` for a rejected delta. After two failed
rounds, `STOP`.

DISCARD is a verdict, not permission to reset the worktree. Run
`scripts/delegate-delta restore "$SNAP"`; it verifies current non-ignored
state still equals the post snapshot, then restores only delegate paths to
pre-execute content. Concurrent change → `STOP` before restore.
Never use `git reset`, `git checkout`, `git clean`, or a blanket restore.

## Outcome logging

Lightweight and non-blocking. Prefer omitting unknown fields over inventing
precision.

```text
requested_agent:
actual_agent:
success:
revision_needed:
escaped_defect:
cost:
duration:
```

Use `scripts/router-log`. Logging must not block execution; a log write
failure is a warning, not a hard stop.

Optional semantic routing metadata may be recorded via
`--routing-event` (JSON) into a `routing-events.jsonl` sidecar beside the TSV.
Laya has no final routing authority; its route probabilities stay separate
from raw evidence. Do not persist chain-of-thought or raw task contents.

## Semantic analysis (optional)

Laya is a local, self-hosted System-1 routing sensor: a persistent service at
`http://127.0.0.1:8000/v1/systemone` (Jev-compatible API). It evaluates the
eligible execution routes directly — it does not generate task features. Ajax
deterministic policy retains final authority. Configuration lives in
`config/semantic_analysis.toml` (`enabled = true` by default; degrades when
Laya is unreachable). Model capabilities are static in
`config/model_capabilities.toml`.

- **Facts first** — explicit model override, changed files, diff size, retry
  state, and other objective inputs are collected before any Laya call. Hard
  constraints remove ineligible routes (availability, high-risk lanes) before
  inference; Laya sees only compact decision-relevant task information, never
  source files or large repository context.
- **Validated decision** — Laya returns a registry route key
  (`MINIMAX`/`QWEN`/`CURSOR`/`GLM`/`CODEX`), route probabilities, and complexity and
  ambiguity scores (1–5). `RouteDecision`, `FailureFeatures`, and
  `ContextRequirements` use typed validation; invalid Laya output is rejected.
- **Deterministic policy** — registry keys select the executor; hard rules
  (explicit override, auth/security/session/PTY/data-loss risk, model/harness
  availability, retry escalation, capability requirements, SKILL route-table
  exceptions) cannot be overridden by Laya output. Laya's route is used only
  when it names an eligible route at or above the confidence threshold;
  otherwise the existing deterministic default applies.
- **Graceful degradation** — disabled, timeout, invalid JSON, low confidence, or
  unreachable Laya → continue with deterministic default routing.
- **Explanation** — `scripts/analyze-task` emits structured fields (facts,
  eligible routes, selected route, route probabilities/confidence, complexity,
  ambiguity, fallback usage, matched rule, context strategy); no
  chain-of-thought.
