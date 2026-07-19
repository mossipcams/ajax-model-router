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

Headless only. The shared runner uses the installed `pi --help` interface:
`pi -p --model "$MODEL" --no-session --no-context-files --no-skills <prompt>`
with stdin closed. Never use interactive or server paths. Context files and
skills stay off — the READY packet is the worker contract. It preserves the
full raw log and prints only the complete structured report.

```bash
scripts/run-delegate --tool pi --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Exit `124` is an explicit timeout report, not a completed empty diff. Missing
tool, missing output, and invalid output also return explicit failed reports.

Mode-specific line appended to the router prompt:

- `test-only`: `Do not edit production code.`
- `implement`: `Before editing, state the likely failure mode and smallest
  implementation path.`

After a write mode, return to the router's Review Gate.
