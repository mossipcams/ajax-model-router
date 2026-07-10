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
- mode: `discover`, `implement`, or `test-only`
- allowed scope: the decision's `ALLOWED_SCOPE`
- the router prompt and `READY` packet for write modes
- read-only discovery prompt for `discover`

## Preflight

```bash
command -v opencode
git status --short
```

Missing `opencode` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

```bash
cat > /tmp/opencode-task.txt <<'PROMPT'
<router prompt plus packet or discovery scope>
PROMPT
opencode run --model "$MODEL" "$(cat /tmp/opencode-task.txt)" </dev/null > /tmp/opencode-run.log 2>&1
tail -80 /tmp/opencode-run.log
```

Mode-specific line appended to the router prompt:

- `discover`: `Read only. Return exact source files, symbols, and anchors. Do
  not edit files.`
- `test-only`: `Do not edit production code.`
- `implement`: `Before editing, state the likely failure mode and smallest
  implementation path.`

For `discover`, return the read-only findings to the router and reroute. After a
write mode, return to the router's Review Gate.
