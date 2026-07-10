---
name: opencode-delegate
description: Run OpenCode from the current worktree when model-router selected an OpenCode lane.
---

# OpenCode Delegate

Adapter for the OpenCode lanes. `model-router` picks the model, supplies the
Delegate Prompt and packet, and runs the Review Gate. This skill only invokes
the tool.

Required inputs:

- model: `opencode-go/minimax-m3` or `opencode-go/glm-5.2` (exact IDs, no
  provider-specific aliases)
- the router's Delegate Prompt plus complete packet

## Preflight

```bash
command -v opencode
git status --short
```

Missing `opencode` means stop and report.

## Invocation

```bash
cat > /tmp/opencode-task.txt <<'PROMPT'
<Delegate Prompt + packet>
PROMPT
opencode run --model "$MODEL" "$(cat /tmp/opencode-task.txt)" > /tmp/opencode-run.log 2>&1
tail -80 /tmp/opencode-run.log
```

Model-specific line appended to the Delegate Prompt:

- `opencode-go/glm-5.2`: `Before editing, state the likely failure mode and
  smallest implementation path.`

Then return to the router's Review Gate.
