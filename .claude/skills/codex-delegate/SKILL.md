---
name: codex-delegate
description: Run Codex GPT-5.5 for a mode selected by model-router: packet critique, diff review, final review, implementation, or delegator mode.
---

# Codex Delegate

This skill executes a selected Codex mode. It does not choose the mode.

Required inputs:

- mode: `packet-critique`, `diff-review`, `final-review`, `implementation`, or
  `delegator`
- relevant packet, diff, or review prompt

Never create worktrees, branches, commits, pushes, merges, rebases, or branch
switches. Never use `--yolo` or `danger-full-access`.

## Preflight

```bash
command -v codex
git status --short
git diff --stat
```

Missing `codex` means stop and report.

## Invocations

Read-only modes:

```bash
cat > /tmp/codex-task.txt <<'PROMPT'
<delegate prompt>
PROMPT
codex exec --model gpt-5.5 --sandbox read-only --output-last-message /tmp/codex-report.md - \
  < /tmp/codex-task.txt > /tmp/codex-run.log 2>&1
cat /tmp/codex-report.md
```

Final review:

```bash
codex exec --profile xhigh --model gpt-5.5 --sandbox read-only --output-last-message /tmp/codex-report.md - \
  < /tmp/codex-task.txt > /tmp/codex-run.log 2>&1
cat /tmp/codex-report.md
```

Write modes:

```bash
codex exec --model gpt-5.5 --sandbox workspace-write --output-last-message /tmp/codex-report.md - \
  < /tmp/codex-task.txt > /tmp/codex-run.log 2>&1
cat /tmp/codex-report.md
```

Read only the report file, not the full run log.

## Prompt Templates

Packet critique:

```text
Review the TDD implementation packet below before it is sent to an implementation delegate.
Return BLOCK or PASS.
Check only: allowed files, forbidden changes, behavior goal, code anchors, test-first proof, verification commands, stop conditions, and scope size.

<packet>
```

Diff review:

```text
Review this delegate diff against the packet.
Return ACCEPT, REVISE, or DISCARD.
Check only: allowed files, forbidden changes, test-first evidence, verification, code anchors, behavior match, and unrelated edits.

<packet>
<git diff>
```

Implementation:

```text
Implement exactly one behavior change from the packet below.
Edit only Allowed files.
Do not touch Forbidden changes.
Add or identify the failing test first when the packet requires it.
Run Verification commands.
Return a REPORT with: summary, files changed, test-first result, commands run, stop conditions, remaining risks.

<packet>
```

Delegator:

```text
Use the installed model-router skill to choose one sub-delegate lane for the packet below.
Run that sub-delegate from the current worktree.
Review its diff against the packet.
Return ACCEPT, REVISE, or DISCARD plus commands run.

<packet>
```

## Parent Review

After Codex write modes:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Then run the packet verification commands.
