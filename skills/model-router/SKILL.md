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
3. **Reroute** — emit a new decision after evidence gathering, packet build, critique,
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
  ACTION: LOCAL | GATHER_EVIDENCE | BUILD_PACKET | CRITIQUE_PACKET | DELEGATE | REVIEW | STOP
  LANE: local | tdd-implementation-packet | cursor-delegate | opencode-delegate | codex-delegate | NONE
  MODE: <lane mode or NONE>
  MODEL: <exact ID from Model Registry or NONE>
  PACKET_STATUS: READY | BLOCKED | NOT_REQUIRED
  PACKET_REBUILD_COUNT: 0 | 1 | NONE
  PACKET_CRITIQUE_COUNT: 0 | 1 | 2 | NONE
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

| Rule ID | Condition | `ACTION` | `LANE` | `MODE` | Model key | `PACKET_STATUS` |
|---|---|---|---|---|---|---|
| `R-GATE` | Delegate write finished and its delta is not yet gated | `LOCAL` | `local` | `NONE` | none | `READY` |
| `R-QA` | Pure Q&A or planning | `LOCAL` | `local` | `NONE` | none | `NOT_REQUIRED` |
| `R-LOCAL-TINY` | Candidate edit is one file, at most 10 changed lines, and adds no branch, loop, parser, auth, security, or data-loss path | `LOCAL` | `local` | `NONE` | none | `NOT_REQUIRED` |
| `R-REVIEW` | Standalone or broad review request | `REVIEW` | `local` | `NONE` | none | `NOT_REQUIRED` |
| `R-EVIDENCE` | Any required evidence category is missing | `GATHER_EVIDENCE` | `local` | `evidence` | none | `BLOCKED` |
| `R-BUILD` | Required evidence is complete and no packet exists | `BUILD_PACKET` | `tdd-implementation-packet` | `build` | none | `BLOCKED` |
| `R-CRITIQUE` | Candidate packet is mechanically `READY`, selects a `CODEX` or `GLM` lane, records unresolved specification or architecture uncertainty, and critique count is 0 | `CRITIQUE_PACKET` | `codex-delegate` | `packet-critique` | `CODEX` | `READY` |
| `R-REBUILD` | First packet critique returned `BLOCK`, rebuild count is 0, and required evidence is complete | `BUILD_PACKET` | `tdd-implementation-packet` | `build` | none | `BLOCKED` |
| `R-RECRITIQUE` | Rebuilt packet is mechanically `READY`, still records uncertainty, and critique count is 1 | `CRITIQUE_PACKET` | `codex-delegate` | `packet-critique` | `CODEX` | `READY` |
| `R-CRITIQUE-STOP` | Second packet critique returned `BLOCK` and critique count is 2 | `STOP` | `codex-delegate` | `packet-critique` | `CODEX` | `BLOCKED` |
| `R-DELEGATE` | Packet is mechanically `READY` and either has no unresolved uncertainty initially or after one rebuild, or its latest critique passed | `DELEGATE` | implementation lane below | implementation mode below | implementation model below | `READY` |
| `R-STOP` | Selected tool is unavailable and every other implementation lane was tried or is also unavailable; or the task exceeds one bounded behavior | `STOP` | attempted lane | attempted mode | attempted model | current status |

### Implementation Lane

For `DELEGATE`, use the rules below.
Risk and reasoning depth take precedence over file category. TypeScript alone
is not a frontend signal. Follow the first matching rule.

| Packet facts | Lane | Mode | Model key |
|---|---|---|---|
| User explicitly asked Codex to implement | `codex-delegate` | `implementation` | `CODEX` |
| Packet records unresolved specification or architecture uncertainty | `opencode-delegate` | `implement` or `test-only` | `GLM` |
| Authentication, security, data-loss, backend, server, session, PTY, or supervisor work; or architecture-wide reasoning | `opencode-delegate` | `implement` or `test-only` | `GLM` |
| Routine docs, generated cleanup, exact replacements, named boilerplate, shallow tests-only work, or any bounded change with exact anchors touching at most 2 files and roughly 60 changed lines with no term from the risk row above — including frontend UI that fits those bounds | `opencode-delegate` | `implement` or `test-only` | `MINIMAX` |
| Frontend UI behavior with bounded files and anchors that exceeds the MiniMax row (more than 2 files, or roughly more than ~60 changed lines, or multi-surface visual/layout work) | `cursor-delegate` | `implement` or `test-only` | `CURSOR` |
| No lane matched | `opencode-delegate` | `implement` or `test-only` | `GLM` |

Before selecting `CURSOR`, verify the MiniMax row does not match. A path under
`ajax-web`, CSS, or terminal surface is not by itself a Cursor signal.

Tests-only work keeps the lane selected by reasoning depth. It changes `MODE`
to `test-only`; it does not select MiniMax by itself.

If the selected lane's tool is unavailable, reroute the same packet once to
the next matching lane and record it in `ESCALATE_IF`; never retry the same
unavailable tool. `STOP` only when no lane remains.

Packet critique applies only to `CODEX` and `GLM` implementation lanes and only
when the mechanically valid packet records unresolved specification or
architecture uncertainty. A first `BLOCK` permits one evidence pass, one packet
rebuild, and one re-critique. A second `BLOCK` returns `STOP` with the unresolved
blockers. A blocked or mechanically invalid packet is never dispatched.
`MINIMAX` and `CURSOR` packets dispatch directly once `READY`; the parent Review
Gate is their only review.

