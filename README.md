# ajax-model-router

Canonical shared skill bundle for **Ajax Model Router** — harness-boundary
mediation for cross-harness model delegation.

Separate the **caller harness** from the **target transport**. A harness can
invoke Ajax without being a supported DELEGATE target (e.g. Claude → Cursor).
When a caller that is itself a supported transport targets that same transport,
return `USE_NATIVE` and bypass Ajax. Otherwise validate the exact model ID and
transport, then run the deterministic DELEGATE lifecycle.

Pstack remains independent and Cursor-native; this repo does not vendor or
integrate it.

## Layout

- `skills/model-router/` — shared rules: registry, request/decision contracts,
  dispatch prompt, lifecycle, parent review.
- `skills/model-router-cursor/` — `CALLER_HARNESS=cursor`
- `skills/model-router-codex/` — `CALLER_HARNESS=codex`
- `skills/model-router-claude/` — `CALLER_HARNESS=claude` (caller only; never
  `USE_NATIVE`)
- `skills/cursor-delegate`, `pi-delegate`, `codex-delegate` — thin **transport**
  adapters for `ACTION: DELEGATE` only.
- `.cursor` / `.codex` / `.claude` / `.agents` — symlink views.

## Install

```bash
scripts/install-symlinks --target ../ajax-cli
scripts/check-symlinks --target ../ajax-cli
scripts/check-contracts
```

| Dest | Source |
|---|---|
| `.cursor/skills/model-router` | `skills/model-router-cursor` |
| `.codex/skills/model-router` | `skills/model-router-codex` |
| `.agents/skills/model-router` | `skills/model-router-codex` |
| `.claude/skills/model-router` | `skills/model-router-claude` |

## Routing

```text
MODEL_ROUTING_REQUEST → ROUTING_DECISION
  USE_NATIVE | DELEGATE | STOP
```

| Scenario | Action |
|---|---|
| Cursor → Cursor | `USE_NATIVE` |
| Codex → Codex | `USE_NATIVE` |
| Pi → Pi | `USE_NATIVE` |
| Claude → Cursor / Codex / Pi | `DELEGATE` |
| Cursor → Codex / Pi | `DELEGATE` |
| Codex → Cursor / Pi | `DELEGATE` |
| Wrong model for transport | `STOP` |
| Target transport missing | `STOP` |

```bash
scripts/route --caller-harness claude \
  --target-transport cursor --model composer-2.5 --allowed src/foo.py
```

## Safety controls (DELEGATE)

Pre/post snapshot, delta, write-scope, verification, parent review of the
actual delta, and safe restore on discard. `USE_NATIVE` / `STOP` write a
routing decision only.
