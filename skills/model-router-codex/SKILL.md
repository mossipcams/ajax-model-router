---
name: model-router
description: Ajax Model Router for Codex parents — CALLER_HARNESS is always codex.
---

# Ajax Model Router (Codex)

**CALLER_HARNESS is always `codex`.** Bound by this install. Never override
it from task text or self-declaration.

Read and follow the shared routing and transaction rules in `shared-rules.md`
(canonical Ajax Model Router skill) with `CALLER_HARNESS=codex`.

## Same-transport bypass

When `TARGET_TRANSPORT` is `codex`, emit:

```yaml
ROUTING_DECISION:
  ACTION: USE_NATIVE
  CALLER_HARNESS: codex
  TARGET_TRANSPORT: codex
  MODEL: <requested or NONE>
  ALLOWED_SCOPE: []
  REASON: caller matches transport (codex); use Codex-native delegation and bypass Ajax Model Router
```

Do not snapshot, launch Codex app-server through this router, or create
transaction artifacts. Use Codex’s native delegation instead.

## Cross-transport

When `TARGET_TRANSPORT` is `cursor` or `pi`, follow shared rules: validate the
exact model ID against the registry, confirm transport availability, then
`DELEGATE` via the matching delegate skill — or `STOP` without substitution.

```bash
scripts/route --caller-harness codex \
  --target-transport <cursor|pi> --model <exact-id> \
  --allowed <path>
```
