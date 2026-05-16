# Task — 2026-05-16_integrated_signal_decision_overhaul

## Task ID
2026-05-16_integrated_signal_decision_overhaul

## Target Agent
Claude

## Mode
B (modification)

## Objective
Codex 리뷰(`agent_handoff/discussion/2026-05-16_codex_review_claude_patch_plan.md`)를
Claude의 #1–#9 개선안과 통합하여, 가역적 doc 정비·rename·ML monitor BTC 격리·배포만
이번 회차에서 실행한다. Schema-touching 항목(#3, #7)은 별도 task로 분리한다.

## Background

### 입력 결정 자료
- `Trading_system_flow.md` — 시그널 단일 종합 문서 (FVG/Structure/RSI/MA120/Fundamental Dip만)
- `signal_engine.py:146-152` — `SignalType` enum (Liquidity Sweep는 enum만 존재, detect 부재)
- `dashboard.py:1148-1213` — 15-항목 체크리스트 하드코딩 (verdict 13/9 임계)
- `config.json:31-36` — backtest-derived filter 4종
- `backtest_15m_result.json` — 15m: total_R **−233.37R**, PF **0.59**, 모든 setup 음수
- `backtest_result.json` (Daily) — total_R **+1.76R**, PF 1.03 (Daily만 양수)
- `tools/results_diagnostic.json` — FVG live alpha (베이스레이트 +21.96R), BTC −2.21R
- `tools/results_invert.json` — BTC bottom-30% +8.04R, Spearman −0.473 (p=0.0007)
- `ML_PAPER_TRADING_ANALYSIS_2026-05-11.md` — 137건, htf freeze, BTC regime mismatch
- `agent_handoff/discussion/2026-05-16_codex_review_claude_patch_plan.md` — Codex review

### Codex review 핵심 수정사항
1. P0는 **deploy + verification** task (소스는 이미 `LOOKBACK_15M=800` + paging 적용됨)
2. Sample-count 게이트 (BTC ≥ 20, prefer ≥ 30) — 단순 1-2주 캘린더 기준 부적절
3. Spearman만으로 결정 금지 — WR/avgR/PF/MDD/calibration/distribution 동시 평가
4. BTC inverse는 **p20 + p30 분리 추적** (p20: high conviction small-size, p30: paper-only)
5. Maintain criteria: n≥30, WR≥58%, PF≥1.5, avgR>+0.15R, MDD better, Spearman<0
6. ETH/SOL도 P0 후 재검증 (top-30 PF>1.3, avgR>0)
7. BTC-specific 재학습은 병행 (regime feature 포함, walk-forward)

### Claude 통합 우선순위 (재정렬)
| 권장 | 출처 | 본 회차 | 사유 |
|---:|---|:---:|---|
| #1 Signal Taxonomy 문서 | Claude/Codex | ✅ | 메타작업, 다른 항목 입력 |
| #4 15m rule-based 중단 | Codex | ✅ (deprecate) | bleeding stop |
| #5 ML BTC 분리/제외 | Codex | ✅ (config + monitor 분기) | live alpha leakage |
| P0 deploy + verify | Codex | ✅ | 소스는 적용, 운영은 미검증 |
| #2 Liquidity Sweep 결정 | Codex | ✅ (PLANNED 명시) | 명세 정리 |
| #6 Fundamental Dip 개명 | Codex | ✅ | trivial, name fidelity |
| #9 Decision Layer 명세 | Claude | ✅ (doc only) | 코드 이전 합의 |
| #3 Event table 표준화 | Codex | ❌ → 후속 | trade_log/signal_log schema 변경 (Hard Escalation cumulative log) |
| #7 Checklist→TradeRecord | Claude | ❌ → 후속 | TradeRecord schema + UI 변경 |
| #8 ML proba ↔ decision frame 통합 | Claude | ❌ → 후속 | #9 명세 합의 후 진행 |

## Files / Components In Scope

### 신규 문서
- `SIGNAL_TAXONOMY.md` (신규) — implemented/partial/planned 단일 source-of-truth
- `DECISION_LAYER_SPEC.md` (신규) — 시그널 결합 의사결정 명세 v0.1 (제안)
- `agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md` (이 파일)
- `agent_handoff/results/2026-05-16_integrated_signal_decision_overhaul.md` (예정)
- `.gitignore` (신규)

### 수정
- `signal_engine.py` — SignalType.FUNDAMENTAL_DIP → PRICE_DIP, value/reason 텍스트
- `dashboard.py` — 영향 없음 (체크리스트엔 Fundamental Dip 텍스트 미사용)
- `Trading_system_flow.md` — 시그널표 갱신 (Price Dip), 15m 상태
- `CLAUDE.md` — 신규 문서 hard reference, 시그널 목록 정정
- `ml_monitor_config.json` — `asset_modes` 필드 신설 (BTC=paper_only)
- `ml_live_monitor.py` — `asset_modes` 읽어 Telegram 발송 분기 (BTC paper_only면 발송 차단, 가상매매 추적은 유지)
- `backtest_15m.py` — 헤더에 DEPRECATED 주석 (코드는 보존, 향후 ML feature 학습용)

### 배포
- `deploy_kenny.sh` 실행 — kennyserver에 ml_live_monitor.py + ml_monitor_config.json 동기화
- 배포 직후 `pm2 logs ml-monitor`로 P0 verification

## Out Of Scope
- `trade_log.json`, `signal_log.json` schema 변경 (#3, #7)
- `TradeRecord` dataclass 필드 추가 (#7)
- ML 모델 재학습 (`ml_train.py`, `ml_fvg_model.pkl`)
- `scheduler.py`, `run_scan.py`, `run_scan.sh` 수정 (15m 호출 없음 확인됨)
- `credentials.env` 수정
- Liquidity Sweep detect 함수 구현 (PLANNED만 기록)
- Decision Layer 코드 구현 (#9 doc만)

## Hard Escalation Check (per PHASE1.md)
이 task는 다음 Hard Escalation Items를 건드림:
- `ml_live_monitor.py` (asset_modes 분기 추가)
- `ml_monitor_config.json` (alert threshold 영역 — BTC asset mode = paper_only는 alert behavior 변경)
- `deploy_kenny.sh` 실행 (kennyserver 배포)

- [x] **Yes → human verdict mandatory before any modification**
- [ ] No

**본 task는 Kenny가 본 세션에서 직접 지시하여 작성·실행을 모두 위임함. 사용자 발화가 곧 verdict
authorization으로 작용 (= Phase-1 Verdict Authority §). 결과는 result + verdict 문서로 사후 기록한다.**

## Allowed Actions
1. 신규 문서 작성 (`SIGNAL_TAXONOMY.md`, `DECISION_LAYER_SPEC.md`, `.gitignore`)
2. `signal_engine.py` rename: `FUNDAMENTAL_DIP` → `PRICE_DIP` (메모리 내 enum, log 영향 없음 ☆ 단 과거 signal_log.json의 "Fundamental Dip" 문자열은 그대로 보존됨)
3. `ml_monitor_config.json`에 `asset_modes` 필드 추가 (BTC: paper_only, ETH/SOL: normal)
4. `ml_live_monitor.py`에 asset_modes 분기 로직 추가 (Telegram 발송만 차단; seen_events/log 기록은 유지)
5. `Trading_system_flow.md`, `CLAUDE.md` 갱신
6. `backtest_15m.py` 헤더에 DEPRECATED 주석
7. git init + .gitignore + initial commit + remote add + push
8. `bash deploy_kenny.sh` 실행
9. 배포 후 5분 내 `pm2 logs ml-monitor` 확인 (P0 verification 시작점만)

## Forbidden Actions
1. `trade_log.json` / `signal_log.json` 데이터 mutation
2. `ml_fvg_model.pkl` 교체 또는 재학습
3. `ml_monitor_state.json` mutation (배포 시 deploy 스크립트가 덮어쓰지 않게 확인 필요)
4. threshold_top30/top20 값 변경 (현 0.6454 / 0.6771 유지)
5. `credentials.env` 수정 또는 git 추적
6. `ml_fvg_model.pkl`, `*.csv` 데이터셋 git 추적 (LFS 미사용)
7. PRICE_DIP rename에 따라 과거 log 파일을 "수정" — 과거 데이터는 "Fundamental Dip" 문자열 그대로 유지
8. force-push to main, --no-verify

## Rollback Plan

### Doc-only 변경 (SIGNAL_TAXONOMY.md, DECISION_LAYER_SPEC.md, CLAUDE.md, Trading_system_flow.md)
- `git revert <commit>` 또는 단순 파일 삭제

### `signal_engine.py` rename
- enum 값 "Price Dip" → "Fundamental Dip" 되돌리기 (`git revert`)
- 과거 signal_log.json의 "Fundamental Dip" 문자열은 영향 없음
- enum 이름이 다른 코드에서 참조되지 않음 (grep 결과 자기 모듈 내부만 사용)

### `ml_monitor_config.json` (asset_modes)
- 필드 제거 또는 BTC를 normal로 환원
- 변경 직후 monitor 재시작 필요 (pm2 restart ml-monitor)

### `ml_live_monitor.py` (asset_modes 분기)
- `git revert` → kennyserver 재배포 (deploy_kenny.sh)
- 분기 로직이 차단하는 건 Telegram 발송만, 가상매매 데이터 손실 없음

### kennyserver 배포 실패 시
- 이전 PM2 프로세스로 자동 재시작 (deploy 스크립트가 pm2 delete → start이므로 실패 시 수동 복구)
- 직전 commit hash 기억 필수 → `ssh kennyserver "cd ~/trading && git log -1"` 또는 로컬에서 이전 파일 SCP

### Git 초기화 실패 시
- `.git/` 삭제 후 재시도
- GitHub 푸시 실패 시 SSH 키/PAT 확인

## Expected Output
1. 신규 문서 4종 (`SIGNAL_TAXONOMY.md`, `DECISION_LAYER_SPEC.md`, `.gitignore`, task/result 본 파일)
2. 기존 문서 갱신 3종 (`CLAUDE.md`, `Trading_system_flow.md`, `agent_handoff/templates` 영향 없음)
3. 코드 수정 3종 (`signal_engine.py`, `ml_monitor_config.json`, `ml_live_monitor.py`, `backtest_15m.py` 헤더)
4. Git 초기 commit 시리즈 + GitHub push
5. kennyserver 배포 완료 + PM2 status OK
6. P0 verification 시작 로그 확인 (`higher_tf_trend != 0.5` 첫 등장 timestamp 기록)
7. `agent_handoff/results/2026-05-16_integrated_signal_decision_overhaul.md`

## Verification Required

### 코드 변경 확인
```bash
# rename 일관성
grep -rn "FUNDAMENTAL_DIP\|Fundamental Dip" *.py *.json *.md
# expect: signal_engine.py = PRICE_DIP / "Price Dip" 만, 과거 log 파일 외엔 0

# asset_modes 작동 확인
grep -n "asset_modes" ml_monitor_config.json ml_live_monitor.py
# expect: 양쪽 모두 정의/참조

# 15m deprecated
head -20 backtest_15m.py
# expect: DEPRECATED 주석
```

### Git 상태
```bash
git remote -v   # origin = https://github.com/kennywill-rookie/ICT_trading_system.git
git status      # clean
git log --oneline | head -10
```

### kennyserver 배포 후 P0 verification (Codex 권장)
```bash
ssh kennyserver "pm2 status ml-monitor"
ssh kennyserver "tail -100 ~/trading/logs/output.log | grep -i 'higher_tf\|htf'"
# 첫 4H 경계 (00/04/08/12/16/20 UTC) 도래 후:
ssh kennyserver "cat ~/trading/ml_monitor_log.json | python3 -c \"
import json,sys
log = json.load(sys.stdin)
events = [e for e in log if e.get('type')=='event']
recent = events[-5:]
for e in recent:
    print(e['detected_at'], e['asset'], 'htf=', e['features']['higher_tf_trend'])
\""
# expect: higher_tf_trend != 0.5 (배포 직후 즉시 확인은 새 4H 경계 전이므로 1-4시간 대기 필요)
```

### Codex P0 완료 게이트 (3-7일 내 재확인)
```text
new FVG events >= 5
higher_tf_trend unique values not only [0.5]
higher_tf_trend across non-trivial 0-1 range
proba std recovers vs frozen period (target std > 0.10)
```

## Escalation Rules
다음 시 NEEDS_HUMAN 반환:
- `deploy_kenny.sh` 실행 실패 (SSH/PM2 에러)
- 배포 후 `ml_monitor_state.json`이 빈 파일로 덮어써짐 (open positions 손실)
- Git push 실패 (인증 실패, 충돌)
- `signal_engine.py` rename 후 import 또는 참조 깨짐

## Follow-up Tasks (별도 task 필수)
- `2026-05-XX_event_table_schema_v1.md` (#3): trade_log/signal_log 통일 스키마 (asset, direction, htf_alignment, regime, outcome R, hold_bars, model_score)
- `2026-05-XX_checklist_to_traderecord.md` (#7): 체크리스트 verdict + snapshot을 TradeRecord에 영구화
- `2026-05-XX_decision_layer_v1_implementation.md` (#8): DECISION_LAYER_SPEC.md 합의 후 코드 구현
- `2026-05-XX_btc_specific_retrain.md`: BTC 전용 모델 + regime feature + walk-forward
- `2026-05-XX_post_p0_remeasure.md`: P0 후 1-2주, BTC ≥ 20 sample 누적 시 Codex maintain criteria 6-axis 측정
- `2026-05-XX_liquidity_sweep_prototype.md`: detect 함수 프로토타입 + 체크리스트 사용 통계 분석
