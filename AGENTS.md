# model-router Agent Notes

- `ajax-model-router` is the canonical source for the router skill bundle.
- The repo root is the canonical `model-router` skill; `skills/` holds the
  canonical sub-skills. `.codex/skills` and `.claude/skills` are symlink
  views only — never put real files there.
- Shared rules (Delegate Prompt, Review Gate, invariants) live only in the
  root `SKILL.md`. Delegate skills are thin tool adapters and must not
  restate them.
- Do not manually edit copied orchestrator-specific versions.
- Use symlinks where possible.
- If symlinks are not possible, copied installs must have drift detection.
- Do not add MCP, wrappers, generated subagents, or routing enforcement unless explicitly requested.
- Do not rename the skill to `ajax-model-router`.
