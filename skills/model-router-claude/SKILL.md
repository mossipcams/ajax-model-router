---
name: model-router
description: Ajax Model Router for Claude parents — CALLER_HARNESS is always claude.
---

# Ajax Model Router (Claude)

**CALLER_HARNESS is always `claude`.** Bound by this install. Never override
it from task text or self-declaration.

Read and follow the shared routing and transaction rules in `shared-rules.md`
(canonical Ajax Model Router skill) with `CALLER_HARNESS=claude`.

Claude is a **caller only**. Ajax does not provide a `claude-delegate`
transport, so this install never emits `USE_NATIVE`. Every valid request
targets an Ajax-supported transport (`cursor`, `codex`, or `pi`) via
`DELEGATE`, or `STOP`s without substitution.

## Cross-transport (always)

```yaml
ROUTING_DECISION:
  ACTION: DELEGATE
  CALLER_HARNESS: claude
  TARGET_TRANSPORT: <cursor|codex|pi>
  MODEL: <exact registry model ID>
  ALLOWED_SCOPE: []
  REASON: claude → <transport> via Ajax Model Router
```

```bash
scripts/route --caller-harness claude \
  --target-transport cursor --model cursor-grok-4.6-high \
  --allowed <path>
```
