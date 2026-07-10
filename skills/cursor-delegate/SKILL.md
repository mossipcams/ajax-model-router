---
name: cursor-delegate
description: Run Cursor CLI from the current worktree when model-router selected the Cursor lane or the user explicitly named Cursor.
---

# Cursor Delegate

Adapter for the Cursor lane. `model-router` picks the mode, supplies the
Delegate Prompt and packet, and runs the Review Gate. This skill only invokes
the tool.

Required inputs:

- mode: `implement`, `small-fix`, `test-only`, `resume`, or `review`
- model: `composer-2.5`
- the router's Delegate Prompt plus complete packet for write modes
- `CHAT_ID` for resume

## Preflight

```bash
command -v cursor-agent
git status --short
```

Missing `cursor-agent` means stop and report.

## Invocation

| Mode | Command |
|---|---|
| write modes | `cursor-agent -p -f --trust --model composer-2.5` |
| review | `cursor-agent -p --plan --trust` |

Add `--resume "$CHAT_ID"` only when resuming a prior run.

```bash
cursor-agent -p -f --trust --model composer-2.5 > /tmp/cursor-run.log 2>&1 <<'EOF'
<Delegate Prompt + packet>
EOF
tail -80 /tmp/cursor-run.log
```

Mode-specific lines appended to the Delegate Prompt:

- `test-only`: `Do not edit production code.`
- `review`: use a read-only prompt and require findings with file:line
  references.

Then return to the router's Review Gate.
