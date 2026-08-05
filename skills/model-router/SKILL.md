---
name: model-router
description: Pick the workflow for one bounded coding task: local, packet, delegate lane, review gate, revise, discard, or stop.
---

# Model Router

Route one bounded coding task or review: gather missing context, delegate it,
or stop, then gate any resulting change. Prefer DELEGATE for implementation.
Parent LOCAL is for architecture planning, pure Q&A, evidence gathering, and
the Review Gate — not for writing the change.

This skill owns every shared rule of the pipeline. The delegate skills
(`codex-delegate`, `cursor-delegate`, `pi-delegate`) are thin adapters:
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
| `CODEX` | `gpt-5.6-sol` |
| `CURSOR` | `composer-2.5` |
| `MINIMAX` | `opencode-go/minimax-m3` |
| `GLM` | `opencode-go/glm-5.2` |

## Routing Decision

Return exactly one binding before packet work, dispatch, or review. Use `NONE`
for fields that do not apply; never omit a field.

```yaml
ROUTING_DECISION:
  ACTION: LOCAL | GATHER_EVIDENCE | BUILD_PACKET | CRITIQUE_PACKET | DELEGATE | REVIEW | STOP
  LANE: local | tdd-implementation-packet | cursor-delegate | pi-delegate | codex-delegate | NONE
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
  complete dispatch package for the selected `dispatch_level` (`direct`,
  `compact`, or full READY packet).
- Parent reviews every delegate diff before accepting it.
- Empty diff plus a success claim is failure.
- Stop after two failed delegate rounds.

## Route

Follow the first matching action rule. Copy a selected registry value into
`MODEL`; never use an alias.

| Rule ID | Condition | `ACTION` | `LANE` | `MODE` | Model key | `PACKET_STATUS` |
|---|---|---|---|---|---|---|
| `R-GATE` | Delegate write finished and its delta is not yet gated | `LOCAL` | `local` | `NONE` | none | `READY` |
| `R-QA` | Pure Q&A or architecture planning (no implementation write) | `LOCAL` | `local` | `NONE` | none | `NOT_REQUIRED` |
| `R-REVIEW` | Standalone or broad review request | `REVIEW` | `local` | `NONE` | none | `NOT_REQUIRED` |
| `R-EVIDENCE` | Any required evidence category is missing | `GATHER_EVIDENCE` | `local` | `evidence` | none | `BLOCKED` |
| `R-BUILD` | Required evidence is complete and no packet exists | `BUILD_PACKET` | `tdd-implementation-packet` | `build` | none | `BLOCKED` |
| `R-CRITIQUE` | Candidate packet is mechanically `READY`, selects a `CODEX` or `GLM` lane, records unresolved specification or architecture uncertainty, and critique count is 0 | `CRITIQUE_PACKET` | `codex-delegate` | `packet-critique` | `CODEX` | `READY` |
| `R-REBUILD` | First packet critique returned `BLOCK`, rebuild count is 0, and required evidence is complete | `BUILD_PACKET` | `tdd-implementation-packet` | `build` | none | `BLOCKED` |
| `R-RECRITIQUE` | Rebuilt packet is mechanically `READY`, still records uncertainty, and critique count is 1 | `CRITIQUE_PACKET` | `codex-delegate` | `packet-critique` | `CODEX` | `READY` |
| `R-CRITIQUE-STOP` | Second packet critique returned `BLOCK` and critique count is 2 | `STOP` | `codex-delegate` | `packet-critique` | `CODEX` | `BLOCKED` |
| `R-SIZE-SPLIT` | Estimated changed lines ≥ 250, or the packet clearly covers more than one bounded behavior | `STOP` | `NONE` | `NONE` | none | `BLOCKED` |
| `R-DELEGATE` | Packet is mechanically `READY` and either has no unresolved uncertainty initially or after one rebuild, or its latest critique passed | `DELEGATE` | implementation lane below | implementation mode below | implementation model below | `READY` |
| `R-STOP` | Selected tool is unavailable and every other implementation lane was tried or is also unavailable; or the task exceeds one bounded behavior | `STOP` | attempted lane | attempted mode | attempted model | current status |

`R-SIZE-SPLIT` is a pre-dispatch gate: do not `DELEGATE`. Split into smaller
packets, rebuild, and reroute. Log `escalation_reason=pre-dispatch-size-split`.
`UNKNOWN` estimates do not trip the line threshold; only a known estimate ≥ 250
does. The post-delta ~400 changed-line stop in the Delegate Prompt / Review Gate
remains the backstop when the estimate was wrong. This is not a Composer-only
ACCEPT tripwire.

### Implementation Lane

For `DELEGATE`, use the rules below.
Default to `CURSOR`. Divert only when an exception row matches.
Risk and reasoning depth still take precedence over file category when choosing
among exceptions. TypeScript alone is not a frontend signal. Follow the first
matching rule.

| Packet facts | Lane | Mode | Model key |
|---|---|---|---|
| User explicitly asked Codex to implement | `codex-delegate` | `implementation` | `CODEX` |
| Packet records unresolved specification or architecture uncertainty | `pi-delegate` | `implement` or `test-only` | `GLM` |
| Routine docs, generated cleanup, exact replacements, or named boilerplate with exact anchors, at most 2 files and roughly 60 changed lines, and no authentication/security/data-loss concerns | `pi-delegate` | `implement` or `test-only` | `MINIMAX` |
| No exception matched | `cursor-delegate` | `implement` or `test-only` | `CURSOR` |

Do not divert to MiniMax or GLM just because the change is backend, PTY,
frontend, multi-file, or under `ajax-web` — those stay on `CURSOR` by default.
MiniMax is only the shallow docs/boilerplate row above; GLM is only recorded
uncertainty (or a MiniMax revise escalation).

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

## Verification principle

Ajax Model Router requires evidence that the implementation works.
It does not require test-first development or TDD.
Tests should be used when they are the most effective verification method.

Every implementation task defines a verification plan appropriate to the change.
Testing is one verification method, not the controlling workflow. Behavior
changes do **not** automatically require a new failing test, RED evidence,
GREEN sequencing, or `TEST_FIRST: REQUIRED`.

## Structured Reports

All delegate and review results use these schemas. Missing fields make the
result `FAILED`; parents do not infer values from prose.

```yaml
DELEGATE_REPORT:
  STATUS: COMPLETE | BLOCKED | FAILED
  CHANGED_FILES: [<paths>]
  VERIFICATION:
    - TYPE: test | existing_test | build | typecheck | lint | static_analysis | integration | browser | manual | other
      COMMAND: <command or NONE>
      STEPS: []
      RESULT: pass | fail | skipped | blocked
      DETAILS: <short result note>
  CONCERNS: []
