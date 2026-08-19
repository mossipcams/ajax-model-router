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

## Preflight

```bash
command -v acpx
git status --short
```

Missing `acpx` means return `STOP`; never substitute local work,
native Cursor Task, best-of-n, or another tool inside this adapter.

Do not spawn native Task, best-of-n, or other Cursor subagents.
Implement in-process. Missing `acpx` is `STOP`, not a license to Task.

## Payloads

Every dispatch is stateless. The parent assembles a full outcome-based Dispatch
prompt for initial work and for every revision.

## Invocation

The shared runner dispatches through acpx ACP (`cursor` profile) using one-shot `exec`
only — no saved sessions. The router-selected model is passed as
`--model "$MODEL"`. Full ACP NDJSON is preserved in the raw log; only the
validated structured report is printed.

```bash
scripts/run-delegate --tool cursor --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Timeout, malformed/unknown events, missing terminal events, missing report, or
invalid report returns an explicit failed `DELEGATE_REPORT`. Return the
extracted report unchanged for parent acceptance.
