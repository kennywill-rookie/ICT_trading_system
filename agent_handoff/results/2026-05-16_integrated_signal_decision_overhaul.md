# Result — 2026-05-16_integrated_signal_decision_overhaul

## Task ID
2026-05-16_integrated_signal_decision_overhaul

## Agent
Claude (Opus 4.7, 1M context)

## Snapshot date
2026-05-16

## Input span / data snapshots used
- `agent_handoff/discussion/2026-05-16_codex_review_claude_patch_plan.md` (Codex review)
- `ML_PAPER_TRADING_ANALYSIS_2026-05-11.md` (137 trades, 2026-03-18 ~ 2026-05-10)
- `tools/results_diagnostic.json` (FVG baseline, BTC -2.21R)
- `tools/results_invert.json` (BTC Spearman -0.473, p=0.0007; bottom-30% +8.04R)
- `backtest_15m_result.json` (BTC-USD 15m, total_R -233.37R, PF 0.59)
- `backtest_result.json` (BTC-USD Daily, total_R +1.76R, PF 1.03)
- Current code: `signal_engine.py`, `ml_live_monitor.py`, `ml_monitor_config.json`,
  `dashboard.py`, `deploy_kenny.sh`

## Files inspected
- `signal_engine.py` (1041 lines) — SignalType enum, scan_asset, TradeRecord
- `ml_live_monitor.py` (642 → 660 lines after patch) — main loop, scan_asset, Telegram
- `ml_data_pipeline.py` (748 lines) — feature schema (20)
- `dashboard.py` — CHECKLIST const + verdict thresholds
- `config.json`, `ml_monitor_config.json`, `deploy_kenny.sh`
- `Trading_system_flow.md`, `CLAUDE.md`, `agent_handoff/PHASE1.md`

## Files changed (this cycle)

### Created
1. `.gitignore` — secrets, models, cumulative logs, runtime state, internal-only files
2. `SIGNAL_TAXONOMY.md` — single source-of-truth (state matrix, asset matrix, ML scope, deprecated, Liquidity Sweep decision protocol)
3. `DECISION_LAYER_SPEC.md` v0.1 — proposed unified decision layer (`planned`)
4. `agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md`
5. `agent_handoff/results/2026-05-16_integrated_signal_decision_overhaul.md` (this file)

### Modified
1. `signal_engine.py`
   - `SignalType.FUNDAMENTAL_DIP` → `PRICE_DIP` (value "Price Dip")
   - reason string + print 갱신
   - NOTE comment 추가: 순수 가격 트리거, fundamental/news 미구현
2. `Trading_system_flow.md`
   - 시그널 표: "Price Dip" + 설명 정정
3. `CLAUDE.md`
   - SIGNAL_TAXONOMY.md, DECISION_LAYER_SPEC.md hard reference 추가
   - 자산 표: Order Block → planned, Fundamental Dip → Price Dip
   - ML 해석 § 2026-05-16 update 단락 추가
4. `ml_monitor_config.json`
   - 신규 필드 `asset_modes`: BTC=paper_only, ETH/SOL=normal
5. `ml_live_monitor.py`
   - `main()`: `asset_modes` 로드 + 시작 로그에 출력
   - 스캔 루프: `disabled` 자산 skip, `paper_only`면 Telegram 차단·paper-track 유지
   - position 레코드에 `asset_mode` 보존
6. `backtest_15m.py`
   - 헤더 DEPRECATED 블록 추가 (코드 보존)

