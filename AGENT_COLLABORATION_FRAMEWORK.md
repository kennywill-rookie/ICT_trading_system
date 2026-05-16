# Agent Collaboration Framework

> **Active phase**: see [`agent_handoff/PHASE1.md`](agent_handoff/PHASE1.md) (Phase-1 started 2026-05-15, review ~2026-06-15).
> Phase agreements override this framework where they conflict.
> Discussion record: [`agent_handoff/discussion/2026-05-15_framework_review.md`](agent_handoff/discussion/2026-05-15_framework_review.md).

Purpose: Define how Claude, Codex, an optional orchestrator, and the human operator should collaborate on this trading-system codebase.

This file is intended to be read by Claude, Codex, and future agents as an operating framework. It is not a trading strategy by itself. Current user instructions, source code, configs, and verified data remain the source of truth for any concrete task.

---

## 1. Core Principle

Use a hybrid collaboration model:

```text
Limited read-only direct communication
  + markdown handoff documents
  + orchestrator verdict gate
  + human escalation for risky actions
```

Direct agent communication is allowed only for fast understanding, review, interpretation, and planning.

Any action that changes code, deployment, live model behavior, thresholds, credentials, or trading execution must go through a markdown handoff and receive a verdict before execution.

---

## 2. Recommended Roles

### Claude

Primary role:

- Strategy interpretation
- Trading hypothesis design
- Signal taxonomy and decision-layer design
- Report review and narrative synthesis
- Risk framing
- Documentation/spec writing

Typical Claude tasks:

- Define how FVG, Structure Shift, Liquidity Sweep, and HTF Bias should be combined.
- Review whether a conclusion is strategically overgeneralized.
- Interpret diagnostics by asset, direction, and regime.
- Draft or revise markdown specs and research plans.

### Codex

Primary role:

- Codebase inspection
- Python implementation
- Backtest and diagnostic tooling
- Data pipeline and logging changes
- Test/verification execution
- Code review and bug fixing

Typical Codex tasks:

- Implement event logging.
- Add feature extraction.
- Create diagnostic scripts.
- Verify report numbers against JSON outputs.
- Patch monitor/backtest code.

### Orchestrator

Primary role:

- Gatekeeper, not implementer
- Reviews task/result pairs
- Produces structured verdicts
- Routes revisions to the correct agent
- Escalates risky actions to the human

The orchestrator should not invent new strategy, edit files, deploy, or trade.

### Human

Final authority for:

- Real trading
- Deployment
- Credentials/API access
- Model replacement
- Threshold changes affecting live monitor behavior
- Any irreversible or financially sensitive operation

---

## 3. Communication Modes

### Mode A: Read-Only Direct Communication

Used for fast questions between agents.

Allowed purposes:

- Code understanding
- File/function location
- Analysis interpretation
- Report review
- Design option comparison
- Risk identification
- Test planning
- Documentation clarification

Examples:

```text
Claude → Codex:
Read signal_engine.py and summarize how Structure Shift is detected. Do not edit files.

Codex → Claude:
Interpret the BTC mismatch diagnostics strategically. Do not recommend live trading changes.
```

Allowed actions:

- Read files
- Summarize
- Compare
- Critique
- Identify risks
- Propose options

Forbidden actions:

- Edit files
- Change configs
- Run deployment
- Modify model files
- Change thresholds
- Read or modify credentials unless explicitly approved
- Place or simulate real orders
- Delete logs/state/data

Recommended message metadata:

```yaml
scope: read_only
purpose: code_understanding | analysis_review | strategy_interpretation | risk_review | test_planning
allowed_actions:
  - read_files
  - summarize
  - compare
  - critique
forbidden_actions:
  - edit_files
  - deploy
  - change_config
  - trade
  - delete_data
requires_verdict: false
requires_human: false
```

### Mode B: Markdown Handoff

Used when work needs to be persisted, reviewed, or implemented.

Handoff documents should be used for:

- Code changes
- Dataset or schema changes
- New diagnostics
- Model training workflow changes
- Strategy specs
- Decision-layer specs
- Long-term plans
- Any result that future agents need to audit

Suggested directory:

```text
agent_handoff/
  tasks/
  results/
  verdicts/
  logs/
  templates/
```

Suggested task filename:

```text
agent_handoff/tasks/YYYY-MM-DD_short_task_name.md
```

Suggested result filename:

```text
agent_handoff/results/agent_YYYY-MM-DD_short_task_name.md
```

Suggested verdict filename:

```text
agent_handoff/verdicts/orchestrator_YYYY-MM-DD_short_task_name.md
```

### Mode C: Verdict-Gated Action

Required before:

- Code modification is accepted as complete
- Live monitor behavior is changed
- Thresholds are applied
- Model files are replaced
- Deployment is executed
- Risk-sensitive config is changed

The verdict can be produced by an orchestrator or, for high-risk items, by the human.

