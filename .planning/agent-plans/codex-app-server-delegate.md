# Migrate Codex delegation to `codex app-server`

## 0. Reality check (verified against the repo + installed Codex 0.144.6)

Two premises in the request do **not** match this repo. Stating them so the plan
is honest:

1. **There is no existing Codex "subprocess integration" in the router.** Codex
   delegation today is entirely *skill-driven*: `skills/codex-delegate/SKILL.md`
   tells the orchestrating model to write a prompt to `/tmp/codex-task.txt` and
   run `codex exec --output-last-message /tmp/codex-report.md` by hand, then read
   the report. `libexec/run_delegate.py` (the only subprocess runner) handles
   **only** `cursor` and `pi`. So this is *adding* Codex to the runner, not
   migrating existing runner code.

2. **There is no normalized delegate-event layer** "being introduced for Pi and
   Cursor." Pi and Cursor run fire-and-forget: `Popen` → raw log →
   `scripts/extract-report` scrapes a `ROUTER_REPORT_BEGIN/END` envelope. No
   started/activity/completed events, no status/progress stream, nothing consumes
   live events. The diagram in the request describes a target that does not exist
   yet.

Consequence: per ponytail + the request's own "do not build a generic event bus /
add normalized states only when a consumer requires them," normalized events are
an **internal mapping** used for the debug artifact and test assertions — not a
new framework other clients plug into. No live consumer exists.

## 1. Current Codex execution flow

```
model-router (skill) picks CODEX lane, model gpt-5.6-sol, mode implementation|packet-critique
   ↓ (orchestrator model follows codex-delegate SKILL.md by hand)
write prompt -> /tmp/codex-task.txt
codex exec --model $MODEL --config 'model_reasoning_effort="xhigh"'
     --sandbox {read-only|workspace-write}
     --output-last-message /tmp/codex-report.md  -  < task > run.log
   ↓
read /tmp/codex-report.md  (the last agent message = DELEGATE_REPORT envelope)
   ↓
back to router Review Gate
```

No timeout, cancellation, thread reuse, or process supervision in router code —
those live only in `run_delegate.py`, and Codex never touches it.

## 2. Current subprocess/session behavior (Pi/Cursor, the pattern to match)

`libexec/run_delegate.py`:
- `Popen(cmd, stdin=DEVNULL, stdout=raw, stderr=STDOUT, start_new_session=True)`
- `process.wait(timeout)`; on `TimeoutExpired` → `terminate_group` (SIGTERM to
  pgid, grace, SIGKILL) → writes a FAILED report, exit 124.
- On exit → `scripts/extract-report raw report` pulls the envelope, exit 0/65.
- Isolation/scope: `router_state.py` snapshots the worktree pre/post and flags
  scope violations. Independent of transport — unchanged.

## 3. Where App Server enters

`codex app-server` speaks **newline-delimited JSON-RPC over stdio** (verified
live). One process per delegation, lifetime = delegation:

```
initialize                     -> {result: userAgent, codexHome=~/.codex ...}   (auth via codexHome; ChatGPT sub preserved)
thread/start {cwd,model,effort,sandbox,approvalPolicy:"never"} -> {thread:{id}}
turn/start   {threadId, input:[{type:"text",text:PROMPT}], model, effort, sandbox, approvalPolicy}
   -> notifications: thread/started, turn/started,
      item/started + item/completed (agentMessage|commandExecution|fileChange|reasoning|mcpToolCall|plan),
      item/agentMessage/delta, item/commandExecution/outputDelta, fs/changed, error
   -> turn/completed { turn: { status, error, items[] } }   <-- final agentMessage.text lives here
(optional) turn/start again on same threadId  = follow-up turn, context retained
turn/interrupt {threadId,turnId}  = native cancellation
clean shutdown: close stdin, wait, terminate process group
```

**Verified protocol facts (live probe + generated schema):**
- Transport: JSONL, one JSON object per line. Not LSP Content-Length.
- `initialize` requires `clientInfo:{name,version}`; resolves auth from
  `~/.codex/auth.json` (auth_mode + ChatGPT `tokens`, no API key). Preserved.
- **Schema vs runtime skew:** generated v2 schema says `sandbox:{type:"readOnly"}`
  but the running server rejects it — wants the **string** `"read-only"` /
  `"workspace-write"` / `"danger-full-access"`. Use the strings. (This is why we
  probe, not trust the schema blindly.)