### Not modified (out of scope, deferred)
- `trade_log.json`, `signal_log.json` (Hard Escalation cumulative logs)
- `TradeRecord` dataclass
- `ml_fvg_model.pkl`, `ml_fvg_dataset.csv`
- `scheduler.py`, `run_scan.py`, `run_scan.sh` (15m 호출 없음 확인)
- `credentials.env`
- `dashboard.py` 체크리스트 (verdict 영구화는 #7 별도 task)

## Tests / checks performed

### Static
```bash
# Rename consistency
grep -rn "FUNDAMENTAL_DIP\|Fundamental Dip" *.py *.json
# Result: 0 in code, 1 in this result doc (intentional)

# Enum import
python3 -c "from signal_engine import SignalType; print(SignalType.PRICE_DIP.value)"
# Result: 'Price Dip'

# All enum members
['Liquidity Sweep', 'Structure Shift', 'FVG Entry', 'RSI Divergence',
 '120일선 지지', 'Price Dip']

# AST parse
python3 -c "import ast; ast.parse(open('ml_live_monitor.py').read())"
# Result: parse OK, 660 lines

# JSON validity
python3 -c "import json; print(json.load(open('ml_monitor_config.json'))['asset_modes'])"
# Result: {'_doc': '...', 'BTC-USDT': 'paper_only', 'ETH-USDT': 'normal', 'SOL-USDT': 'normal'}
```

### Runtime (pre-deploy)
- 변경된 `ml_live_monitor.py`를 로컬에서 import-level 검증만 수행 (live 호출 안 함)
- `deploy_kenny.sh`의 `FILES[]`를 검사하여 `ml_monitor_state.json` / `ml_monitor_log.json`이 **포함되지 않음을 확인** → 서버의 누적 로그·오픈 포지션 보존

### Git
```text
4 commits pushed to origin/main:
  cb2693a Add .gitignore
  95c838f Initial import: docs, framework
  abd0309 Initial import: signal engine, ML pipeline, live monitor
  d7a6dd4 Add task: 2026-05-16 integrated signal/decision overhaul
  2e8f4ce Rename Fundamental Dip -> Price Dip (#6)
  fda89df Deprecate 15m rule-based backtest (#4)
  e0db079 Add per-asset mode gating, BTC -> paper_only (#5)
  b552363 Add SIGNAL_TAXONOMY.md + DECISION_LAYER_SPEC.md (#1 #9 #2)
```

Repo: https://github.com/kennywill-rookie/ICT_trading_system

## Data impact

### Cumulative logs (kennyserver)
- `ml_monitor_state.json` (open positions) — **unchanged** (not in deploy FILES)
- `ml_monitor_log.json` (cumulative events) — **unchanged** (not in deploy FILES)
- 신규 이벤트부터 `asset_mode` 필드가 함께 기록됨 (additive, 기존 reader는 무시)
- 신규 position부터 `asset_mode` 보존 (사후 BTC 분리 분석 가능)

### Past signal_log.json entries
- "Fundamental Dip" 문자열 그대로 유지 (mutation 없음). 신규 entry부터 "Price Dip".

### Past trade_log.json entries
- 영향 없음 (스키마 변경 없음)

### Telegram
- 본 배포 시점부터 BTC FVG 신호는 Telegram 발송 **차단**. ETH/SOL은 정상 발송.
- 시작 직후 startup 알림은 그대로 발송 (모든 자산 목록 표시)

## Known limitations

1. **P0 verification은 배포 직후가 아닌 다음 4H 경계 이후 (UTC 00/04/08/12/16/20)** — `higher_tf_trend != 0.5` 확인은 1-4시간 대기 필요. 본 result는 배포 직후의 PM2 상태만 보고하며, full P0 게이트(events≥5, std 회복)는 별도 follow-up.
2. **`asset_mode` 분기는 Telegram만 차단**. 본 변경은 inverse 진입 룰을 코드화하지 않음 — 그건 DECISION_LAYER_SPEC.md §3·§4의 사후 task.
3. **BTC inverse 채택은 미결정** — 본 cycle은 BTC 격리(paper_only)만 수행. 채택 여부는 post-P0 maintain criteria (n≥30, WR≥58%, PF≥1.5, avgR>+0.15) 만족 시 별도 task로 결정.
4. **Decision Layer 구현 0**. 명세만 작성. 합의·backtest 후 코드화.
5. **Liquidity Sweep prototype 미실행**. 결정 프로토콜만 SIGNAL_TAXONOMY.md §7에 기록.
6. **Event table schema (#3) 미실행**. trade_log/signal_log schema 변경은 cumulative log Hard Escalation이라 별도 task 필요.
7. **체크리스트 verdict TradeRecord 영구화 (#7) 미실행**. dashboard.py + TradeRecord dataclass 동시 변경이라 별도 task.

## Verification commands (post-deploy)

```bash
# 1. PM2 status
ssh kennyserver "pm2 status ml-monitor"
# expect: online, restarts 0 (or 1 if pm2 delete used)

# 2. Startup log: asset_modes 출력 확인
ssh kennyserver "pm2 logs ml-monitor --lines 50 --nostream"
# expect: 'Modes: {BTC-USDT: paper_only, ETH-USDT: normal, SOL-USDT: normal}'

# 3. 다음 4H 경계 (UTC 00/04/08/12/16/20) 후
ssh kennyserver "tail -200 ~/trading/logs/output.log | grep -E 'htf|higher_tf'"
# expect: higher_tf_trend != 0.5

# 4. 이벤트 발생 후 (수 시간 ~ 1일)
ssh kennyserver "python3 -c \"
import json
log = json.load(open('/home/kenny/trading/ml_monitor_log.json'))
events = [e for e in log if e.get('type')=='event']
recent = events[-10:]
for e in recent:
    htf = e['features']['higher_tf_trend']
    mode = e.get('asset_mode', 'unset')
    print(f\\\"{e['detected_at']} {e['asset']:10} htf={htf:.3f} mode={mode}\\\")
\""
# expect: BTC entries show mode='paper_only', htf values not all 0.5
```

## Residual risk

1. **Codex의 P0 게이트 미달**: 배포 후 1-4 시간 내 higher_tf_trend가 여전히 0.5만 나오면 fetch_recent_15m의 페이징 자체가 미작동. → 즉시 rollback (`git revert e0db079` + 재배포).
2. **BTC paper_only 분류 누락**: monitor가 asset_modes를 읽지 못하면 paper_only가 normal로 fallback돼 BTC Telegram이 다시 발송될 수 있음. → 시작 로그의 `Modes:` 출력으로 즉시 감지.
3. **kennyserver 배포 시 PM2 충돌**: deploy_kenny.sh가 pm2 delete → start이므로 그 사이 모니터링 공백 (수 초). 4H 경계와 겹치면 1 이벤트 누락 가능.
4. **GitHub repo가 public이면 코드 노출**: credentials.env, *.pkl은 .gitignore로 차단됐으나 repo 자체의 public/private 설정은 GitHub 측에서 확인 필요.

## Recommended Next Step

순서:
1. **본 result + verdict 확정 후** `bash deploy_kenny.sh` 실행
2. 즉시 PM2 status + startup log 확인
3. 다음 4H 경계 + 1-4시간 후 P0 verification (higher_tf_trend 분포 + asset_mode 보존)
4. 7일 후 BTC 신규 이벤트 수 확인 — Codex 권장 sample count gate (BTC ≥ 20, prefer ≥ 30)
5. 그 시점에 별도 task: `2026-05-XX_post_p0_remeasure.md` (6축 metrics 재측정)
6. 결과에 따라 BTC inverse 채택 / paper-only 유지 / disabled 결정
7. 병행: BTC-specific 재학습 task 별도 발행

## Follow-up tasks to file (placeholder IDs)

- `2026-05-XX_post_p0_remeasure.md` — Codex 6-axis metrics 재측정 (Spearman + WR + avgR + PF + MDD + calibration + distribution)
- `2026-05-XX_event_table_schema_v1.md` — #3
- `2026-05-XX_checklist_to_traderecord.md` — #7
- `2026-05-XX_decision_layer_v1_implementation.md` — #8 (DECISION_LAYER_SPEC 합의 + backtest 후)
- `2026-05-XX_btc_specific_retrain.md` — BTC 전용 모델 + 2024 trend regime
- `2026-05-XX_liquidity_sweep_prototype.md` — SIGNAL_TAXONOMY §7
- `2026-05-XX_phase1_git_policy.md` — Phase-1 amendment: git 도입 정식 명문화

## Verdict
Pending Kenny's review (`agent_handoff/verdicts/2026-05-16_integrated_signal_decision_overhaul.md`).
