---
name: opencode-delegate
description: Run OpenCode only from a model-router ROUTING_DECISION.
---

# OpenCode Delegate

Adapter for router-selected OpenCode lanes. Do not reconstruct routing from the
user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the router decision
- mode: `implement` or `test-only`
- allowed scope: the decision's `ALLOWED_SCOPE`
- the router prompt and `READY` packet for write modes

## Preflight

```bash
command -v opencode
git status --short
```

Missing `opencode` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

Headless only. The shared runner uses the installed `opencode run --help`
interface: `opencode run --model "$MODEL" <prompt>` with stdin closed. Never
use interactive or server paths. It preserves the full raw log and prints only
the complete structured report.

```bash
scripts/run-delegate --tool opencode --model "$MODEL" \
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
