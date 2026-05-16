# Verdict — {YYYY-MM-DD_short_task_name}

## Task ID
(matching the task filename)

## Verdict
ACCEPT | REJECT | REVISE | NEEDS_HUMAN

## Reason
Short factual explanation.

## Checked Inputs
- task file: agent_handoff/tasks/{...}.md
- result file: agent_handoff/results/{...}.md
- changed files: {list}
- verification commands run: {list with outputs or pass/fail}

## Residual Risk
- ...

## Data / Snapshot Validity Assessment
- Is the data used in the result still considered current?
- Are there any stale-artifact concerns for downstream decisions?

## Required Next Action
- none (ACCEPT)
- ask Claude to revise: {specific points}
- ask Codex to revise: {specific points}
- run additional tests: {list}
- request human re-approval (for boundary cases that emerged)

## Fallback Rules (per PHASE1.md)
- REJECT → no implementation accepted; new or revised task required before further work
- REVISE → next result must explicitly address the requested revision before acceptance
