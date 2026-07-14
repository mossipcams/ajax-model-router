# Training Ledger

One entry per rule change made by a training pass. Every entry cites the log
rows that fired the tripwire; the commit is the checkpoint to revert if the
next 10 rows are worse.

Entry format:

```
## YYYY-MM-DD <rule changed>
- Tripwire: <which pre-registered tripwire fired>
- Evidence: <log rows, quoted or by date+lane>
- Change: <smallest edit made>
- Checkpoint: <commit hash>
```

## 2026-07-14 MiniMax implementation lane broadened
- Tripwire: user-directed (dead-row tripwire fired on the MiniMax lane; user chose broaden over delete)
- Evidence: 0 MINIMAX dispatches in all 58 rows since epoch vs 12 cursor + 1 GLM; 2026-07-14 ajax-fluid ran 5 bounded cursor dispatches, all first-try ACCEPT — shallow enough for the cheap lane
- Change: MiniMax row now also matches bounded changes with exact anchors, ≤2 files, ~60 changed lines, no risk-row term
- Checkpoint: bef77c8

## 2026-07-14 Tool-unavailable reroutes instead of STOP
- Tripwire: user-directed
- Evidence: 2026-07-13 ajax-crashing, opencode-delegate STOP tool-unavailable ×2 stalled the task; opencode 1.17.19 was installed — failure was environmental to that orchestrator
- Change: unavailable tool falls through once to the next matching lane; STOP only when no lane remains
- Checkpoint: bef77c8

## 2026-07-14 Tripwire thresholds retuned, two tripwires added
- Tripwire: user-directed
- Evidence: 2026-07-13 ajax-crashing opencode failed both of its only gated rounds (REVISE empty-diff, STOP missing-reports) without tripping 3-of-10; 30-row dead-row window skewed by all-cursor 2026-07-14 rows would have proposed deleting structural rows; 2026-07-13 ajax-jwts critique BLOCKed 4 consecutive packets before PASS (5 critique calls for 1 dispatch)
- Change: gate-failure tripwire adds 2-consecutive trigger; dead-row window 30→50; new critique-churn tripwire (3 consecutive BLOCKs → dispatch after next rebuild); new MiniMax-starvation tripwire (0 of last 15 dispatches → broaden lane)
- Checkpoint: bef77c8
