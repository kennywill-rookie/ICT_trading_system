<!-- Phase-1 toolchain setup completed: 2026-05-15 -->
<!-- Source: agent_handoff/discussion/2026-05-15_framework_review.md Turn 7 -->

# Phase-1 Adoption Agreement

**Phase-1 started: 2026-05-15** (1-month review window ends ~2026-06-15)

## Purpose

Phase-1 adopts `AGENT_COLLABORATION_FRAMEWORK.md` as a human-operated collaboration and safety process for this trading-system project.

This phase does not introduce an automated orchestrator, wrapper runtime beyond Codex prompt injection, deployment automation, or additional LLM verdict authority. Kenny is the final orchestrator and verdict owner.

## Required References

`CLAUDE.md` must contain a hard reference near the top requiring Claude sessions to read and follow `AGENT_COLLABORATION_FRAMEWORK.md` before collaborative or file-modifying work.

Codex framework awareness is handled through `ask_codex.sh` or its successor wrapper. The wrapper must inject a concise framework summary before the user prompt for Codex calls.

If Codex is used directly without the wrapper, Kenny owns responsibility for applying the framework manually. No `AGENTS.md`, global Codex config, or cross-project instruction mechanism is introduced in Phase-1.

## Phase-1 Start

The initial toolchain setup is exempt from the task/result/verdict cycle:

- creating `agent_handoff/PHASE1.md`
- adding the `CLAUDE.md` hard reference
- implementing framework injection in `ask_codex.sh` or its successor wrapper
- updating `AGENT_COLLABORATION_FRAMEWORK.md` to reference this Phase-1 agreement

Phase-1 begins after this setup is complete.

## Review Point

Phase-1 will be reviewed after 1 month of operation from the setup completion date.

At review, Kenny decides one of:

- keep the full task/result/verdict flow
- discard the framework
- reduce verdict requirements to high-risk changes only
- introduce additional automation or permission enforcement

## Change Definition

A Phase-1 “change” requires the full task/result/verdict cycle.

Changes include:

- source code file modification, addition, or deletion
- shell script modification, addition, or deletion
- operational JSON/TOML/config modification
- model artifact, model registry, monitor state, or cumulative log mutation
- scheduler, cron, deployment, live monitor, scan runner, or alerting behavior change
- framework-governing document changes, including `AGENT_COLLABORATION_FRAMEWORK.md`, `PHASE1.md`, and the hard-reference area of `CLAUDE.md`

The following do not require the full cycle while remaining within Mode A:

- appending discussion turns under `agent_handoff/discussion/**`
- automatic logs under `agent_handoff/logs/**`
- one-off read-only notes or analysis artifacts that do not modify source, config, runtime behavior, model state, or cumulative data
- typo or formatting fixes that do not change framework meaning or operational behavior

## Operating Rule

Every Phase-1 change requires:

1. Task
2. Result
3. Verdict

No code, config, model, threshold, scheduler, live monitor, credentials, deployment, or data mutation is accepted until a human verdict exists.

Read-only discussion may occur in Mode A without a task. Any transition from discussion to modification must be declared by Kenny and must start with a task document.

## File Locations and Naming

Use these paths unless Kenny explicitly approves another location:

- `agent_handoff/tasks/YYYY-MM-DD_short_task_name.md`
- `agent_handoff/results/YYYY-MM-DD_short_task_name.md`
- `agent_handoff/verdicts/YYYY-MM-DD_short_task_name.md`
- `agent_handoff/discussion/YYYY-MM-DD_topic.md`

Any participant may draft a task. Only Kenny can approve a task as active.

## Verdict Authority

Kenny owns final `ACCEPT`, `REJECT`, or `REVISE` decisions.

Claude leads strategy, trading semantics, signal definitions, regime interpretation, and specification critique.

Codex leads implementation feasibility, code-path analysis, test/backtest implementation planning, and verification design.

If Claude and Codex disagree, the disagreement must be captured in the verdict or a linked discussion note. Kenny decides whether to proceed, revise, or stop.

If a verdict is `REJECT`, no implementation from that task is accepted. A new or revised task is required before further work.

If a verdict is `REVISE`, the next result must explicitly address the requested revision before acceptance.

## Hard Escalation Items

The following always require explicit Kenny approval and a verdict:

- `credentials.env` or any secret-bearing file
- OKX/live order placement or order-routing behavior
- kennyserver deployment or runtime service changes
- `deploy_kenny.sh` or any deployment-equivalent script
- trading thresholds, model-selection thresholds, alert thresholds
- `ml_live_monitor.py`
- `scheduler.py`
- `run_scan.py`
- `run_scan.sh`
- any scheduler, scan-runner, live-monitor, alerting, or deployment-equivalent file, even if renamed
- model artifacts, model registry files, or live/paper monitor state
- deletion, truncation, regeneration, or schema-changing edits to cumulative research/runtime data, including `trade_log.json`, `signal_log.json`, `logs_kenny/*`, `ml_monitor_state.json`, and similar files

## Guardrails

FVG ML diagnostic results must not be generalized to the whole trading system unless the evaluated data, signal scope, and model scope explicitly support that conclusion.

Paper trading components may still affect live data collection, monitoring continuity, and future evaluation. Treat paper monitor changes as operationally significant.

Scheduler and scan-runner changes are operational changes because they affect timing, alerting, and data collection coverage.

Analysis artifacts are not source of truth by default. Any result based on prior outputs must identify its data snapshot.

## Template Requirements

Each Task must include:

- Mode
- Files or components in scope
- Out-of-scope items
- Human escalation check
- Rollback Plan

Each Result must include:

- Files inspected or changed
- Tests/checks performed
- Data impact
- Snapshot date
- Input span
- Input file hashes where practical, otherwise exact filenames and date ranges
- Known limitations

Each Verdict must include:

- `ACCEPT`, `REJECT`, or `REVISE`
- Reason
- Residual risk
- Data/snapshot validity assessment
- Follow-up required, if any

## Git Policy

No git tracking policy is defined in Phase-1 because this project is not currently operated as a git repository.

`agent_handoff/` remains a filesystem audit trail. Git tracking, ignore rules, and archival policy are deferred until git is introduced.
