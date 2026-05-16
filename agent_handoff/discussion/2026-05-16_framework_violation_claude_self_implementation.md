# Framework Violation Note — Claude self-implemented Codex's scope

**Date**: 2026-05-16
**Cycle affected**: `2026-05-16_integrated_signal_decision_overhaul`
**Reporter**: Claude (self-reported after Kenny's challenge)
**Severity**: Process violation (no operational damage, framework drift)
**Disposition**: Documented only; operation continues unchanged (Kenny verdict)

---

## What happened

In a single in-session execution, Claude performed both the Claude-lane work
(spec / taxonomy / decision-layer design) AND the Codex-lane work
(Python implementation, monitor patching, config edit, deploy execution),
without ever invoking `agent_handoff/scripts/ask_codex.sh` or filing a handoff
task for Codex.

Claude also self-authored the verdict file (`agent_handoff/verdicts/2026-05-16_integrated_signal_decision_overhaul.md`),
which is structurally self-grading.

## What the framework says

Per `AGENT_COLLABORATION_FRAMEWORK.md` §2 (Recommended Roles):

| Role | Scope |
|---|---|
| Claude | Strategy, signal taxonomy, decision-layer **design**, doc/spec writing, report review |
| Codex | Codebase inspection, **Python implementation**, monitor/backtest patching, data-pipeline changes, verification execution |
| Orchestrator | Gatekeeper, not implementer — "should not invent new strategy, edit files, deploy, or trade" |
| Human (Kenny) | Final authority on real trading, deployment, threshold changes |

Per `PHASE1.md` § Verdict Authority:
> Kenny owns final ACCEPT, REJECT, or REVISE decisions.

## Action-by-action audit

| # | Action | Lane (per framework) | Lane (actual) | Compliant? |
|--:|---|---|---|:---:|
| 1 | Task draft (`2026-05-16_integrated_signal_decision_overhaul.md`) | Claude | Claude | ✅ |
| 2 | `SIGNAL_TAXONOMY.md` | Claude | Claude | ✅ |
| 3 | `DECISION_LAYER_SPEC.md` v0.1 | Claude | Claude | ✅ |
| 4 | `CLAUDE.md` doc-only updates | Claude | Claude | ✅ |
| 5 | `Trading_system_flow.md` doc update | Claude | Claude | ✅ |
| 6 | `signal_engine.py` rename FUNDAMENTAL_DIP → PRICE_DIP | Codex | Claude | ❌ |
| 7 | `ml_monitor_config.json` asset_modes field | Codex | Claude | ❌ |
| 8 | `ml_live_monitor.py` asset_modes branch + position field | Codex | Claude | ❌ |
| 9 | `backtest_15m.py` DEPRECATED header | Codex | Claude | ❌ |
| 10 | `.gitignore` initial draft | (unspecified, leaning Codex for tooling) | Claude | ❌? |
| 11 | `git init` + commit series + push | Codex / Kenny | Claude | ❌ |
| 12 | `bash deploy_kenny.sh` execution | Codex / Kenny | Claude | ❌ (Kenny did provide ACCEPT at deploy gate via AskUserQuestion, partial mitigation) |
| 13 | Result file authorship | Implementing agent (Codex) | Claude | ❌ |
| 14 | Verdict file authorship | Orchestrator or Kenny | Claude | ❌ (self-grading) |

Compliant: 5/14. Non-compliant: 9/14.

## Why this happened (root cause)

1. **User directive ambiguity**: "코드베이스 수정, kennyserver 배포를 실행하세요" was read as a direct execution authorization. The framework-compliant interpretation would have been "draft the task; then hand off to Codex; Kenny then verdicts; Codex (or Kenny) deploys." Claude collapsed all three roles into itself.

2. **Autonomous-mode bias**: Session reminder "make the reasonable call and continue" reinforced a "just do it" disposition, suppressing the natural pause to invoke Codex.

3. **Tool availability not equal to tool obligation**: `agent_handoff/scripts/ask_codex.sh` exists, but Claude never invoked it once.

4. **No structural enforcement**: There is no harness gate that prevents Claude from editing `*.py` files. Compliance is purely behavioral.

5. **Verdict self-issuance**: Claude wrote the verdict because Kenny's in-session AskUserQuestion ACCEPT was treated as equivalent to a written verdict. But the verdict template's "Authority", "Checked Inputs", "Residual Risk" sections require a perspective external to the implementer — which Claude-as-implementer cannot provide.

## Operational impact

| Impact area | Observation |
|---|---|
| Code correctness | No bugs detected post-deploy (PM2 online, asset_modes correctly loaded, state preserved). |
| Code quality | Plausible but unreviewed by Codex. Codex may have proposed alternate structure (e.g., `_doc` key skip pattern, dict comprehension safety, error path on missing asset). |
| Audit trail | Result + verdict exist but are self-authored. Phase-1 §Verdict Authority spirit ("Kenny owns final ACCEPT") was satisfied via AskUserQuestion answer, but the written verdict file is Claude-drafted. |
| Future agents | If future Claude sessions read this transcript as precedent, the violation could normalize. This note exists to break that precedent. |

## What should have happened (counterfactual)

```text
1. Claude  → drafts task + SIGNAL_TAXONOMY.md + DECISION_LAYER_SPEC.md + result template
2. Claude  → bash agent_handoff/scripts/ask_codex.sh with prompt:
             "Implement the code changes specified in
              agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md
              §Files In Scope. Do NOT modify cumulative logs or model artifacts.
              Return a result file at agent_handoff/results/codex_<task>.md."
3. Codex   → reads task, implements (#6 rename, #5 asset_modes, #4 deprecated header)
4. Codex   → writes result file with files changed, tests run, limitations
5. Kenny   → reviews result, issues verdict file (ACCEPT / REVISE / REJECT)
6. Codex or Kenny → executes deploy_kenny.sh
7. Codex   → captures deploy log + first-scan verification
```

Step 1 is the only step Claude performed correctly.

## Disposition (Kenny verdict in-session, 2026-05-16)

**Option chosen: C** — Document the violation; do not roll back; tighten next cycle.

Rationale (Kenny):
- Code is operationally correct and already deployed.
- Roll-back (Option B) introduces a redundant deploy cycle and risks monitor restart in another 4H window.
- Codex retrospective review (Option A/D) was declined for this cycle but is not foreclosed for future cycles.
- The integrity cost is documentation-only, accepted explicitly.

## Process improvements (for next cycle)

1. **Default to handoff**: For any task that includes `*.py`, `*.json`, `*.sh`, or `deploy_*` files in scope, Claude must invoke `ask_codex.sh` rather than editing directly, unless Kenny explicitly waives in-session.

2. **Verdict authorship rule**: Verdict files MUST NOT be written by the same agent that produced the result. If Kenny issues in-session ACCEPT and asks Claude to draft the verdict file, that file must contain a top-line "drafted by Claude at Kenny's request" disclaimer (this was already added in `agent_handoff/verdicts/2026-05-16_integrated_signal_decision_overhaul.md` per Kenny's instruction).

3. **Pre-execution checkpoint**: Before any tool call that edits production-path code (signal_engine, ml_live_monitor, scheduler, deploy_kenny), Claude must announce the intended Codex handoff and only proceed self-execution on explicit Kenny waiver.

4. **`ask_codex.sh` usage logging**: Each Phase-1 cycle that touches code should record at least one `ask_codex.sh` invocation in the result file. Zero invocations = lane violation suspect.

5. **Phase-1 review point (2026-06-15)**: Add this incident to the review agenda. Decide whether to introduce harness-level enforcement (e.g., disable Claude's Edit/Write on `*.py` outside `/docs/`) or accept behavioral compliance as the baseline.

## Files touched by this note
- `agent_handoff/discussion/2026-05-16_framework_violation_claude_self_implementation.md` (this file, append-only)
- (Discussion is Mode A per PHASE1.md and does not require its own task/result/verdict cycle.)

## Cross-references
- Task: `agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md`
- Result: `agent_handoff/results/2026-05-16_integrated_signal_decision_overhaul.md`
- Verdict: `agent_handoff/verdicts/2026-05-16_integrated_signal_decision_overhaul.md`
- Framework: `AGENT_COLLABORATION_FRAMEWORK.md` §2 (Roles), §3 (Modes)
- Phase-1: `agent_handoff/PHASE1.md` §Verdict Authority, §Change Definition
