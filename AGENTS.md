# model-router Agent Notes

- `model-router` is the canonical source of truth.
- Do not manually edit copied orchestrator-specific versions.
- Use symlinks where possible.
- If symlinks are not possible, copied installs must have drift detection.
- Do not add MCP, wrappers, generated subagents, or routing enforcement unless explicitly requested.
- Do not rename the skill to `ajax-model-router`.
