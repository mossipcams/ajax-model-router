---
name: model-router
description: Pick the workflow for one bounded coding task: local, packet, delegate lane, review gate, revise, discard, or stop.
---

# Model Router

Route one bounded coding task or review: handle it locally, gather missing
context, delegate it, or stop, then gate any resulting change. Not for broad
planning or unrelated cleanup.

This skill owns every shared rule of the pipeline. The delegate skills
(`codex-delegate`, `cursor-delegate`, `opencode-delegate`) are thin adapters:
preflight plus the exact commands for one tool. If a delegate skill conflicts
with this file, this file wins.

## Pipeline

1. **Route** — emit one binding for the next action.
2. **Execute** — perform only that action under its bound lane, mode, model,
   and scope.
3. **Reroute** — emit a new decision after discovery, packet build, critique,
   delegation, or review.
4. **Gate** — accept, revise once, discard, or stop after any write action.

## Model Registry

Only this table owns provider model IDs. Route rules refer to registry keys;
the decision copies the corresponding exact ID into `MODEL`.

| Key | Model ID |
|---|---|
| `CODEX` | `gpt-5.5` |
| `CURSOR` | `composer-2.5` |
| `MINIMAX` | `opencode-go/minimax-m3` |
| `GLM` | `opencode-go/glm-5.2` |

## Routing Decision

Return exactly one binding before packet work, dispatch, or review. Use `NONE`
for fields that do not apply; never omit a field.

```yaml
ROUTING_DECISION:
  ACTION: LOCAL | BUILD_PACKET | CRITIQUE_PACKET | DISCOVER | DELEGATE | REVIEW | STOP
  LANE: local | tdd-implementation-packet | cursor-delegate | opencode-delegate | codex-delegate | NONE
  MODE: <lane mode or NONE>
  MODEL: <exact ID from Model Registry or NONE>
  PACKET_STATUS: READY | BLOCKED | NOT_REQUIRED
  ALLOWED_SCOPE: [<exact paths, read-only scope, or NONE>]
  REASON: <one sentence>
  ESCALATE_IF: [<observable conditions>]
```

The binding describes the current action, not a possible future delegate.
Emit a new decision after each action.

## Invariants

- Current directory is already the task worktree.
- Never create worktrees, branches, commits, pushes, merges, rebases, or
  branch switches. No delegate may either.
- Do not delegate from a vague prompt. Implementation delegates require a
  complete packet.
- Parent reviews every delegate diff before accepting it.
- Empty diff plus a success claim is failure.
- Stop after two failed delegate rounds.

## Route

Follow the first matching action rule. Copy a selected registry value into
`MODEL`; never use an alias.

| Condition | `ACTION` | `LANE` | `MODE` | Model key | `PACKET_STATUS` |
|---|---|---|---|---|---|
| Pure Q&A or planning | `LOCAL` | `local` | `NONE` | none | `NOT_REQUIRED` |
| Candidate edit is one file, at most 10 changed lines, and adds no branch, loop, parser, auth, security, or data-loss path | `LOCAL` | `local` | `NONE` | none | `NOT_REQUIRED` |
| Standalone or broad review request | `REVIEW` | `codex-delegate` | `final-review` | `CODEX` | `NOT_REQUIRED` |
| Delegate diff review with a packet | `REVIEW` | `codex-delegate` | `diff-review` | `CODEX` | `READY` |
| Source file or code anchors are unknown | `DISCOVER` | `opencode-delegate` | `discover` | `GLM` | `BLOCKED` |
| No packet exists, or required context is missing | `BUILD_PACKET` | `tdd-implementation-packet` | `build` | none | `BLOCKED` |
| Candidate packet is `READY` but has not passed critique | `CRITIQUE_PACKET` | `codex-delegate` | `packet-critique` | `CODEX` | `READY` |
| Packet critique returned `BLOCK` | `BUILD_PACKET` | `tdd-implementation-packet` | `build` | none | `BLOCKED` |
| Packet is `READY` and critique returned `PASS` | `DELEGATE` | implementation lane below | implementation mode below | implementation model below | `READY` |
| Selected tool is unavailable or the task exceeds one bounded behavior | `STOP` | attempted lane | attempted mode | attempted model | current status |

### Implementation Lane

For `DELEGATE`, use the rules below.
Risk and reasoning depth take precedence over file category. TypeScript alone
is not a frontend signal. Follow the first matching rule.

| Packet facts | Lane | Mode | Model key |
|---|---|---|---|
| User explicitly asked Codex to implement | `codex-delegate` | `implementation` | `CODEX` |
| Authentication, security, data-loss, backend, server, session, PTY, or supervisor work; or architecture-wide reasoning | `opencode-delegate` | `implement` or `test-only` | `GLM` |
| Routine docs, generated cleanup, exact replacements, named boilerplate, or shallow tests-only work | `opencode-delegate` | `implement` or `test-only` | `MINIMAX` |
| Frontend UI behavior with bounded files and anchors | `cursor-delegate` | `implement` or `test-only` | `CURSOR` |
| No lane matched | `opencode-delegate` | `implement` or `test-only` | `GLM` |

