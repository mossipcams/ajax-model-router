---
name: codex-delegate
description: Run Codex only from a model-router EXECUTION decision.
---

# Codex Delegate

Thin adapter for router-selected Codex work. Do not reconstruct routing from
the user request. If no `EXECUTION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the execution decision
- allowed scope: the decision's `SCOPE`
- the router Dispatch prompt

Standalone reviews are not a Codex lane; the parent reviews locally with
risk-proportional depth.

Never use `--yolo` or `danger-full-access`.

## Preflight

```bash
command -v acpx
git status --short
```

Missing `acpx` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

Codex runs through acpx ACP (`codex` profile), driven by the shared runner.
Every dispatch is stateless and uses one-shot `exec` only — no saved sessions.
The parent assembles a full prompt for initial work and for every revision.
Implementation delegations pass `--sandbox workspace-write` to the runner for
contract continuity; sandbox and reasoning effort are not yet forwarded over ACP.

```bash
scripts/run-delegate --tool codex --model "$MODEL" \
  --sandbox workspace-write \
  --reasoning-effort xhigh \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Reasoning effort stays `xhigh` in the router contract. Authentication uses
the existing Codex/ChatGPT login via the acpx codex adapter; never force an
API key. Timeout, missing tool, missing report, or invalid report returns an
explicit failed `DELEGATE_REPORT`. Return to parent acceptance after a write.
