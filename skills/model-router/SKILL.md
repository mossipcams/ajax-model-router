---
name: model-router
description: Ajax Model Router — harness-boundary mediation for cross-harness model delegation.
---

# Ajax Model Router

Cross-harness transport and safety control plane. Mediate delegation when the
caller harness and target transport differ. When a caller that is itself a
supported transport targets that same transport, return `USE_NATIVE` and let
the parent use its own native subagent mechanism — Ajax Model Router is
bypassed.

A harness can be a **caller** without Ajax supporting it as a DELEGATE target.
For example, Claude can invoke Ajax Model Router to launch Cursor even though
there is no `claude-delegate` transport.

**Pstack is independent and Cursor-native.** Do not vendor, modify, duplicate,
or integrate pstack here. Inside Cursor, pstack may select a playbook and
delegate to Composer 2.5 through Cursor’s native subagent path without this
router.

This skill owns shared routing and transaction rules. Harness install adapters
(`model-router-cursor`, `model-router-codex`, `model-router-claude`) bind
`CALLER_HARNESS` immutably. Delegate skills (`cursor-delegate`, `pi-delegate`,
`codex-delegate`) are thin **transport** adapters only. If a delegate skill
conflicts with this file, this file wins.

## Owns

- Cross-harness transport
- Exact provider model IDs
- Request validation
- Process timeouts and cancellation
- Pre-dispatch snapshots
- Post-dispatch deltas
- Write-scope enforcement
- Verification execution
- Structured delegate reports
- Parent review bundles
- Safe restoration of rejected delegate changes

## Does not own

- Selecting engineering playbooks
- Deciding investigation vs architecture vs implementation
- Routing by frontend/backend/file type/risk class/reasoning depth
- Defaulting all implementation to Composer
- Forcing parents to delegate every implementation
- Semantic implementation packets or packet critique loops
- Model-selection tuning ledgers
- Preventing parent-local implementation

## Pipeline

```text
route → (USE_NATIVE | STOP | DELEGATE → execute → verify → parent review)
```

1. **Route** — emit one `ROUTING_DECISION` from the install-bound caller harness
   and the request.
2. **USE_NATIVE** — stop here. No snapshot, no process, no transaction artifacts.
3. **STOP** — refuse. Never substitute another provider or model.
4. **DELEGATE** — run the deterministic lifecycle, then parent-review the delta.

## Model Registry

Only this table owns provider model IDs for **target transports**. Validate
that each requested model belongs to its target transport. Do not use aliases
in transport commands. Editing this registry is enough to add or remove models.
Callers (`claude`, `other`, …) are not registry rows — they invoke Ajax; they
are not DELEGATE targets until a transport exists.

| Transport | Model ID |
|---|---|
| `cursor` | `composer-2.5` |
| `cursor` | `cursor-grok-4.6-high` |
| `codex` | `gpt-5.6-sol` |
| `pi` | `opencode-go/minimax-m3` |
| `pi` | `opencode-go/glm-5.2` |

## Request contract

```yaml
MODEL_ROUTING_REQUEST:
  CALLER_HARNESS: cursor | codex | claude | pi | other
  TARGET_TRANSPORT: cursor | codex | pi
  MODEL: <exact target model ID>
  TASK: <one bounded task>
  ALLOWED_FILES:
    - <path or bounded path pattern>
  ACCEPTANCE:
    - <observable outcome>
  VERIFICATION:
    - <command or explicit manual verification>
  STOP_IF:
    - <observable stop condition>
```

`CALLER_HARNESS` is filled by the harness install adapter, not invented from
task text or free model self-declaration. `TARGET_TRANSPORT` is always one of
the Ajax-supported transports above.

## Routing decision

Emit exactly one decision before any delegation:

```yaml
ROUTING_DECISION:
  ACTION: USE_NATIVE | DELEGATE | STOP
  CALLER_HARNESS: cursor | codex | claude | pi | other
  TARGET_TRANSPORT: cursor | codex | pi
  MODEL: <validated provider model ID or NONE>
  ALLOWED_SCOPE: []
  REASON: <one sentence>
```

Rules:

1. If `CALLER_HARNESS` equals `TARGET_TRANSPORT` and that value is a supported
   transport, return `USE_NATIVE`. Do not create a snapshot, launch a process,
   or perform a delegation. Callers that are not transports (`claude`,
   `other`) never receive `USE_NATIVE`.
