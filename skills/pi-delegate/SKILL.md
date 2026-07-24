---
name: pi-delegate
description: Run Pi only from a model-router ROUTING_DECISION.
---

# Pi Delegate

Adapter for router-selected Pi lanes. Do not reconstruct routing from the
user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the router decision
- mode: `implement` or `test-only`
- allowed scope: the decision's `ALLOWED_SCOPE`
- the router prompt and `READY` packet for write modes

## Preflight

```bash
command -v pi
git status --short
```

Missing `pi` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

Headless only. The shared runner starts one native RPC process per delegation:
`pi --mode rpc --model "$MODEL" --no-session --no-context-files --no-skills`.
It sends JSONL `prompt` and `follow_up` commands over stdin and consumes Pi's
native events until `agent_settled`. The process stays alive for the delegation
so follow-ups reuse the same in-memory context; closing stdin ends it. Context
files and skills stay off — the READY packet is the worker contract. The full
JSONL/stderr stream is preserved in the raw log.

```bash
scripts/run-delegate --tool pi --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Exit `124` is an explicit timeout report, not a completed empty diff. Missing
tool, malformed/unknown events, missing terminal events, and invalid reports
also return explicit failed reports. Native events drive status; process exit
remains the final safety signal.

Mode-specific line appended to the router prompt:

- `test-only`: `Do not edit production code.`
- `implement`: `Before editing, state the likely failure mode and smallest
  implementation path.`

After a write mode, return to the router's Review Gate.
