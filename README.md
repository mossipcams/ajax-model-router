# ajax-model-router

Canonical shared router skill bundle.

Included skills:

- `model-router`
- `tdd-implementation-packet`
- `cursor-delegate`
- `opencode-delegate`
- `codex-delegate`

The repo root is still the canonical `model-router` skill. `.codex/skills` and
`.claude/skills` contain the full Codex / Claude Code bundle.

```bash
# From this repo
scripts/install-symlinks --target ../ajax-cli

# Verify
scripts/check-symlinks --target ../ajax-cli
```

Use `--force` only when replacing an existing non-canonical install:

```bash
scripts/install-symlinks --target ../ajax-cli --force
```
