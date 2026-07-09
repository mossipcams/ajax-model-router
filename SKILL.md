---
name: model-router
description: Decide whether to handle a bounded code behavior change locally, create a TDD packet, delegate implementation to Cursor or OpenCode, delegate review to Codex, or stop. Use when choosing between local orchestrator work, Cursor with Grok 4.5 High (not High Fast) or Composer 2.5, OpenCode MiniMax-M3 or GLM 5.2, and Codex GPT-5.5 high for one bounded coding task.
---

# Model Router

## Primary Role

The router decides the workflow. Do not delegate by default.

It does not implement non-trivial changes itself once invoked unless every suitable delegate is unavailable or unsuitable. It may keep trivial one-liners, direct Q&A, exploration, and changes smaller than a useful handoff local.

It integrates with existing skills:

- `tdd-implementation-packet` = canonical packet creator
- `cursor-delegate` = Cursor implementation lane, with Grok 4.5 High for complex tasks and Composer 2.5 for routine bounded tasks
- `opencode-delegate` = MiniMax-M3 or GLM 5.2 implementation lane
- `codex-delegate` = GPT-5.5 high review, packet critique, patch narrowing, or explicit implementation

## Global Rules

- Current directory is already the task worktree.
- Never create worktrees, create branches, change branches, commit, push, merge, or rebase.
- Never delegate implementation from a vague prompt.
- Implementation requires a complete tdd-implementation-packet. The packet is the source of truth; delegates must not invent their own.
- All implementation must be test-first when applicable.
- Parent agent must review the resulting git diff before accepting.
- Empty diff plus success claim is failure.
- Out-of-scope edits trigger Revise or Discard.
- Two failed delegate rounds means stop and report.

## Decision Tree

Use this exact decision tree:

```text
START
1. Is the user asking for a code behavior change?
   - No:
     - If asking for review, go to review decision (step 4 / codex-delegate).
     - If asking for planning, create or critique a packet only if useful.
     - Otherwise answer directly.
   - Yes:
     - Continue.
1a. Is the change trivial or smaller than a useful handoff?
   - Yes:
     - Implement locally.
   - No:
     - Continue.
2. Is there exactly one behavior change?
   - No:
     - Split into one behavior change.
     - Route only the first bounded change.
     - Stop if it cannot be split safely.
   - Yes:
     - Continue.
3. Is a complete tdd-implementation-packet available?
   - No:
     - Use existing tdd-implementation-packet skill.
     - If Graphify, Serena, ast-grep, or desired behavior context is missing
       and cannot be gathered, stop.
   - Yes:
     - Continue.
4. Is the packet ambiguous, risky, or intended for a weaker model?
   - Yes:
     - Use codex-delegate in packet critique mode before implementation.
   - No:
     - Continue.
5. Choose implementation delegate:
   A. Use cursor-delegate with Grok 4.5 High when:
      - complex frontend, Svelte, TypeScript, UI behavior, PWA layout,
        viewport, terminal rendering,
      - multi-file repo-aware edits,
      - tricky UI behavior,
      - normal bug fixes where Cursor is useful but Composer 2.5 is too weak,
      - existing repo patterns matter,
      - and the model id is `grok-4.5-high`, never `grok-4.5-fast-high`.
   B. Use cursor-delegate with Composer 2.5 when:
      - routine bounded frontend, Svelte, TypeScript, UI behavior, or PWA work,
      - straightforward bug fixes,
      - well-anchored repo-aware changes,
      - the packet leaves little judgment to the model.
   C. Use opencode-delegate with MiniMax-M3 when:
      - task is mechanical,
      - low-risk,
      - repetitive,
      - boilerplate,
      - docs cleanup,
      - simple test expansion,
      - obvious localized change,
      - cheap retry is acceptable.
   D. Use opencode-delegate with GLM 5.2 when:
      - task needs deeper code reasoning,
      - tricky backend behavior,
      - Rust architecture reasoning,
      - bug isolation,
      - refactor validation,
      - implementation depends on understanding module boundaries,
      - failure mode must be reasoned through before editing.
   E. Use codex-delegate for implementation only when:
      - the user explicitly asks Codex to implement,
      - or all other implementation delegates are unavailable,
      - and the packet is complete.
      - Default Codex role is review, not implementation.
   F. Use codex-delegate in delegator mode when:
      - the user explicitly asks Codex to delegate / hand off the work,
      - and the packet is complete.
      - Codex then picks the sub-lane and runs cursor-agent or opencode itself;
        this router's parent still runs the final review gate.
6. After implementation:
   - Always review git diff.
   - If patch is clean and verification passes, Accept.
   - If patch is narrow but incomplete, Revise once.
   - If patch is out-of-scope, too large, ignores anchors, skips test-first,
     or changes forbidden behavior, Discard.
   - After two failed rounds, stop and report.
END
```

## Routing Table

| Delegate / model | Role |
|---|---|
| Local orchestrator | Default for trivial, exploratory, or smaller-than-handoff work. |
| Cursor / Grok 4.5 High | Preferred Cursor lane for complex tasks: frontend, Svelte, TypeScript, PWA, terminal behavior, repo-aware Rust edits, normal bounded bug fixes where Composer 2.5 is too weak. Use `grok-4.5-high`, not High Fast. |
| Cursor / Composer 2.5 | Routine bounded Cursor lane; not the default for complex tasks. |
| OpenCode / MiniMax-M3 | Cheap mechanical worker. Best for boring, repetitive, low-risk, boilerplate, docs, simple test additions. |
| OpenCode / GLM 5.2 | Reasoning-heavy implementer. Best for tricky backend behavior, Rust architecture, bug isolation, refactor validation. |
| Codex / GPT-5.5 high | Default reviewer. Best for adversarial review, packet critique, test adequacy, hidden risks, patch narrowing. |
| Codex / GPT-5.5 xhigh | Expensive final reviewer. Use for disputed output, high-risk diff, or user-requested deep review. |

## Review Gate

After any delegate finishes, the router must require:

```bash
git status --short
git diff --stat
git diff -- <allowed files>
```

Then run the verification commands from the packet itself.

Accept only if:

- changed files are inside Allowed files,
- test-first behavior is proven or validly explained,
- verification passes,
- production edits match packet anchors,
- Graphify boundaries are preserved,
- no forbidden behavior changed,
- no broad formatting/refactor sweep happened.

Otherwise Revise (once, with specific findings) or Discard. Two failed rounds: stop, summarize both attempts, report the blocker.
