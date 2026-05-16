# Verdict — 2026-05-16_integrated_signal_decision_overhaul

## Task ID
2026-05-16_integrated_signal_decision_overhaul

## Verdict
ACCEPT (in-session, with conditions on follow-up verification)

## Verdict Authority
Kenny (orchestrator, per PHASE1.md § Verdict Authority).
Approval was given in-session via AskUserQuestion ("✅ ACCEPT — 지금 배포 실행") at deploy gate.
This file is the formal post-hoc record.

## Reason
The integrated plan correctly sequences (1) doc consolidation, (2) reversible code
renames, (3) BTC isolation in the ML monitor, and (4) deploy + immediate verification.
Schema-touching items (#3, #7) are correctly deferred because they mutate cumulative
logs that fall under Hard Escalation. Codex review (2026-05-16) was integrated:
P0 redefined as deploy+verify, sample-count gates added, 6-axis metrics required,
BTC inverse split into p20/p30 buckets, maintain criteria pre-specified.

Deploy-time verification passed on all reachable items:
- PM2 ml-monitor online (id=4, pid=235963)
- `asset_modes` correctly loaded and printed at startup
- BTC-USDT = paper_only, ETH-USDT/SOL-USDT = normal
- State preserved: 1 open position, 160 seen events, 319 log entries
- Two in-flight positions (ETH, SOL) closed cleanly (WIN R=1.39, R=1.44) before restart

## Checked Inputs
- task file: `agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md`
- result file: `agent_handoff/results/2026-05-16_integrated_signal_decision_overhaul.md`
- prior discussion: `agent_handoff/discussion/2026-05-16_codex_review_claude_patch_plan.md`
- data snapshots:
  - `ML_PAPER_TRADING_ANALYSIS_2026-05-11.md` (137 trades, 2026-03-18 ~ 2026-05-10)
  - `tools/results_diagnostic.json` (FVG +21.96R baseline, BTC −2.21R)
  - `tools/results_invert.json` (BTC Spearman −0.473, p=0.0007; bottom-30% +8.04R)
  - `backtest_15m_result.json` (BTC 15m total_R −233.37R, PF 0.59)
  - `backtest_result.json` (BTC Daily total_R +1.76R, PF 1.03)
- changed files (9 commits):
  - `.gitignore` (cb2693a)
  - imports: docs/framework (95c838f), code (abd0309)
  - `agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md` (d7a6dd4)
  - `signal_engine.py` rename Fundamental Dip → Price Dip (2e8f4ce)
  - `backtest_15m.py` DEPRECATED header (fda89df)
  - `ml_monitor_config.json` + `ml_live_monitor.py` asset_modes (e0db079)
  - `SIGNAL_TAXONOMY.md` + `DECISION_LAYER_SPEC.md` + `CLAUDE.md` (b552363)
  - `agent_handoff/results/...` (6d3df99) + deploy log append (c7a85dd)

### Verification commands run (in-session)
- `python3 -c "from signal_engine import SignalType; ..."` → PRICE_DIP = "Price Dip" ✅
- `python3 -c "import ast; ast.parse(open('ml_live_monitor.py').read())"` → parse OK ✅
- `python3 -c "import json; json.load(open('ml_monitor_config.json'))['asset_modes']"` → all 3 assets present ✅
- `grep -rn "FUNDAMENTAL_DIP" *.py *.json` → 0 (rename complete) ✅
- `grep -n "15m\|backtest_15m" scheduler.py run_scan.py run_scan.sh` → 0 (no live path) ✅
- `git push origin main` (9 commits) → OK ✅
- `bash deploy_kenny.sh` → PM2 online ✅
- `ssh kenny@... "pm2 logs ml-monitor --lines 40 --nostream"` → asset_modes printed correctly ✅

### Verification deferred (time-bound)
- `higher_tf_trend != 0.5` in new event records → next 4H boundary (UTC 12:00 / 16:00 / 20:00)
- New event records carry `asset_mode` field → first scan after deploy
- BTC paper_only effective (no Telegram) → first BTC FVG event after deploy

## Residual Risk

### Operational (must monitor 1–7 days)
1. **P0 fix may still be incomplete** — `LOOKBACK_15M=800` + history-candles paging is in source, but only the first 4H scan after deploy will prove `higher_tf_trend` is no longer frozen at 0.5. If it is still frozen, fetch_recent_15m paging is broken at a deeper level.
2. **`asset_mode` field persistence** — newly created events / positions should carry `asset_mode`. Must inspect `ml_monitor_log.json` after first scan.
3. **Telegram for BTC remains blocked silently** — there is no positive heartbeat that proves BTC signals were generated and intentionally not sent. Need to check that `paper-track` positions for BTC do accumulate.

### Structural (acknowledged, deferred)
4. **`asset_mode` branch only gates Telegram**, not inverse entry. Inverse trading rule is in `DECISION_LAYER_SPEC.md` (planned), not in code.
5. **`decision_log.json` does not exist yet** — there is no audit trail linking checklist verdict + rule signal + ML proba + outcome to a single record. Sample data for backtest of the combined score is therefore unavailable.
6. **BTC sample size is small** (48 events) — Codex maintain criteria (n≥30 per bucket, p<0.05) cannot be evaluated until at least ~3 weeks of post-P0 data is collected.

### Repo / supply-chain
7. **GitHub repo visibility** is set by Kenny on GitHub side; not enforced from local. If public, all source is publicly readable (no secrets/models leaked due to .gitignore, but logic is open).
8. **Phase-1 git policy** is silent on git (was deferred). Git is now in use; PHASE1.md amendment task needed for audit consistency.

## Data / Snapshot Validity Assessment

### Still current (use freely)
- `signal_engine.py` rule definitions
- `ml_live_monitor.py` runtime behavior (post-deploy 2026-05-16)
- `SIGNAL_TAXONOMY.md` (single source-of-truth)
- `DECISION_LAYER_SPEC.md` v0.1 (proposal, requires Codex review)

### Stale until re-measured (do NOT base trading decisions on these)
- `tools/results_invert.json` BTC bottom-30% advantage — measured on frozen-htf model output. Post-P0 must remeasure.
- `tools/results_diagnostic.json` calibration buckets — same reason.
- `ML_PAPER_TRADING_ANALYSIS_2026-05-11.md` Spearman / Brier figures — measured pre-P0 (snapshot 2026-05-10).
- Codex `maintain criteria` numbers (n≥30, WR≥58%, PF≥1.5, avgR>+0.15) — proposed thresholds, not measured outcomes.

### Permanent / append-only
- `ml_monitor_state.json`, `ml_monitor_log.json` (kennyserver) — preserved across deploy (verified). All new entries from 2026-05-16 deploy onward carry the new `asset_mode` field.

## Required Next Action

### Immediate (today / next 24h)
1. After next 4H boundary, run verification block from result doc § "Verification commands (post-deploy)" step 3 — `higher_tf_trend` distribution check.
2. After first new event (paper_only or normal), confirm `asset_mode` field is present in `ml_monitor_log.json`.

### Within 7 days
3. File task `2026-05-XX_post_p0_remeasure.md` — recompute all 6-axis metrics (Spearman + WR + avgR + PF + MDD + calibration + distribution) on post-P0 data, asset-split + direction-split.
4. File task `2026-05-XX_phase1_git_policy.md` — Phase-1 amendment to formally adopt git tracking (the policy was deferred when Phase-1 started).

### Within 2-3 weeks (gated on sample count)
5. When BTC ≥ 20 new events: preliminary inverse-edge check (paper-only).
6. When BTC ≥ 30 new events: full Codex maintain-criteria evaluation. Decide BTC inverse adoption / continue paper_only / disable.
7. File task `2026-05-XX_btc_specific_retrain.md` — parallel BTC-only model with 2024 trend regime + walk-forward CV.

### Conditional on agreement
8. File task `2026-05-XX_event_table_schema_v1.md` — #3 (cumulative log schema, full Hard Escalation cycle).
9. File task `2026-05-XX_checklist_to_traderecord.md` — #7.
10. File task `2026-05-XX_decision_layer_v1_implementation.md` — #8, gated on Codex review of `DECISION_LAYER_SPEC.md` v0.1.
11. File task `2026-05-XX_liquidity_sweep_prototype.md` — per `SIGNAL_TAXONOMY.md` §7 protocol.

## Fallback Rules (per PHASE1.md)
- REJECT → would require revert of commits `2e8f4ce`, `fda89df`, `e0db079`, `b552363`, `6d3df99`, `c7a85dd`, plus redeploy of pre-change `ml_live_monitor.py` + `ml_monitor_config.json` to kennyserver. State files unaffected.
- REVISE → next result must explicitly address the revision point before acceptance.

## Acceptance Conditions Met
- [x] Task file exists with Hard Escalation Check ticked
- [x] Result file lists files changed, data impact, known limitations
- [x] All code changes pushed to `origin/main` (https://github.com/kennywill-rookie/ICT_trading_system)
- [x] Deploy executed successfully (PM2 status online)
- [x] Startup log confirms `asset_modes` loaded correctly
- [x] State / cumulative log files preserved (no data loss)
- [x] Out-of-scope items explicitly enumerated with follow-up task placeholders
- [x] Rollback plan documented for each changed component

## Sign-off
Verdict: **ACCEPT**
Date: 2026-05-16
Authority: Kenny (in-session AskUserQuestion authorization, this file = post-hoc record)
Scope: this task only. Each follow-up task above must obtain its own verdict per Phase-1.
