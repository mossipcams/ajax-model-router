---
name: tdd-implementation-packet
description: Create a READY or BLOCKED implementation packet after required code context is collected.
---

# TDD Implementation Packet

Create one executable packet for one bounded task. The packet must expose
whether it is dispatchable; completeness is never inferred from section count.

## Inputs

Collect concise evidence for the categories the task needs:

1. Desired behavior
2. Exact source and test anchors
3. Existing implementation or test patterns to reuse
4. Relevant architecture boundaries when the change crosses modules or dependencies

Acquisition is proportional to uncertainty. Use `rg` and direct file inspection
for localized changes, Serena when semantic relationships are unclear,
ast-grep for structural search or repeated mechanical edits, and Graphify only
for unfamiliar cross-module or architecture-sensitive work. These are methods,
not packet requirements. Record evidence and anchors, not unused-tool ceremony.

A missing required evidence category makes the packet `BLOCKED` and routes to
`GATHER_EVIDENCE`. It is not a stop condition inside a `READY` packet.

## Task Contract

Set these fields before writing instructions:

```yaml
PACKET_STATUS: READY | BLOCKED
TASK_KIND: behavior | tests-only | docs-only | mechanical
TEST_FIRST: REQUIRED | NOT_APPLICABLE
PRODUCTION_EDIT: REQUIRED | FORBIDDEN
UNRESOLVED_UNCERTAINTY: NONE | SPECIFICATION | ARCHITECTURE | BOTH
BLOCKERS: []
```

| `TASK_KIND` | `TEST_FIRST` | `PRODUCTION_EDIT` | Minimum evidence |
|---|---|---|---|
| `behavior` | `REQUIRED` | `REQUIRED` | Intended failing assertion, exact production anchor, red and green commands |
| `tests-only` | `NOT_APPLICABLE` | `FORBIDDEN` | Existing behavior source and exact test anchor |
| `docs-only` | `NOT_APPLICABLE` | `FORBIDDEN` | Named source of truth and exact document anchor |
| `mechanical` | `NOT_APPLICABLE` | `REQUIRED` or `FORBIDDEN` | Exact search pattern, replacement, and expected match count |

File category never determines reasoning depth or delegate lane.

## Readiness

`READY` requires:

- exact allowed files and forbidden changes,
- a bounded goal and task contract,
- concise evidence for each applicable category above,
- exact edit anchors and instructions,
- verification commands and acceptance criteria,
- observable stop conditions.

Run `scripts/check-packet <packet>` before routing a candidate packet. Script
failure makes it `BLOCKED`; do not spend a critique call on mechanical defects.

If any item is absent, return `BLOCKED`, list it in `BLOCKERS`, and stop. A
`BLOCKED` packet contains no test or edit instructions and cannot be dispatched
to a write mode.

## READY Output

After the task-contract fields, produce exactly these headings:

1. `## Goal`
2. `## Allowed files`
3. `## Forbidden changes`
4. `## Context evidence`
5. `## Code anchors`
6. `## Test-first instructions`
7. `## Edit instructions`
8. `## Verification commands`
9. `## Acceptance criteria`
10. `## Stop conditions`

`Context evidence` records category, finding, and exact anchor. Evidence is
anchors and minimal excerpts, never whole files or a list of unused tools; the
packet may be resent, so every excess line is paid for repeatedly.

`Test-first instructions` names the test, failing assertion, and focused red
command only when `TEST_FIRST` is `REQUIRED`; otherwise write
`NOT_APPLICABLE: <reason>`.

`Edit instructions` name the exact production symbol or document/test anchor.
When `PRODUCTION_EDIT` is `FORBIDDEN`, state that constraint instead of
inventing a production change.

`Verification commands` list focused checks first and broader checks only when
the blast radius requires them.

`Stop conditions` are future observable conflicts such as edits outside allowed
files, changed anchors, unrelated failures, or scope growth. They never hide
missing packet inputs.
