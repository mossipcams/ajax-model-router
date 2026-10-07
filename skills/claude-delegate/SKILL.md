---
name: claude-delegate
description: Run Claude only from a model-router EXECUTION decision.
---

# Claude Delegate

Thin adapter for router-selected Claude work. Do not reconstruct routing from
the user request. If no `EXECUTION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the execution decision
- allowed scope: the decision's `SCOPE`
- the prepared prompt file and persistent run directory

## Preflight

```bash
command -v acpx
git status --short
```

Missing `acpx` means return `STOP`; never substitute local work or another
tool inside this adapter. Do not spawn native Task or other Claude subagents;
implement in-process.

## Invocation

Claude runs through acpx ACP (`claude` profile), driven by the shared runner.
Every dispatch is stateless and uses one-shot `exec` only — no saved sessions.
The parent assembles a full prompt for initial work and for every revision.

```bash
scripts/run-delegate --tool claude --model "$MODEL" \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Authentication uses the existing Claude login; never force an API key.
Timeout, missing tool, missing report, or invalid report returns an explicit
failed `DELEGATE_REPORT`. Return to parent acceptance after a write.