```

Blocked work uses the same schema with `STATUS: BLOCKED`, empty or partial
`VERIFICATION`, and at least one concern:

```yaml
DELEGATE_REPORT:
  STATUS: BLOCKED
  CHANGED_FILES: []
  VERIFICATION: []
  CONCERNS:
    - TYPE: verification_unclear
      DETAIL: <what is unclear>
      RECOMMENDED_ACTION: <smallest next step>
```

A success claim without verification entries is failure. Failed verification
items make `COMPLETE` invalid.

Legacy reports that still carry `TEST_FIRST` / `COMMAND_EVIDENCE` with
`PHASE: RED|GREEN|VERIFY|OTHER` are accepted by `scripts/check-report` with a
deprecation warning; RED/GREEN sequencing is not enforced. Map their commands
into `VERIFICATION` when reviewing.

```yaml
REVIEW_REPORT:
  VERDICT: ACCEPT | REVISE | DISCARD | STOP
  FINDINGS:
    - SEVERITY: HIGH | MEDIUM | LOW
      FILE: <path>
      LINE: <line or NONE>
      ISSUE: <specific defect>
      REQUIRED_CHANGE: <smallest correction>
  VERIFICATION: [<method, command or steps, and result>]
  SCOPE_VIOLATIONS: []
  REMAINING_RISKS: []
```

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

Optional v3 trailing fields (when known; otherwise omit the whole trailer):

9. verification_types (comma-separated), new_tests_added, existing_tests_run,
   manual_checks_run, verification_passed, scope_violation, retry_count.

Every required v2 field is required. Record `UNKNOWN` where a metric is
unavailable; never infer it. Use the canonical origin identity for the
repository, not a worktree basename. A parent `ACCEPT` is only a procedural
gate result. Verification, CI, and a later `ESCAPED_DEFECT` are independent
signals.

Legacy eight-column rows remain readable but are excluded from any metric that
requires v2 fields. Use `OBSERVATION` with route-rule `NONE` for later CI or
escaped-defect facts; these do not count as route decisions. An `EPOCH` row
starts a new calibration window.

`scripts/router-log-summary` also aggregates verification-method usage when v3
trailers are present. Do not claim removing TDD improves quality or token use
without measured data.

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

Write-mode dispatches run inside the lifecycle transaction. The transaction
creates the pre-dispatch snapshot, runs the delegate transport, captures the
post snapshot, and writes `delta.json` / `delta.patch` under
`snapshot_directory`. Parents should not re-run those deterministic steps by
hand unless debugging a failed transaction.

Manual equivalents (still valid for recovery):

```bash
SNAP="$(mktemp -d)"
scripts/delegate-snapshot "$SNAP" pre
# ... delegate ...
scripts/delegate-snapshot "$SNAP" post
scripts/delegate-delta inspect "$SNAP" --allowed <exact-path> [--allowed <exact-path>...]
```

`delta.json` separates preexisting paths from delegate-created, modified,
deleted, and mode-changed paths, records overlap and scope violations, and
`delta.patch` contains the complete inspectable patch including new untracked
file contents.

Keep `$SNAP` / `snapshot_directory` until the Review Gate finishes. If any
snapshot command fails, return `STOP` before dispatch.

## Transaction lifecycle

Router write-mode work is one transaction coordinated by internal lifecycle
hooks (not Git hooks, not a user plugin system):

```text
classify
→ before_dispatch
→ build_dispatch
→ validate_dispatch
→ snapshot
→ delegate
→ after_delegate
→ run_verification
→ before_review
→ review_delta (parent Review Gate)
→ after_review
→ log_calibration
```

`classify` and `review_delta` stay parent-owned. Hooks never invoke another
language model, never rewrite packets into prose, and never perform semantic
routing. They exist to remove deterministic work from prompts.

Each stage receives a normalized context object:

```json
{
  "task_id": "",
  "dispatch_level": "direct",
  "risk": "low",
  "provider": "",
  "model": "",
  "allowed_files": [],
  "acceptance": [],
  "working_directory": "",
  "snapshot_directory": ""
}
```

Run the deterministic stages with:

```bash
scripts/run-transaction --context context.json --until-stage before_review
# parent Review Gate over review_bundle.json
scripts/run-transaction --context context.json \
  --from-stage after_review --until-stage log_calibration \
  --gate-result ACCEPT
