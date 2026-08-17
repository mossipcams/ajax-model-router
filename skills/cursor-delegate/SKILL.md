---
name: cursor-delegate
description: Run Cursor CLI only from a model-router EXECUTION decision.
---

# Cursor Delegate

Thin adapter for a router-selected Cursor agent. Do not reconstruct routing
from the user request. If no `EXECUTION` is supplied, return `STOP` and ask
the parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the execution decision
- allowed scope: the decision's `SCOPE`
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

- **Initial dispatch**: the router's outcome-based Dispatch prompt.
- **Same-session Cursor resume**: Review findings and immutable constraints
  (task ID, scope, acceptance, verification expectation). Do not resend the
  full prompt when `CHAT_ID` retains context.
- **Cross-tool revision**: full Dispatch prompt plus findings.

## Invocation

The shared runner uses Cursor's native stream output:
`-p -f --trust --model "$MODEL" --output-format stream-json
--stream-partial-output`, plus `--resume "$CHAT_ID"` for a same-session
revision. Full JSONL/stderr is preserved in the raw log; only the validated
structured report is printed.

```bash
scripts/run-delegate --tool cursor --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

For resume, append `--resume "$CHAT_ID"`. Timeout, malformed/unknown events,
missing terminal events, missing report, or invalid report returns an explicit
failed `DELEGATE_REPORT`. Return the extracted report unchanged for parent
acceptance.