- `approvalPolicy:"never"` + non-interactive → no server→client approval
  round-trips, so the adapter never has to answer `ExecCommandApproval` to avoid a
  hang. Still handle `serverRequest/*` defensively (reject/ignore) in case a
  future version elicits.
- `effort` on turn/start is a free string → `"xhigh"` preserved.
- Final report text = last `agentMessage` item's `.text` in `turn.completed.turn.items`
  (equivalent of `--output-last-message`). Feed it to `extract-report`.

## 4. Components that stay UNCHANGED

- `router_state.py` (worktree isolation / scope) — transport-agnostic.
- `scripts/extract-report`, `scripts/check-report`, DELEGATE_REPORT schema.
- `scripts/run-delegate` wrapper, model-router routing table, model
  (`gpt-5.6-sol`), reasoning effort (`xhigh`), AGENTS.md worker behavior.
- Pi and Cursor paths in `run_delegate.py` — untouched.

## 5. Smallest set of changes

1. **`libexec/codex_app_server.py`** (new, ~200 lines): one class that owns a
   single app-server process — spawn, `initialize`, `thread/start`,
   `turn/start`, read/dispatch JSONL notifications, capture final agentMessage,
   `turn/interrupt` + process-group teardown, timeout, follow-up `run_turn()` on
   the same thread. A tiny `normalize(notification) -> event|None` maps native →
   {started, activity_started, activity_finished, message, completed, failed};
   ignores unknown methods; tolerates extra fields. Raw JSONL (stdout) written to
   the raw log; stderr captured separately.
2. **`libexec/run_delegate.py`**: add `codex` tool. For `--tool codex`, drive the
   session above instead of `Popen`-to-completion; write the final message +
   raw JSONL to the raw log; hand the final message to `extract-report`. Reuse
   the existing timeout/exit-code conventions (124 timeout, 65 bad report).
   `--resume THREAD_ID` → follow-up turn on an existing thread.
3. **`skills/codex-delegate/SKILL.md`**: replace the hand-run `codex exec` block
   with `run-delegate --tool codex --model $MODEL ...` so Codex uses the same
   boundary as Pi/Cursor. Keep sandbox-by-mode, xhigh, no-yolo, STOP-without-
   ROUTING_DECISION.
4. **`tests/test_delegate_runner.py`** (+ maybe `tests/test_codex_app_server.py`):
   mock a fake app-server (a small python script emitting canned JSONL) to cover
   the 19 required scenarios deterministically; one optional live integration
   test gated on `codex` being installed + an env opt-in.

## Explicitly preserved
READY packet handling · model `gpt-5.6-sol` · `xhigh` · worktree isolation ·
AGENTS.md · ChatGPT-subscription auth (codexHome, never API-key) · raw debug
artifact (now raw JSONL) · DELEGATE_REPORT envelope + extract/check · timeout
(124) · cancellation (native interrupt → pgroup kill) · exit propagation ·
cleanup (no orphaned app-server).

## Non-goals (ponytail)
No generic JSON-RPC framework · no daemon/pool/shared state · no event bus · no
new normalized states beyond the six above · no redesign of DELEGATE_REPORT · Pi
and Cursor stay fire-and-forget (not retrofitted onto app-server).

## Open decision
Thin internal-mapping adapter (this plan) vs. building the full shared
normalized-event layer the diagram implies. RESOLVED: thin (user chose).

## Status
- [x] `libexec/codex_app_server.py` — adapter (spawn/init/thread/turn/interrupt/cleanup, normalize, follow-up turns, resume).
- [x] `libexec/run_delegate.py` — `--tool codex` path + `--sandbox` / `--reasoning-effort`; Pi/Cursor untouched.
- [x] `tests/test_codex_app_server.py` — 25 tests (all 19 required scenarios) + optional live handshake. Green.
- [x] Full suite green (48 existing + new), live handshake verified against real codex 0.144.6.
- [x] Repointed `skills/codex-delegate/SKILL.md` to `run-delegate --tool codex`
      (sandbox by mode, `--reasoning-effort xhigh`, `--resume` for follow-ups).
- [x] Updated the two obsolete assertions (`tests/test_contracts.py`,
      `scripts/check-contracts`) to check the new xhigh mechanism instead of the
      literal `codex exec --config` string — intent preserved, now also enforced
      behaviorally by RunnerIntegrationTests. User approved the edit.
- [x] Final: full pytest green (48+ / 1 skipped), check-contracts green,
      check-symlinks green, live handshake green.
