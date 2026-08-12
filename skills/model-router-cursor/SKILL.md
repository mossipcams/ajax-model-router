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
  MODEL: composer-2.5
  ALLOWED_SCOPE: []
  REASON: caller matches transport (cursor); native Task → composer-2.5, bypass Ajax Model Router
```

Do not snapshot, launch `cursor-agent` through this router, or create
transaction artifacts.

**`USE_NATIVE` means native Task with `model: composer-2.5`, not parent-local
implementation.** The Cursor parent (often Grok High) orchestrates and reviews;
it does not Write/StrReplace the bounded change itself. Default `MODEL` is
`composer-2.5` even when the request omitted it. Pstack playbooks stay on this
same native path and already map code roles to Composer via `pstack-models.mdc`.

Parent-local edits are only for trivial one-liners, non-code work, or after
Composer failed the same scoped task three times.

## Cross-transport

When `TARGET_TRANSPORT` is `codex` or `pi`, follow shared rules: validate the
exact model ID against the registry, confirm transport availability, then
`DELEGATE` via the matching delegate skill — or `STOP` without substitution.

```bash
scripts/route --caller-harness cursor \
  --target-transport <codex|pi> --model <exact-id> \
  --allowed <path>
```
