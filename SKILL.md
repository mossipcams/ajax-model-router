---
name: model-router
description: Pick the workflow for one bounded coding task: local, packet, delegate lane, review gate, revise, discard, or stop.
---

# Model Router

Route one bounded code behavior change: implement it locally or delegate it,
then gate the result. Not for pure Q&A, broad planning, or unrelated cleanup.

This skill owns every shared rule of the pipeline. The delegate skills
(`codex-delegate`, `cursor-delegate`, `opencode-delegate`) are thin adapters:
preflight plus the exact commands for one tool. If a delegate skill conflicts
with this file, this file wins.

## Pipeline

1. **Route** — pick local work or a delegate lane (first matching rule).
2. **Packet** — `tdd-implementation-packet` is the contract and the single
   source of truth for the delegate.
3. **Dispatch** — send the Delegate Prompt below through the chosen delegate
   skill.
4. **Gate** — review the diff, then accept, revise once, discard, or stop.

## Invariants

- Current directory is already the task worktree.
- Never create worktrees, branches, commits, pushes, merges, rebases, or
  branch switches. No delegate may either.
- Do not delegate from a vague prompt. Implementation delegates require a
  complete packet.
- Parent reviews every delegate diff before accepting it.
- Empty diff plus a success claim is failure.
- Stop after two failed delegate rounds.

## Route

Follow the first matching rule.

| Condition | Action |
|---|---|
| Request is not a code behavior change | Answer directly. If it is a review request, use `codex-delegate` `diff-review` or `final-review`. |
| Candidate edit is one file, <=10 changed lines, and adds no conditional, loop, parser, auth, security, or data-loss path | Implement locally. No packet needed. |
| Request contains multiple independent behaviors | Route only the first requested behavior. Stop if it cannot be expressed as one packet. |
| No complete packet exists | Build one with `tdd-implementation-packet`. |
| Packet is missing allowed files, forbidden changes, goal, code anchors, test instructions, verification, acceptance criteria, or stop conditions | `codex-delegate` `packet-critique`, then fix the packet. |
| Packet is complete | Pick a lane below. |

## Lanes

First match wins.

| Packet facts | Lane |
|---|---|
| User explicitly asked Codex to implement | `codex-delegate` `implementation`, `gpt-5.5` |
| User explicitly asked Codex to delegate | `codex-delegate` `delegator`, `gpt-5.5` |
| Allowed files are docs-only, tests-only, generated-code cleanup, repeated exact replacements, or boilerplate with named anchors | `opencode-delegate`, `opencode-go/minimax-m3` |
| Allowed files include frontend/Svelte/TypeScript/PWA files | `cursor-delegate`, `composer-2.5` |
| Allowed files include Rust/backend/server/auth/session/PTY/supervisor code | `opencode-delegate`, `opencode-go/glm-5.2` |
| Packet names a bug but not the source file to edit | `opencode-delegate`, `opencode-go/glm-5.2` |
| No lane matched | `cursor-delegate`, `composer-2.5` |

Use the exact model IDs above — no provider-specific aliases, no Haiku. If the
selected tool is unavailable, implement locally under the packet constraints
and still run the Review Gate.

## Delegate Prompt

Every implementation dispatch sends exactly this wrapper followed by the full
packet. Delegate skills append only the tool- or mode-specific lines they
name; nothing else is added or removed.

```text
You are a bounded implementation worker for a parent agent.
Current directory is the task worktree.
Never commit, push, merge, rebase, create branches, or change branches.

Implement exactly one behavior change from the packet below.
Edit only Allowed files. Do not touch Forbidden changes. Follow Code anchors.
Add or identify the failing test first when the packet requires it.
Make the smallest production edit needed.
Run Verification commands.
Stop if any Stop condition is hit, or if the patch would exceed roughly 400 changed lines.
No drive-by cleanup, renames, formatting sweeps, or broad refactors.

Return a REPORT with: summary, files changed, test-first result, commands run, stop conditions hit, remaining risks.

<TDD implementation packet>
```

## Review Gate

After any delegate write mode:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Then run the packet verification commands.

Accept only when all are true:

- changed files are inside Allowed files,
- test-first behavior happened or the packet says it does not apply,
- verification passed,
- production edits match packet anchors,
- forbidden behavior did not change,
- no broad formatting or refactor sweep happened.

Otherwise: revise once for incomplete work inside Allowed files; discard
forbidden or out-of-scope work. After two failed rounds, stop and report both
attempts.
