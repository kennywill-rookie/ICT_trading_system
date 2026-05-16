# Task — {YYYY-MM-DD_short_task_name}

## Task ID
YYYY-MM-DD_short_task_name

## Target Agent
Claude | Codex

## Mode
A (read-only) | B (modification)

## Objective
One clear sentence.

## Background
Relevant context, links, files, and prior decisions.

## Files / Components In Scope
- ...

## Out Of Scope
- ...

## Hard Escalation Check (per PHASE1.md)
Does this touch any of: `credentials.env`, `deploy_kenny.sh`, `ml_live_monitor.py`,
`scheduler.py`, `run_scan.py`, `run_scan.sh`, model artifacts, monitor state,
`trade_log.json`, `signal_log.json`, `logs_kenny/*`, OKX/live order logic,
kennyserver deployment, trading/model/alert thresholds, cumulative log
deletion/schema changes?

- [ ] Yes → human verdict mandatory before any modification
- [ ] No

## Allowed Actions
- ...

## Forbidden Actions
- ...

## Rollback Plan
How to undo this change if the verdict goes south or post-deployment issues appear.
Include: files to revert, state/data files that may have changed, dependent
services to restart, monitor-state implications.

## Expected Output
- Files changed, or
- Analysis summary, or
- Verdict

## Verification Required
- Commands to run
- JSON/report values to check
- Manual review points

## Escalation Rules
When to return NEEDS_HUMAN.
