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

No entries yet.
