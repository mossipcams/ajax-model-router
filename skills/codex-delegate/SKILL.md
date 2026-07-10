---
name: codex-delegate
description: Run Codex GPT-5.5 for a mode selected by model-router: packet critique, diff review, final review, implementation, or delegator mode.
---

# Codex Delegate

Adapter for the Codex lanes. `model-router` picks the mode, supplies the
Delegate Prompt and packet for write modes, and runs the Review Gate. This
skill only invokes the tool.

Required inputs:

- mode: `packet-critique`, `diff-review`, `final-review`, `implementation`,
  or `delegator`
- the relevant packet, diff, or review prompt

Never use `--yolo` or `danger-full-access`.

## Preflight

```bash
command -v codex
git status --short
```

Missing `codex` means stop and report.

## Invocation

Write the prompt to `/tmp/codex-task.txt`, then run the mode's command:

| Mode | Command |
|---|---|
| `packet-critique`, `diff-review` | `codex exec --model gpt-5.5 --sandbox read-only --output-last-message /tmp/codex-report.md -` |
| `final-review` | `codex exec --profile xhigh --model gpt-5.5 --sandbox read-only --output-last-message /tmp/codex-report.md -` |
| `implementation`, `delegator` | `codex exec --model gpt-5.5 --sandbox workspace-write --output-last-message /tmp/codex-report.md -` |

```bash
codex exec <mode flags> - < /tmp/codex-task.txt > /tmp/codex-run.log 2>&1
cat /tmp/codex-report.md
```

Read only the report file, not the full run log.

## Prompts

`implementation` uses the router's Delegate Prompt plus packet, unchanged.

`packet-critique`:

```text
Review the TDD implementation packet below before it is sent to an implementation delegate.
Return BLOCK or PASS.
Check only: allowed files, forbidden changes, behavior goal, code anchors, test-first proof, verification commands, stop conditions, and scope size.

<packet>
```

`diff-review` and `final-review`:

```text
Review this delegate diff against the packet.
Return ACCEPT, REVISE, or DISCARD.
Check only: allowed files, forbidden changes, test-first evidence, verification, code anchors, behavior match, and unrelated edits.

<packet>
<git diff>
```

`delegator`:

```text
Use the installed model-router skill to choose one sub-delegate lane for the packet below.
Run that sub-delegate from the current worktree.
Review its diff against the packet.
Return ACCEPT, REVISE, or DISCARD plus commands run.

<packet>
```

After write modes, return to the router's Review Gate.
