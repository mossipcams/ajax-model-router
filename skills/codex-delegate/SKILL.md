---
name: codex-delegate
description: Run Codex only from a model-router ROUTING_DECISION.
---

# Codex Delegate

Thin adapter for router-selected Codex work. Do not reconstruct routing from
the user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask
the parent to run `model-router`.

Required inputs:

- mode: `packet-critique`, `diff-review`, `final-review`, or `implementation`
- model: the exact `MODEL` from the router decision
- `READY` packet for `implementation` and `diff-review`
- candidate packet for `packet-critique`
- requested scope, repository diff, and verification evidence for
  `final-review`

A standalone review does not require a packet. Route it to `final-review` with
`PACKET_STATUS: NOT_REQUIRED`.

Never use `--yolo` or `danger-full-access`.

## Preflight

```bash
command -v codex
git status --short
```

Missing `codex` means return `STOP`; never substitute local work or another tool
inside this adapter.

## Invocation

Write the prompt to `/tmp/codex-task.txt`, then run the selected command:

| Mode | Command |
|---|---|
| `packet-critique`, `diff-review` | `codex exec --model "$MODEL" --sandbox read-only --output-last-message /tmp/codex-report.md -` |
| `final-review` | `codex exec --profile xhigh --model "$MODEL" --sandbox read-only --output-last-message /tmp/codex-report.md -` |
| `implementation` | `codex exec --model "$MODEL" --sandbox workspace-write --output-last-message /tmp/codex-report.md -` |

```bash
codex exec <mode flags> - < /tmp/codex-task.txt > /tmp/codex-run.log 2>&1
cat /tmp/codex-report.md
```

Read only the report file, not the full run log.

## Prompts

`implementation` uses the router's Delegate Prompt plus the `READY` packet.

`packet-critique`:

```text
Audit this candidate packet. Return the router's PACKET_REVIEW schema.
Check readiness status, allowed scope, forbidden changes, context evidence,
anchors, task-kind requirements, verification, stop conditions, and scope size.

<candidate packet>
```

`diff-review` checks contract compliance only:

```text
Review this delegate delta against the READY packet.
Return the router's REVIEW_REPORT schema with file:line findings.
Check allowed scope, forbidden changes, evidence, anchors, behavior match, and
unrelated edits. Do not claim broad final correctness.

<packet>
<pre-dispatch to post-dispatch diff>
<verification evidence>
```

`final-review` is the broader gate:

```text
Review the requested repository scope and current diff as a senior code reviewer.
Return the router's REVIEW_REPORT schema with severity-ordered file:line findings.
Assess correctness, regressions, security, error handling, test gaps, and cross-file integration.
Use a packet when supplied, but do not require one for standalone review.

<requested scope>
<current diff>
<verification evidence>
<optional packet>
```

After `implementation`, return to the router's Review Gate.
