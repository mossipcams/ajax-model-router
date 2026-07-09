---
name: model-router
description: Pick the workflow for one bounded coding task: local, packet, delegate lane, review gate, revise, discard, or stop.
---

# Model Router

Use this skill for one bounded code behavior change. Do not use it for pure
Q&A, broad planning, or unrelated cleanup.

## Invariants

- Current directory is already the task worktree.
- Never create worktrees, branches, commits, pushes, merges, rebases, or branch
  switches.
- Do not delegate from a vague prompt.
- Implementation delegates require a complete `tdd-implementation-packet`.
- The packet is the source of truth.
- Parent reviews every delegate diff before accepting it.
- Empty diff plus success claim is failure.
- Stop after two failed delegate rounds.

## Route

Follow the first matching rule.

| Condition | Action |
|---|---|
| Request is not a code behavior change | Answer directly. If it is a review request, use `codex-delegate` review. |
| Candidate edit is one file, <=10 changed lines, and adds no conditional, loop, parser, auth, security, or data-loss path | Implement locally. |
| Request contains multiple independent behaviors | Route only the first requested behavior. Stop if it cannot be expressed as one packet. |
| No complete packet exists | Use `tdd-implementation-packet`. |
| Packet is missing allowed files, forbidden changes, goal, code anchors, test instructions, verification, acceptance criteria, or stop conditions | Use `codex-delegate` packet critique. |
| Packet is complete | Pick one implementation lane below. |

## Implementation Lane

Evaluate in order. First match wins.

| Packet facts | Lane |
|---|---|
| User explicitly asked Codex to implement | `codex-delegate` implementation, `gpt-5.5` high |
| User explicitly asked Codex to delegate | `codex-delegate` delegator mode, `gpt-5.5` high |
| Allowed files are docs-only, tests-only, generated-code cleanup, repeated exact replacements, or boilerplate with named anchors | `opencode-delegate`, `opencode-go/minimax-m3` |
| Allowed files include frontend/Svelte/TypeScript/PWA files | `cursor-delegate`, Composer 2.5 |
| Allowed files include Rust/backend/server/auth/session/PTY/supervisor code | `opencode-delegate`, `opencode-go/glm-5.2` |
| Packet names a bug but not the source file to edit | `opencode-delegate`, `opencode-go/glm-5.2` |
| No lane matched | `cursor-delegate`, Composer 2.5 |

Model ID rules:

- Use `opencode-go/minimax-m3`, not provider-specific aliases.
- Use `opencode-go/glm-5.2`, not provider-specific aliases.
- Do not use Haiku.

If the selected implementation tool is unavailable, implement locally under the
packet constraints and still run the review gate.

## Review Gate

After a delegate finishes, require:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Run the packet verification commands.

Accept only when all are true:

- changed files are inside Allowed files,
- test-first behavior happened or the packet says it does not apply,
- verification passed,
- production edits match packet anchors,
- forbidden behavior did not change,
- no broad formatting or refactor sweep happened.

Revise once for incomplete work inside Allowed files. Discard forbidden or
out-of-scope work. After two failed rounds, stop and report both attempts.
