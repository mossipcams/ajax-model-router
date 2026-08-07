---
name: codex-delegate
description: Run Codex only from a model-router ROUTING_DECISION with ACTION DELEGATE.
---

# Codex Delegate

Thin transport adapter for cross-harness Codex work. Do not reconstruct
routing from the user request. If no `ROUTING_DECISION` with
`ACTION: DELEGATE` and `TARGET_TRANSPORT: codex` is supplied, return `STOP`
and ask the parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the routing decision
- allowed scope: the decision's `ALLOWED_SCOPE` / request `ALLOWED_FILES`
- the router Dispatch prompt

Standalone reviews are not a Codex lane; the parent reviews the actual delta
locally.

Never use `--yolo` or `danger-full-access`.

## Preflight

```bash
command -v codex
git status --short
```

Missing `codex` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

Codex runs through `codex app-server` (native line-delimited JSON-RPC), driven
by the shared runner. One app-server process per delegation. Implementation
uses `workspace-write` sandbox. Pass the exact registry model ID — no aliases.

```bash
scripts/run-delegate --tool codex --model "$MODEL" \
  --sandbox workspace-write \
  --reasoning-effort xhigh \
  --prompt "$AJAX_ROUTER_RUN_DIR/prompt.txt" \
  --raw-log "$AJAX_ROUTER_RUN_DIR/raw.log" \
  --report "$AJAX_ROUTER_RUN_DIR/report.yaml"
```

Reasoning effort stays `xhigh`. Authentication uses the existing Codex/ChatGPT
login (resolved from `~/.codex`); never force an API key. For a follow-up turn
that reuses Codex's retained thread, append `--resume "$THREAD_ID"`. Timeout,
missing tool, missing report, or invalid report returns an explicit failed
`DELEGATE_REPORT`. Return to parent acceptance after a write.
