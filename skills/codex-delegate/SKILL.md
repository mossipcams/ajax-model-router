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

Codex runs through `codex app-server` (native line-delimited JSON-RPC), driven by
the shared runner — the same boundary as Pi and Cursor. One app-server process
per delegation; the runner initializes the connection, starts a thread, runs one
turn with the packet, consumes the structured events, and feeds the final agent
message into the same `extract-report` contract. The mode selects the sandbox:

| Mode | Sandbox |
|---|---|
| `packet-critique` | `read-only` |
| `implementation` | `workspace-write` |

```bash
scripts/run-delegate --tool codex --model "$MODEL" \
  --sandbox <read-only|workspace-write> \
  --reasoning-effort xhigh \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Reasoning effort stays `xhigh`. Authentication uses the existing Codex/ChatGPT
login (resolved from `~/.codex`); never force an API key. The runner prints only
the extracted structured report; the raw JSON-RPC log is preserved for debugging.

For a follow-up turn that reuses Codex's retained thread context, append
`--resume "$THREAD_ID"` (the thread id from the prior run's raw log). Timeout,
missing tool, missing report, or invalid report returns an explicit failed
`DELEGATE_REPORT`.

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
