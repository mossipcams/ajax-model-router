# Ajax Model Router — Agent Notes

- `ajax-model-router` is the canonical source for the router skill bundle.
- Visible skill name stays `model-router`. Product name stays Ajax Model Router.
- `skills/model-router` holds shared routing and transaction rules.
- Install adapters bind `CALLER_HARNESS` (`cursor`, `codex`, `claude`). Never
  infer caller from task text. `TARGET_TRANSPORT` is always `cursor|codex|pi`.
- A caller need not be a DELEGATE target (Claude → Cursor is valid).
- `.cursor` → cursor adapter; `.codex`/`.agents` → codex; `.claude` → claude.
- Delegate skills are thin transport adapters for `ACTION: DELEGATE` only.
- Pipeline is harness-boundary route → USE_NATIVE | STOP | DELEGATE lifecycle.
- No playbooks, packet critique, or calibration model selection.
- Do not vendor or integrate pstack.
- Use symlinks where possible. If copies are required, keep drift detection.
- Do not add MCP, wrappers, generated subagents, or routing enforcement unless
  explicitly requested.
- Do not rename the skill to `ajax-model-router`.
