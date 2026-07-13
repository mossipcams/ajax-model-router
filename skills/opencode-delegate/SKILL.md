---
name: opencode-delegate
description: Run OpenCode only from a model-router ROUTING_DECISION.
---

# OpenCode Delegate

Adapter for router-selected OpenCode lanes. Do not reconstruct routing from the
user request. If no `ROUTING_DECISION` is supplied, return `STOP` and ask the
parent to run `model-router`.

Required inputs:

- model: the exact `MODEL` from the router decision
- mode: `discover`, `implement`, or `test-only`
- allowed scope: the decision's `ALLOWED_SCOPE`
- the router prompt and `READY` packet for write modes
- read-only discovery prompt for `discover`

## Preflight

```bash
command -v opencode
git status --short
```

Missing `opencode` means return `STOP`; never substitute local work or another
tool inside this adapter.

## Invocation

Headless only: `opencode run` with stdin closed. Never `opencode`,
`opencode --mini`, `opencode serve`, or `opencode web` — those are
interactive/server paths and the full TUI can hang on terminal probes.

```bash
cat > /tmp/opencode-task.txt <<'PROMPT'
<router prompt plus packet or discovery scope>
PROMPT
MAX_SECONDS=900
TIMEOUT_MARKER="${TMPDIR:-/tmp}/opencode-timeout.$$"
rm -f "$TIMEOUT_MARKER"
# ponytail: ~/.claude skill scan follows symlinks into venv/nested copies and
# pegs CPU; Claude Code skills aren't for OpenCode. Ceiling: misses any skill
# intentionally shared via ~/.claude/skills. Upgrade: fix symlink targets or
# drop OPENCODE_DISABLE_CLAUDE_CODE_SKILLS once upstream stops following them.
export OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1
opencode run --model "$MODEL" "$(cat /tmp/opencode-task.txt)" </dev/null > /tmp/opencode-run.log 2>&1 &
OPENCODE_PID=$!
(
  sleep "$MAX_SECONDS"
  if kill -0 "$OPENCODE_PID" 2>/dev/null; then
    touch "$TIMEOUT_MARKER"
    kill -TERM "$OPENCODE_PID" 2>/dev/null || true
  fi
) &
WATCHDOG_PID=$!
if wait "$OPENCODE_PID"; then STATUS=0; else STATUS=$?; fi
pkill -P "$WATCHDOG_PID" 2>/dev/null || true
kill "$WATCHDOG_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true
tail -80 /tmp/opencode-run.log
if [[ -f "$TIMEOUT_MARKER" ]]; then
  rm -f "$TIMEOUT_MARKER"
  echo "OpenCode timed out after ${MAX_SECONDS}s" >&2
  exit 124
fi
rm -f "$TIMEOUT_MARKER"
exit "$STATUS"
```

Exit `124` is a failed delegation, not a completed empty diff. Return
`DELEGATE_REPORT` with `STATUS: FAILED`, include the timeout in
`STOP_CONDITIONS_HIT`, and reroute.

Mode-specific line appended to the router prompt:

- `discover`: `Read only. Return exact source files, symbols, and anchors. Do
  not edit files.`
- `test-only`: `Do not edit production code.`
- `implement`: `Before editing, state the likely failure mode and smallest
  implementation path.`

For `discover`, return the read-only findings to the router and reroute. After a
write mode, return to the router's Review Gate.
