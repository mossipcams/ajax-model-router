# Harden Cursor ACP filter lifecycle and runner classification

## Approval

Immediate implementation requested. Parent investigation complete; implementation is delegated.

## Scope

Harden `libexec/cursor_acp_filter.py` stdio lifecycle and `libexec/run_delegate.py` closed-stream diagnostics. Preserve stateless `acpx <profile> exec`, route → execute → verify, and existing `DELEGATE_REPORT` / `subagent_status` contracts.

### In scope

- `libexec/cursor_acp_filter.py`
- `libexec/run_delegate.py`
- `libexec/acpx_events.py` (only if needed to classify connection-closed ACP errors)
- `tests/test_cursor_acp_filter.py`
- `tests/test_delegate_runner.py`
- `tests/test_acpx_events.py` (only with `acpx_events.py`)
- `README.md` (delegate-transport diagnostics; keep `acpx <profile> exec`)

### Non-goals

- Persistent ACPx sessions, reconnect, MCP, native Cursor Task, harness-native fallback
- Automatic retry
- Unrelated routing, semantic analysis, or lifecycle-transaction refactors
- Assuming ACPx is the root cause

## Investigation (2026-09-02)

Installed versions:

- ACPx `0.13.2` (`npm -g`)
- cursor-agent `2026.08.11-e8db854`
- `--json-strict` cannot be combined with `--verbose`

Same cwd `/Users/matt/Desktop/Projects/ajax-model-router`, model `composer-2.5`, `--approve-all`, `--non-interactive-permissions fail`, timeout 90s, prompt “reply pong”:

| Path | Result |
|---|---|
| Direct `acpx cursor exec --verbose --format json` | exit 0, 37s, `stopReason=end_turn`, text `pong`. Spawned `cursor-agent acp` as acpx child. |
| Direct `acpx cursor exec` with runner flags (`--json-strict`, no verbose) | exit 0, 7.4s, `end_turn`. |
| `scripts/run-delegate` (injects filter) | ACP completed: filter was acpx child, `end_turn` + `pong` in `raw.log`. Runner exit 1 `MISSING_STRUCTURED_REPORT` because the probe had no `DELEGATE_REPORT`. |

This session did **not** reproduce live `ACP connection closed` / unexpected EOF. Direct and filtered ACP both finished. Residual defects in current code still explain intermittent EOF:

- `iter_fd_lines` turns every `OSError` into clean EOF
- `write_fd` discards write failures
- After `agent.wait()`, daemon pumps join with a 1s cutoff, then the filter process exits
- No SIGINT/SIGTERM forward; child can outlive the filter
- Unknown request-style `cursor/*` methods are forwarded to acpx
- Runner labels most stream failures `ACP_EVENT_FAILED` and does not record acpx PID or filter diagnostics

GitNexus is not indexed for `ajax-model-router` (only `ajax-cli`). Impact analysis was not available.

## Implementation tasks

- [x] Add failing tests against current code for: final ACP response before exit; output slower/larger than the 1s join; clean EOF; read EIO; write EPIPE; nonzero child exit; unknown request-style `cursor/*`; notification-style `cursor/*` without id; SIGTERM with no orphan; runner classification of clean exit without terminal event; stderr diagnostics vs stdout NDJSON; unchanged supported Cursor extension replies
- [x] Replace silent pipe handling with explicit lifecycle, `[cursor-acp-filter]` stderr diagnostics, drain-after-exit with a bounded shutdown that cannot truncate the last ACP line or hang forever, signal forwarding, unknown `cursor/*` JSON-RPC method-not-supported replies
- [x] Record acpx PID and filter/agent stderr; distinguish agent/filter nonzero exit, clean exit without terminal event, connection closed during init vs active turn, timeout, cancellation. No retry. Keep process-group termination.
- [x] Update README transport notes if classification/diagnostics change
- [x] Run focused filter + delegate-runner tests, then full `scripts/check-contracts`
- [x] REVISE: classify JSON-RPC stdout connection-closed errors; terminate child on forward failure; SIGTERM fake imports time. Delegate report schema failed (`RESULT: fail` in a COMPLETE report); parent verified the tree independently.

## Validation

```bash
python3 -m unittest tests.test_cursor_acp_filter tests.test_delegate_runner
python3 -m unittest tests.test_acpx_events   # if acpx_events.py changed
bash scripts/check-contracts
```

## Validation results

- Parent live probe (2026-09-02): direct `acpx cursor exec` succeeded; filtered `run-delegate` completed ACP (`pong` + `end_turn`) then `MISSING_STRUCTURED_REPORT` (probe had no report envelope). No live EOF this session.
- Focused tests (parent): `python3 -m unittest tests.test_cursor_acp_filter tests.test_delegate_runner tests.test_acpx_events` — 49 passed.
- Full unittest via `scripts/check-contracts`: 162 tests OK (1 skipped).
- `scripts/check-contracts` overall **fails** on a pre-existing forbid: `skills/cursor-delegate/SKILL.md` already contains `` `cursor-agent` `` (commit `efd98fb`). Not introduced by this change; adapter was out of scope.

## Deviations

- Live connection-closed/unexpected EOF was not reproduced; covered with a fake ACP child.
- First execute COMPLETE; second execute wrote the JSON-classification + terminate-on-failure fixes but emitted an invalid COMPLETE report (`RESULT: fail`). Parent accepted the tree after independent review, not the report.
- `acpx --json-strict` may still omit filter stderr from the runner; diagnostics remain on the filter’s own stderr.
