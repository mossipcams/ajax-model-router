# model-router Agent Notes

- `ajax-model-router` is the canonical source for the router skill bundle.
- `skills/model-router` is the thin control plane; sibling directories hold
  thin delegate adapters. `.codex/skills` and `.claude/skills` are symlink
  views only — never put real files there.
- Shared rules (Execution decision, Dispatch, Review, invariants) live only in
  `skills/model-router/SKILL.md`. Delegate skills must not restate them.
- Pipeline is route → execute → verify. No packet build/critique stages.
- Do not manually edit copied orchestrator-specific versions.
- Use symlinks where possible.
- If symlinks are not possible, copied installs must have drift detection.
- Do not add MCP, wrappers, generated subagents, or routing enforcement unless
  explicitly requested.
- Do not rename the skill to `ajax-model-router`.
