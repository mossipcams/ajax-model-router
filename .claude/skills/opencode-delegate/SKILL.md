---
name: opencode-delegate
description: Run OpenCode from the current worktree when model-router selected an OpenCode lane.
---

# OpenCode Delegate

This skill executes a selected OpenCode lane. It does not choose the lane.

Required inputs:

- model: `opencode-go/minimax-m3` or `opencode-go/glm-5.2`
- complete `tdd-implementation-packet`

Never create worktrees, branches, commits, pushes, merges, rebases, or branch
switches.

## Preflight

```bash
command -v opencode
git status --short
git diff --stat
```

Missing `opencode` means stop and report.

## Invocation

```bash
cat > /tmp/opencode-task.txt <<'PROMPT'
<delegate prompt>
PROMPT
opencode run --model "$MODEL" "$(cat /tmp/opencode-task.txt)" > /tmp/opencode-run.log 2>&1
tail -80 /tmp/opencode-run.log
```

Model IDs:

- `opencode-go/minimax-m3`
- `opencode-go/glm-5.2`

Do not use provider-specific aliases.

## Delegate Prompt

Use this wrapper:

```text
You are OpenCode, a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches.

Implement exactly one behavior change from the packet below.
Edit only Allowed files.
Do not touch Forbidden changes.
Follow Code anchors.
Add or identify the failing test first when the packet requires it.
Make the smallest production edit needed.
Run Verification commands.
Stop if any Stop condition is hit.
Stop if the patch would exceed roughly 400 changed lines.
No drive-by cleanup, renames, formatting sweeps, broad refactors, or transcripts.

Return a REPORT with: summary, files changed, test-first result, commands run, stop conditions, remaining risks.

<TDD implementation packet>
```

For `opencode-go/glm-5.2`, add: `Before editing, state the likely failure mode
and smallest implementation path.`

## Parent Review

After OpenCode exits:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Then run the packet verification commands.