```

Default `--until-stage` is `before_review`, which emits
`snapshot_directory/run/review_bundle.json` and status `AWAITING_REVIEW`.

### Dispatch levels

| Level | When | Package |
|---|---|---|
| `direct` | Low risk, bounds already known | User request + allowed files + acceptance + stop conditions. Verification expectations optional; delegate may select methods after inspecting the repo. No READY TDD packet, code anchors, or parent-side test design required. |
| `compact` | Medium risk | READY contract + Task / Allowed / Forbidden / Acceptance / Constraints / Verification / Stop if. Useful anchors optional. No Context evidence, Test-first, or RED/GREEN. |
| `full` | High risk, architecture/security-sensitive, or ambiguous | Implementation packet validated by `scripts/check-packet` (outcome-based verification; legacy TDD packets accepted with deprecation). |

Validate with `scripts/check-dispatch LEVEL PATH` (`full` delegates to
`check-packet`). Escalate `direct → compact → full` while reusing snapshots,
diffs, verification results, and calibration/token artifacts under
`snapshot_directory` unless they are stale or invalid.

### Hook responsibilities

- `before_dispatch` — normalize paths/metadata, enforce size limits, prepare
  snapshot dir, reject invalid context before tokens.
- `build_dispatch` / `validate_dispatch` — minimum package for the level;
  fail closed via `check-dispatch`.
- `snapshot` — pre-dispatch capture with evidence reuse.
- `delegate` — existing `scripts/run-delegate` transport only.
- `after_delegate` — post snapshot, delta, compact report fields, scope
  violations, token fields when available. No narrative summaries.
- `run_verification` — run known verification commands; record exit codes/excerpts.
- `before_review` — smallest review bundle: request, acceptance, changed
  files, delta hunks, verification results, delegate concerns, scope
  violations. Excludes transcript, full packet, repo summaries, raw reasoning.
- `after_review` / `log_calibration` — persist review artifacts and append a
  calibration row (never invent metrics).

## Delegate Prompt

An initial implementation dispatch sends exactly this wrapper followed by the
minimum dispatch package for the selected `dispatch_level` (`direct`,
`compact`, or full implementation packet). A cross-tool revision sends the same
full payload plus Review Gate findings. A Same-session Cursor resume sends only
findings and immutable constraints because the session retains the packet;
this is the sole full-packet exception.

```text
You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches.

Complete exactly one bounded task from the packet below.
Edit only Allowed files / Scope.allowed. Do not touch Forbidden changes.
Follow Code anchors when provided.
Make the smallest allowed edit needed.
Select and run verification appropriate to the change. Testing is one method,
not a required workflow. Do not skip verification.
Stop if any Stop condition is hit, or if the patch would exceed roughly 400 changed lines.
No drive-by cleanup, renames, formatting sweeps, or broad refactors.

Return exactly the router's DELEGATE_REPORT schema between these marker lines:
ROUTER_REPORT_BEGIN
<DELEGATE_REPORT YAML>
ROUTER_REPORT_END
Identify what was verified and the result. Do not write a long narrative unless
a material concern requires explanation.

<implementation packet>
```

## Review Gate

The gate is parent-local work; it needs no delegate dispatch. After any
delegate write mode, inspect the transaction review bundle and delta artifacts:

```bash
cat "$SNAP/run/review_bundle.json"
cat "$SNAP/delta.json"
cat "$SNAP/delta.patch"
```

Evaluate:

- whether acceptance criteria were met,
- whether the diff stayed within scope,
- whether verification was relevant to the change,
- whether verification completed successfully,
- whether broader regression checks were appropriate,
- whether any material risk remains,
- whether the implementation introduced unrelated changes.

Accept only when those checks pass and structured report fields are complete.

Do **not** fail solely because:

- no new tests were added,
- no test was written before implementation,
- no RED evidence exists,
- no GREEN sequence exists,
- verification used build, browser, typecheck, integration, or manual checks
  instead of tests.

Fail when:

- no meaningful verification was performed,
- verification results are missing or failed,
- manual verification is vague or lacks steps and expected results,
- the selected verification clearly cannot validate the changed behavior,
- scope was exceeded,
- acceptance criteria were not demonstrated,
- high-risk behavior lacks adequate regression protection,
- the diff introduces unreviewed or unrelated changes.

Review evidence quality, not adherence to TDD.

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