2. If the caller and transport differ and the target transport and model are
   valid, return `DELEGATE`.
3. If the target transport is unavailable, the model does not belong to that
   transport, or the request is incomplete, return `STOP`.
4. Never silently substitute another provider or model.

Machine helper (optional):

```bash
scripts/route --caller-harness claude \
  --target-transport cursor --model cursor-grok-4.6-high --allowed src/foo.py
```

## Invariants

- Current directory is already the task worktree.
- Never create worktrees, branches, commits, pushes, merges, rebases, or
  branch switches. No delegate may either.
- No commits unless the user explicitly requested them.
- Edit only paths inside `ALLOWED_FILES` / `ALLOWED_SCOPE`. Expanding scope
  requires a new request and decision.
- Empty diff plus a success claim is failure.
- Same-transport work for a matching caller stays on the parent’s native path.

## Dispatch (DELEGATE only)

```text
You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches
unless the user explicitly requested a commit.

Task:
- <TASK>

Allowed files:
- <ALLOWED_FILES>

Acceptance criteria:
- <ACCEPTANCE>

Verification requirements:
- <VERIFICATION>

Stop if:
- <STOP_IF>

Investigate the repository as needed.
Choose the implementation approach.
Run the declared verification.
Return changed files, verification results, and remaining concerns.
Stop if completing the task requires expanding beyond the allowed files.

Return exactly this report between marker lines:
ROUTER_REPORT_BEGIN
DELEGATE_REPORT:
  STATUS: COMPLETE | BLOCKED | FAILED
  CHANGED_FILES: [<paths>]
  VERIFICATION:
    - TYPE: test | build | typecheck | lint | static_analysis | integration | browser | manual | other
      COMMAND: <command or NONE>
      STEPS: []
      RESULT: pass | fail | skipped | blocked
      DETAILS: <short evidence>
  CONCERNS: []
ROUTER_REPORT_END
```

A success claim without verification entries is failure. Failed verification
items make `COMPLETE` invalid. Relevant successful verification is required
for `COMPLETE`.

## Execute controls (DELEGATE only)

Write-mode cross-harness work uses `scripts/run-transaction`:

```text
before_execute → snapshot → execute → after_execute → log_outcome
```

| Control | Failure prevented |
|---|---|
| Worktree / branch safety | Accidental commits, branch switches, new worktrees |
| Bounded write scope | Edits outside allowed files |
| Pre/post snapshot + delta | Invisible or unreviewable changes |
| Restore on reject | Leaving rejected edits in the tree |
| Transport timeout / cancel | Hung external workers |

```bash
SNAP="$(mktemp -d)"
# context.json: task_id, caller_harness, target_transport, model, task,
# allowed_files, acceptance, verification, stop_if, working_directory,
# snapshot_directory
scripts/run-transaction --context context.json --until-stage after_execute
# parent review over delta.json / delta.patch (inspect the actual delta)
# on DISCARD:
scripts/delegate-delta restore "$SNAP"
```

`USE_NATIVE` and `STOP` create no snapshot or transaction artifacts.

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

## Parent review

Parent-local. No delegate review lane. A `COMPLETE` report is evidence, not
acceptance — inspect the actual delta rather than trusting the report.

- Confirm scope held and acceptance is demonstrated.
- Confirm verification is meaningful and relevant.
- Use `REVISE` once for incomplete work still inside scope.
- Use `DISCARD` for a rejected delta, then restore safely.
- After two failed rounds, `STOP`.

DISCARD is a verdict, not permission to reset the worktree. Run
`scripts/delegate-delta restore "$SNAP"`; it verifies current non-ignored
state still equals the post snapshot, then restores only delegate paths to
pre-execute content. Concurrent change → `STOP` before restore.
Never use `git reset`, `git checkout`, `git clean`, or a blanket restore.

## Outcome logging

Lightweight and non-blocking. Prefer omitting unknown fields over inventing
precision.

```text
requested_harness:
actual_harness:
success:
revision_needed:
escaped_defect:
cost:
duration:
```

Use `scripts/router-log`. Logging must not block execution; a log write
failure is a warning, not a hard stop.
