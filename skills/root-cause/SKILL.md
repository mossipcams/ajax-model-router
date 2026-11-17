---
name: root-cause
description: Use when investigating a bug, test failure, or unexpected behavior, before proposing any fix.
---

# Root cause first

## Rules
1. Reproduce before anything else. Run the failing command or write a repro script and show the output. If you cannot reproduce it, stop and report what you tried.
2. State the root cause with evidence: a log line, stack trace, or value you observed. "Likely" or "probably" is not a root cause. If your why stops at a symptom ("route not found"), keep asking why.
3. Write a test that fails for the reported reason. Show the red run.
4. Make one minimal fix at the cause, not at the symptom. No null checks, retries, widened types, timeout bumps, or edited assertions unless that IS the cause.
5. Show the test passing and the original repro no longer failing.
6. After 3 failed fix attempts, stop and report: what you know, what you ruled out, what you'd check next.

## Report
- Cause:
- Evidence:
- Fix:
- Other places this pattern might exist:

## Project notes
If the repo has `docs/root-cause.md`, read it for log locations, repro commands, and known quirks.
