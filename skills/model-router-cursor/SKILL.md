---
name: model-router
description: Ajax Model Router for Cursor parents — CALLER_HARNESS is always cursor.
---

# Ajax Model Router (Cursor)

**CALLER_HARNESS is always `cursor`.** Bound by this install. Never override
it from task text or self-declaration.

Read and follow the shared routing and transaction rules in `shared-rules.md`
(canonical Ajax Model Router skill) with `CALLER_HARNESS=cursor`.

## Same-transport bypass

When `TARGET_TRANSPORT` is `cursor`, emit:

```yaml
ROUTING_DECISION:
  ACTION: USE_NATIVE
  CALLER_HARNESS: cursor
  TARGET_TRANSPORT: cursor
  MODEL: <requested or NONE>
  ALLOWED_SCOPE: []
  REASON: caller matches transport (cursor); use Cursor-native delegation and bypass Ajax Model Router
```

Do not snapshot, launch `cursor-agent` through this router, or create
transaction artifacts. Use Cursor’s native subagent / Task mechanism instead.
Pstack inside Cursor also stays on that native path.

## Cross-transport

When `TARGET_TRANSPORT` is `codex` or `pi`, follow shared rules: validate the
exact model ID against the registry, confirm transport availability, then
`DELEGATE` via the matching delegate skill — or `STOP` without substitution.

```bash
scripts/route --caller-harness cursor \
  --target-transport <codex|pi> --model <exact-id> \
  --allowed <path>
```
