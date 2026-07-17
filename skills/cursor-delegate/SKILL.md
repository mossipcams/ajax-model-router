---
name: cursor-delegate
description: Run Cursor CLI only from a model-router ROUTING_DECISION.
---

# Cursor Delegate

Thin adapter for a router-selected Cursor lane. Do not reconstruct routing from
the user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- mode: `implement` or `test-only`
- model: the exact `MODEL` from the router decision
- allowed scope: the decision's `ALLOWED_SCOPE`
- the prepared prompt file and persistent run directory
- `CHAT_ID` only when continuing an existing Cursor conversation

## Preflight

```bash
command -v cursor-agent
git status --short
```

Missing `cursor-agent` means return `STOP`; never substitute local work or
another tool inside this adapter.

## Payloads

- **Initial dispatch**: the router wrapper followed by the full READY packet.
- **Same-session Cursor resume**: the Review Gate findings and immutable constraints
  (task ID, Allowed files, Forbidden changes, verification, and
  stop conditions). It does not resend the full packet because `CHAT_ID`
  retains that context.
- **Cross-tool revision**: the router wrapper, full READY packet, and Review
  Gate findings because the new tool has no session context.

Resume keeps the original mode; `resume` is not a separate mode.

## Invocation

The shared runner uses only flags present in installed `cursor-agent --help`:
`-p -f --trust --model`, plus `--resume` for a same-session revision. It
preserves the full raw log and prints only the complete structured report.

```bash
scripts/run-delegate --tool cursor --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

For resume, append `--resume "$CHAT_ID"`. Timeout, missing tool, missing report,
or invalid report returns an explicit failed `DELEGATE_REPORT`. Return the
extracted report unchanged to the router's Review Gate.
