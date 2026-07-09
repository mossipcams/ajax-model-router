---
name: cursor-delegate
description: Run Cursor CLI from the current worktree when model-router selected the Cursor lane or the user explicitly named Cursor.
---

# Cursor Delegate

This skill executes a selected Cursor lane. It does not choose the lane.

Required inputs:

- mode: `implement`, `small-fix`, `test-only`, `resume`, or `review`
- model: `grok-4.5-high` or `composer-2.5`
- complete `tdd-implementation-packet` for write modes
- optional `CHAT_ID` for resume

Never create worktrees, branches, commits, pushes, merges, rebases, or branch
switches.

## Preflight

```bash
command -v cursor-agent
git status --short
git diff --stat
```

Missing `cursor-agent` means stop and report.

## Commands

| Mode | Command |
|---|---|
| write modes | `cursor-agent -p -f --trust --model <model> --resume "$CHAT_ID"` |
| review | `cursor-agent -p --plan --trust --resume "$CHAT_ID"` |

Use `grok-4.5-high`, never `grok-4.5-fast-high`.

Redirect output and read only the final report:

```bash
cursor-agent -p -f --trust --model "$MODEL" --resume "$CHAT_ID" > /tmp/cursor-run.log 2>&1 <<'EOF'
<delegate prompt>
EOF
tail -80 /tmp/cursor-run.log
```

## Delegate Prompt

Use this wrapper for write modes:

```text
You are Cursor CLI, a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches.

Implement exactly one behavior change from the packet below.
Edit only Allowed files.
Do not touch Forbidden changes.
Add or identify the failing test first when the packet requires it.
Make the smallest production edit needed.
Run Verification commands.
Stop if any Stop condition is hit.
Return a REPORT with: summary, files changed, test-first result, commands run, stop conditions, remaining risks.

<TDD implementation packet>
```

For `test-only`, add: `Do not edit production code.`

For `review`, use a read-only prompt and require findings with file:line
references.

## Parent Review

After Cursor exits:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Then run the packet verification commands.
