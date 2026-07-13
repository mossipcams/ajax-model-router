---
name: codex-delegate
description: Run Codex only from a model-router ROUTING_DECISION.
---

# Codex Delegate

Thin adapter for router-selected Codex work. Do not reconstruct routing from
the user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask
the parent to run `model-router`.

Required inputs:

- mode: `packet-critique` or `implementation`
- model: the exact `MODEL` from the router decision
- `READY` packet for `implementation`
- candidate packet for `packet-critique`

Standalone reviews are not a Codex lane; the orchestrating parent reviews
locally.

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
| `packet-critique` | `codex exec --model "$MODEL" --sandbox read-only --output-last-message /tmp/codex-report.md -` |
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

After `implementation`, return to the router's Review Gate.
