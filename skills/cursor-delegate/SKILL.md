---
name: cursor-delegate
description: Run Cursor CLI only from a model-router ROUTING_DECISION.
---

# Cursor Delegate

Thin adapter for a router-selected Cursor lane. Do not reconstruct routing from
the user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- mode: `implement`, `test-only`, or `review`
- model: the exact `MODEL` from the router decision
- allowed scope: the decision's `ALLOWED_SCOPE`
- the router prompt and `READY` packet for write modes
- review context for `review`
- `CHAT_ID` only when continuing an existing Cursor conversation

## Preflight

```bash
command -v cursor-agent
git status --short
```

Missing `cursor-agent` means return `STOP`; never substitute local work or
another tool inside this adapter.

## Invocation

| Mode | Command | Required prompt constraint |
|---|---|---|
| `implement` | `cursor-agent -p -f --trust --model "$MODEL"` | Follow the packet and edit only allowed files. |
| `test-only` | `cursor-agent -p -f --trust --model "$MODEL"` | Do not edit production code. |
| `review` | `cursor-agent -p --plan --trust --model "$MODEL"` | Read only; return the router's `REVIEW_REPORT` with file:line findings. |

Resume keeps the original mode and adds `--resume "$CHAT_ID"`; `resume` is not
a separate mode.

```bash
cursor-agent -p -f --trust --model "$MODEL" > /tmp/cursor-run.log 2>&1 <<'EOF'
<router prompt and packet>
EOF
tail -80 /tmp/cursor-run.log
```

Return the tool report unchanged to the router's Review Gate.