Tests-only work keeps the lane selected by reasoning depth. It changes `MODE`
to `test-only`; it does not select MiniMax by itself.

`DISCOVER` is read-only. Set `ALLOWED_SCOPE` to the smallest named directory or
repository scope, collect exact files and anchors, then route again. Never send
a `BLOCKED` packet to a write mode.

Standalone review uses `PACKET_STATUS: NOT_REQUIRED` and does not need an
implementation packet. Supply the requested review scope and current diff.

## Structured Reports

All delegate and review results use these schemas. Missing fields make the
result `FAILED`; parents do not infer values from prose.

```yaml
DELEGATE_REPORT:
  STATUS: COMPLETE | BLOCKED | FAILED
  SUMMARY: <one sentence>
  FILES_CHANGED: [<paths>]
  TEST_FIRST: PROVEN | NOT_APPLICABLE | NOT_PROVEN
  COMMAND_EVIDENCE:
    - PHASE: RED | GREEN | VERIFY | OTHER
      COMMAND: <exact command>
      EXIT_CODE: <integer>
      OUTPUT_EXCERPT: <lines proving the result>
  STOP_CONDITIONS_HIT: []
  REMAINING_RISKS: []
```

```yaml
REVIEW_REPORT:
  VERDICT: ACCEPT | REVISE | DISCARD | STOP
  FINDINGS:
    - SEVERITY: HIGH | MEDIUM | LOW
      FILE: <path>
      LINE: <line or NONE>
      ISSUE: <specific defect>
      REQUIRED_CHANGE: <smallest correction>
  VERIFICATION: [<command and exit code>]
  SCOPE_VIOLATIONS: []
  REMAINING_RISKS: []
```

When `TEST_FIRST` is `REQUIRED`, `COMMAND_EVIDENCE` must show a `RED` command
with a nonzero exit and the intended assertion failure before a `GREEN` entry
for the same focused command with exit zero. `NOT_APPLICABLE` must match the
packet task contract. A success claim without command evidence is failure.

Packet critique uses the same rule with `PACKET_REVIEW`, `VERDICT: PASS |
BLOCK`, and a structured `BLOCKERS` list.

## Pre-dispatch Snapshot

Before any write mode, snapshot the current non-ignored worktree so pre-existing
changes remain distinguishable from delegate edits:

1. Create a private temporary directory outside the worktree.
2. Record the NUL-delimited inventory from
   `git ls-files -co --exclude-standard -z`.
3. Archive the inventoried paths with contents and file modes, and record a
   SHA-256 hash for each path. Record the current `git status --porcelain=v1 -z`.
4. After dispatch, capture the same inventory, hashes, and contents. The delta
   between snapshots is the delegate delta, including created and deleted files.

Keep both snapshots until the Review Gate finishes. If snapshot creation fails,
return `STOP` before dispatch.

## Delegate Prompt

Every implementation dispatch sends exactly this wrapper followed by the full
packet. Delegate skills append only the tool- or mode-specific lines they
name; nothing else is added or removed.

```text
You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches.

Complete exactly one bounded task from the packet below.
Edit only Allowed files. Do not touch Forbidden changes. Follow Code anchors.
Run the failing test first only when TEST_FIRST is REQUIRED.
Edit production code only when PRODUCTION_EDIT is REQUIRED.
Make the smallest allowed edit needed.
Run Verification commands.
Stop if any Stop condition is hit, or if the patch would exceed roughly 400 changed lines.
No drive-by cleanup, renames, formatting sweeps, or broad refactors.

Return exactly the router's DELEGATE_REPORT schema. Include every command's
actual exit code and a short output excerpt. Do not summarize missing evidence.

<TDD implementation packet>
```

## Review Gate

After any delegate write mode, compare the pre- and post-dispatch snapshots,
then inspect the resulting delegate delta:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Run the packet verification commands independently. Accept only when all are
true:

- changed files are inside Allowed files,
- structured report fields are complete,
- red/green evidence is valid or the packet says it does not apply,
- verification passed,
- production edits match packet anchors,
- forbidden behavior did not change,
- no broad formatting or refactor sweep happened.

Use `REVISE` once for incomplete work inside allowed scope. Use `DISCARD` for a
rejected delegate delta. After two failed rounds, return `STOP` and report both
attempts.

DISCARD is a verdict, not permission to reset the worktree. Restore only paths
identified by the snapshot delta, from their exact pre-dispatch contents.
Before restoring a path, verify its current content still matches the captured post-dispatch hash; otherwise return `STOP` because a concurrent edit occurred.
Delete a delegate-created path only under the same hash check.
Never use `git reset`, `git checkout`, `git clean`, or a blanket restore.
