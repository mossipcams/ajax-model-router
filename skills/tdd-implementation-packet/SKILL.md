---
name: tdd-implementation-packet
description: Create a READY or BLOCKED implementation packet after required code context is collected.
---

# TDD Implementation Packet

Create one executable packet for one bounded task. The packet must expose
whether it is dispatchable; completeness is never inferred from section count.

## Inputs

Collect or explicitly mark the applicability of:

1. Graphify architecture boundaries
2. Serena semantic code context and reusable patterns
3. ast-grep code anchors
4. Desired behavior or artifact change

A missing required input makes the packet `BLOCKED`. It is not a stop condition
inside a `READY` packet. `NOT_REQUIRED` needs a task-specific reason; tool
unavailability alone is not a reason.

## Task Contract

Set these fields before writing instructions:

```yaml
PACKET_STATUS: READY | BLOCKED
TASK_KIND: behavior | tests-only | docs-only | mechanical
TEST_FIRST: REQUIRED | NOT_APPLICABLE
PRODUCTION_EDIT: REQUIRED | FORBIDDEN
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
- Graphify, Serena, and ast-grep evidence when applicable,
- an explicit `NOT_REQUIRED` reason for each inapplicable context source,
- exact edit anchors and instructions,
- verification commands and acceptance criteria,
- observable stop conditions.

If any item is absent, return `BLOCKED`, list it in `BLOCKERS`, and stop. A
`BLOCKED` packet contains no test or edit instructions and cannot be dispatched
to a write mode.

## READY Output

Produce exactly these sections:

1. Status and task contract
2. Goal
3. Allowed files
4. Forbidden changes
5. Context evidence
6. Code anchors
7. Test-first instructions
8. Edit instructions
9. Verification commands
10. Acceptance criteria
11. Stop conditions

`Context evidence` records Graphify, Serena, and ast-grep evidence or an
explicit `NOT_REQUIRED` reason for each.

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
