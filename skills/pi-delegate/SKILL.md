---
name: pi-delegate
description: Run Pi only from a model-router ROUTING_DECISION with ACTION DELEGATE.
---

# Pi Delegate

Thin transport adapter for cross-harness Pi agents (including MiniMax / GLM
model IDs). Do not reconstruct routing from the user request. If no
`ROUTING_DECISION` with `ACTION: DELEGATE` and `TARGET_TRANSPORT: pi` is
supplied, return `STOP` and ask the parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the routing decision
- allowed scope: the decision's `ALLOWED_SCOPE` / request `ALLOWED_FILES`
- the router Dispatch prompt

## Preflight

```bash
command -v pi
git status --short
```

Missing `pi` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

Headless only. The shared runner starts one native RPC process per
delegation:
`pi --mode rpc --model "$MODEL" --no-session --no-context-files --no-skills`.
It sends JSONL `prompt` / `follow_up` over stdin and consumes
Pi's native events until `agent_settled`. Closing stdin ends the process.
Pass the exact registry model ID — no aliases.

```bash
scripts/run-delegate --tool pi --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Exit `124` is an explicit timeout report, not a completed empty diff. Missing
tool, malformed/unknown events, missing terminal events, and invalid reports
also return explicit failed reports. Return to parent acceptance after a write.
