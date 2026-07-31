---
name: tdd-implementation-packet
description: Create a READY or BLOCKED implementation packet with acceptance criteria and outcome-based verification.
---

# Implementation Packet

Create one executable packet for one bounded task. The packet must expose
whether it is dispatchable; completeness is never inferred from section count.

The lane id remains `tdd-implementation-packet` for routing and calibration
compatibility. This skill does **not** require test-first development, RED/GREEN
evidence, or a newly written failing test before production edits.

Ajax Model Router requires evidence that the implementation works. It does not
require TDD. Tests should be used when they are the most effective verification
method.

## Inputs

Collect concise evidence proportional to uncertainty:

1. Desired outcome / acceptance criteria
2. Exact source anchors when known (optional for direct/compact parent dispatch)
3. Existing patterns to reuse when helpful
4. Architecture boundaries when the change crosses modules or dependencies

Acquisition: `rg` and direct file inspection for localized work, Serena when
semantic relationships are unclear, ast-grep for structural search or repeated
mechanical edits, and Graphify only for unfamiliar cross-module work. These are
methods, not packet requirements.

A missing required evidence category makes the packet `BLOCKED` and routes to
`GATHER_EVIDENCE`. It is not a stop condition inside a `READY` packet.

## Task Contract

```yaml
PACKET_STATUS: READY | BLOCKED
UNRESOLVED_UNCERTAINTY: NONE | SPECIFICATION | ARCHITECTURE | BOTH
BLOCKERS: []
```

Optional when useful (not required):

```yaml
TASK_KIND: behavior | tests-only | docs-only | mechanical
```

Do not emit `TEST_FIRST` or `PRODUCTION_EDIT` contract fields. Production edits
are governed by Allowed/Forbidden scope and acceptance criteria.

## Verification model

Every READY packet includes a verification plan appropriate to the change:

```yaml
verification:
  methods:
    - type: test | existing_test | build | typecheck | lint | static_analysis | integration | browser | manual | other
      command: <optional command>
      steps: <optional manual steps>
      expected: <expected result>
  broader_checks:
    - <optional broader commands or checks>
  reason: <brief explanation of why this verification is sufficient>
```

Testing is one method, not the controlling workflow. New tests, existing tests,
typecheck, lint, build, static analysis, integration, browser, platform, or
explicit manual checks with steps and expected outcomes are all valid when they
actually validate the changed behavior.

For direct and compact dispatches, the parent need not design tests or inspect
implementation files before delegation. The delegate may select verification
after inspecting the repository, but must not skip verification and must briefly
explain the selection.

Guidance (not mandatory mappings): pure logic → focused tests often fit; UI
wiring → typecheck/build/browser plus focused existing tests; config → parser,
build, or startup check; mechanical refactor → existing suite/typecheck/lint;
exploratory work → validate resulting behavior after implementation.

## Readiness

`READY` requires:

- a bounded task / outcome,
- allowed and forbidden scope,
- observable acceptance criteria,
- a non-empty verification plan (methods and/or commands with expected results),
- stop conditions for escalation.

Code anchors, constraints, and context evidence are optional and should be
included only when they reduce ambiguity without duplicating repository context
the delegate can read.

Run `scripts/check-packet <packet>` before routing. Script failure makes it
`BLOCKED`; do not spend a critique call on mechanical defects.

If any required item is absent, return `BLOCKED`, list it in `BLOCKERS`, and
stop. A `BLOCKED` packet cannot be dispatched to a write mode.

## READY Output

After the task-contract fields, produce exactly these headings:

1. `## Task`
2. `## Scope` (include Allowed and Forbidden lists)
3. `## Acceptance`
4. `## Constraints` (write `NONE` when there are none)
5. `## Verification`
6. `## Stop if`

Optional additional sections when useful: `## Code anchors`, `## Context
evidence`, `## Edit instructions`. Do not emit a Test-first instructions
section.

Legacy packets that still carry `TEST_FIRST` / `## Test-first instructions` are
accepted by `check-packet` with a deprecation warning; RED/GREEN sequencing is
ignored and verification commands are treated as general verification.

## Stop if

Stop conditions are future observable conflicts such as edits outside allowed
scope, unmet acceptance criteria, failed or missing verification, or scope
growth. They never hide missing packet inputs.