`GATHER_EVIDENCE` is parent-local and read-only. Use direct search and file
inspection for localized work, Serena when semantic relationships are unclear,
ast-grep for structural searches or repeated edits, and Graphify only for
unfamiliar cross-module or architecture-sensitive work. Record concise findings
and exact anchors, then reroute. Never send a `BLOCKED` packet to a write mode.

Standalone review uses `PACKET_STATUS: NOT_REQUIRED` and does not need an
implementation packet. The orchestrating parent performs the review locally
over the requested scope and current diff, and returns the `REVIEW_REPORT`
schema with severity-ordered file:line findings covering correctness,
regressions, security, error handling, test gaps, and cross-file integration.
Reviews are never delegated; a Codex review happens only when the user
explicitly requests one, outside this router.

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

Packet critique returns exactly:

```yaml
PACKET_REVIEW:
  VERDICT: PASS | BLOCK
  REVIEWED_UNCERTAINTY: SPECIFICATION | ARCHITECTURE | BOTH
  PACKET_CHECK: PASS
  BLOCKERS:
    - TYPE: SPECIFICATION | ARCHITECTURE
      ISSUE: <specific unresolved ambiguity>
      REQUIRED_EVIDENCE: <smallest evidence needed>
  REMAINING_RISKS: []
```

`BLOCKERS` is empty for `PASS`. Missing fields make the review `BLOCK`.

## Routing Calibration Log

After every routing decision except pure Q&A and after every Review Gate, use
`scripts/router-log`. Its v2 TSV row records, in order:

1. schema version and UTC timestamp,
2. stable repository identifier, task ID, and round,
3. route-rule ID, task kind, risk class, action, lane, and model,
4. estimated file and line scope,
5. critique result and procedural gate result,
6. escalation destination and reason,
7. failure classification, verification result, and CI result,
8. duration and provider token usage.

Every field is required. Record `UNKNOWN` where a metric is unavailable; never
infer it. Use the canonical origin identity for the repository, not a worktree
basename. A parent `ACCEPT` is only a procedural gate result. Verification,
CI, and a later `ESCAPED_DEFECT` are independent signals.

Legacy eight-column rows remain readable but are excluded from any metric that
requires v2 fields. Use `OBSERVATION` with route-rule `NONE` for later CI or
escaped-defect facts; these do not count as route decisions. An `EPOCH` row
starts a new calibration window.

## Routing Calibration

Run a calibration pass only when the user asks. `scripts/router-log-summary`
calculates every retained tripwire directly from v2 fields:

- a lane/model has non-`ACCEPT` procedural gates in 2 consecutive rounds or 3
  of its last 10 gated rounds;
- the cheap model escalated in 3 of its last 10 implementation rounds;
- a route-rule ID did not fire in the last 50 decisions;
- critique passed 20 consecutive recorded critiques;
- the cheap model took none of the last 15 implementation dispatches.

Frozen calibration controls: invariants, report schemas, snapshots, Review
Gate acceptance rules, DISCARD restoration, and registry model IDs. Adjustable
controls: route conditions and thresholds, lane definitions, critique scope,
and escalation rules.

For each fired tripwire, make the smallest supported rule edit, record it in
`CALIBRATION.md`, run `scripts/check-contracts`, and use the resulting commit as
the checkpoint. No tripwire, no edit.

## Pre-dispatch Snapshot

Before any write mode, snapshot the current non-ignored worktree so pre-existing
changes remain distinguishable from delegate edits:

```bash
SNAP="$(mktemp -d)"
scripts/delegate-snapshot "$SNAP" pre
```

After dispatch, capture and inspect the deterministic pre-versus-post delta:

```bash
scripts/delegate-snapshot "$SNAP" post
scripts/delegate-delta inspect "$SNAP" --allowed <exact-path> [--allowed <exact-path>...]
```

`delta.json` separates preexisting paths from delegate-created, modified,
deleted, and mode-changed paths, records overlap and scope violations, and
`delta.patch` contains the complete inspectable patch including new untracked
file contents.

Keep `$SNAP` until the Review Gate finishes. If any snapshot command fails,
return `STOP` before dispatch.

## Delegate Prompt

An initial implementation dispatch sends exactly this wrapper followed by the
full READY packet. A cross-tool revision sends the same full payload plus Review
Gate findings. A Same-session Cursor resume sends only findings and immutable
constraints because the session retains the packet; this is the sole full-packet
exception.

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

Return exactly the router's DELEGATE_REPORT schema between these marker lines:
ROUTER_REPORT_BEGIN
<DELEGATE_REPORT YAML>
ROUTER_REPORT_END
Include every command's actual exit code and a short output excerpt. Do not
summarize missing evidence.

<TDD implementation packet>
```

## Review Gate

The gate is parent-local work; it needs no delegate dispatch. After any
delegate write mode, inspect the generated pre-versus-post artifacts:

```bash
cat "$SNAP/delta.json"
cat "$SNAP/delta.patch"
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

Use `REVISE` once for incomplete work inside allowed scope. A failed `MINIMAX`
round revises on `GLM` with the same packet plus the findings; never pay for a
second `MINIMAX` attempt. When the same tool retries and supports resume
(`cursor-agent --resume`), send only the findings and constraint reminders, not
the packet again. Use `DISCARD` for a rejected delegate delta. After two failed
rounds, return `STOP` and report both attempts.

DISCARD is a verdict, not permission to reset the worktree. Run
`scripts/delegate-delta restore "$SNAP"`; it first verifies the complete current
non-ignored state still equals the post snapshot, then restores only delegate
paths to exact pre-dispatch content and modes. Any concurrent change returns
`STOP` before restoration begins. Never use `git reset`, `git checkout`,
`git clean`, or a blanket restore.
