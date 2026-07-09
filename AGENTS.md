# model-router Agent Notes

- `ajax-model-router` is the canonical source for the router skill bundle.
- The repo root is the canonical `model-router` skill; `.codex/skills` and
  `.claude/skills` hold the Codex / Claude Code bundle.
- Do not manually edit copied orchestrator-specific versions.
- Use symlinks where possible.
- If symlinks are not possible, copied installs must have drift detection.
- Do not add MCP, wrappers, generated subagents, or routing enforcement unless explicitly requested.
- Do not rename the skill to `ajax-model-router`.