---

## 4. Handoff Document Template

```md
# Agent Handoff Task

## Task ID
YYYY-MM-DD_short_task_name

## Target Agent
Claude | Codex | Orchestrator

## Objective
One clear sentence.

## Background
Relevant context, links, files, and prior decisions.

## Scope
What is included.

## Out Of Scope
What must not be changed or decided.

## Files To Read
- ...

## Allowed Actions
- ...

## Forbidden Actions
- ...

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
```

---

## 5. Agent Result Template

```md
# Agent Result

## Task ID
...

## Agent
Claude | Codex

## Summary
Short summary of what was done.

## Findings
Important results or review findings.

## Files Changed
- file path
- file path

## Verification
Commands run and results.

## Risks / Limitations
Known uncertainty or remaining risk.

## Recommended Next Step
One concrete next action.
```

---

## 6. Orchestrator Verdict Template

```md
# Orchestrator Verdict

## Task ID
...

## Verdict
APPROVE | REVISE | REJECT | NEEDS_HUMAN

## Reason
Short factual explanation.

## Checked Inputs
- task file:
- result file:
- changed files:
- verification:

## Risks
- ...

## Required Next Action
- none
- ask Claude to revise
- ask Codex to revise
- run tests
- request human approval
```

Verdict meanings:

| Verdict | Meaning |
|---|---|
| `APPROVE` | Work is acceptable and next non-risky step may proceed. |
| `REVISE` | Return to the same or another agent with specific corrections. |
| `REJECT` | Do not use the result. Significant mismatch or unsafe output. |
| `NEEDS_HUMAN` | Human approval is required before any further action. |

---

## 7. Mandatory Human Escalation

The following must always return `NEEDS_HUMAN` unless the user explicitly requested the action in the current task:

- Real trading / actual order execution
- OKX API order logic activation
- `credentials.env` modification
- API key scope changes
- kennyserver deployment execution
- Live model replacement
- Live threshold/config changes
- Switching paper trading to real trading
- Deleting or overwriting trade/state/log files
- Destructive git or filesystem actions
- PnL/risk formula changes that affect live decisions

---

## 8. Project-Specific Guardrails

1. Do not treat FVG ML monitor results as the full Structural Edge system result.
2. FVG, Structure Shift, Liquidity Sweep, RSI Divergence, HTF Bias, 120-day MA support, and Fundamental Dip are separate signal candidates.
3. Each signal should eventually follow an event → feature → label → outcome data pipeline.
4. Signal alpha must be analyzed by:
   - asset
   - direction
   - timeframe
   - HTF alignment
   - market regime
   - sentiment proxy
   - rolling time-course window
5. A model failure does not automatically mean the underlying signal has no alpha.
6. Feature collection bugs must be treated as instrumentation failures before drawing strategy conclusions.
7. Live deployment and real trading changes require human approval.

---

## 9. Suggested Minimal Implementation

Start with files only:

```text
agent_handoff/
  tasks/
  results/
  verdicts/
  templates/
```

Then optionally add wrappers:

```text
call_codex_from_claude.sh
call_claude_from_codex.sh
call_orchestrator.sh
```

Wrappers should only do:

```text
task file → agent invocation → result file
```

Wrappers must not:

- auto-merge
- auto-deploy
- auto-edit live config
- auto-run real trading

---

## 10. Optional Direct-Communication Runtime

If using OpenClaw or another session-based runtime, implement direct communication through a session manager:

```text
Claude session
  ↕
Session Manager / Orchestrator
  ↕
Codex session
```

Required primitives:

```text
create_session(agent_type)
send_message(session_id, message)
read_response(session_id)
close_session(session_id)
```

All direct messages should carry scope metadata.

Example:

```json
{
  "from": "claude",
  "to": "codex",
  "scope": "read_only",
  "purpose": "code_understanding",
  "message": "Summarize how FVG events are detected in ml_data_pipeline.py.",
  "allowed_actions": ["read_files", "summarize"],
  "forbidden_actions": ["edit_files", "deploy", "change_config", "trade"],
  "requires_verdict": false,
  "requires_human": false
}
```

Direct communication should be used for thinking, not applying changes.

---

## 11. Recommended Workflow

```text
DISCUSS
  - Direct read-only communication allowed
  - Goal: understand, interpret, compare options

SPEC
  - Markdown handoff task created
  - Scope and constraints written down

IMPLEMENT
  - Codex implements or Claude drafts spec
  - Result markdown produced

REVIEW
  - Orchestrator checks task/result/changes
  - Verdict markdown produced

APPLY
  - Only approved non-risky changes continue
  - Risky actions require human approval
```

---

## 12. One-Line Summary

Use direct agent communication for fast read-only thinking, markdown handoff for durable task transfer, orchestrator verdicts for controlled execution, and human approval for anything that can affect live trading, deployment, credentials, or capital.
