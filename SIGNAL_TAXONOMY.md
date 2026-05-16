# ⚡ Structural Edge — Signal Taxonomy

**Version**: v0.4 · **Updated**: 2026-05-16 · **Status**: source-of-truth (replaces scattered references)

> **Single source-of-truth for all signal definitions, states, and asset routing.**
> Canonical code: `signal_engine.py:SignalType` (line 146).
> Any new signal MUST update both this file AND the enum, with a state value below.

---

## State legend

| State | Meaning |
|---|---|
| `implemented` | Detect + scan + filter all live; results in `signal_log.json`. |
| `partial` | Detect or scan exists but is gated/limited (per-asset, mode, etc.); see notes. |
| `planned` | Specified or referenced (UI, enum) but no detect/scan path. Must not be presented to user as active. |
| `deprecated` | Was implemented; deliberately turned off; code preserved for research. |

---

## 1. Rule-based entry signals (`signal_engine.py`)

| # | Signal | State | Direction | Asset class | Timeframe | Code | Notes |
|--:|---|:---:|:---:|---|---|---|---|
| 1 | **Structure Shift** | `implemented` | L / S | crypto, etf, stock, bond | 4H (crypto) · 1D (others) | `signal_engine.py:422-464` · `:556-600` | Bond은 이 시그널만 유지. HTF aligned 시 +10 conf. |
| 2 | **FVG Entry** | `implemented` | L / S | crypto, etf, stock | 4H · 1D | `signal_engine.py:352-374` · `:602-643` | HTF aligned + `fvg_min_gap_pct ≥ 0.002` 필터. |
| 3 | **RSI Divergence** | `implemented` | L only | crypto, etf, stock | 4H · 1D | `signal_engine.py:377-419` · `:645-683` | Short는 `disable_rsi_divergence_short=true`로 영구 차단 (backtest 결과). |
| 4 | **MA120 Support** | `implemented` | L only | ETF only | 1D | `signal_engine.py:685-707` | 120일선 ±3% 근접 + 상향 돌파. |
| 5 | **Price Dip** (구 Fundamental Dip) | `implemented` | L only | stock only | 1D | `signal_engine.py:709-731` | 순수 가격 트리거 (-10% from 20d high). **Fundamental/news 필터 미구현** — 사용자 수동 검증. 2026-05-16 rename. |
| 6 | **Liquidity Sweep** | `planned` | — | — | — | `signal_engine.py:147` enum only | Enum만 존재. Detect 함수 부재. 체크리스트 (`dashboard.py:1156`)엔 항목 있음. **결정 프로토콜 § 참조**. |
| 7 | **Order Block** | `planned` | — | — | — | (코드 없음) | CLAUDE.md/체크리스트엔 언급. 정식 명세·구현 없음. |

### HTF Bias (meta-signal, 게이트)

`signal_engine.py:467-489` — 주봉 close vs MA20 + 5봉 trend% + RSI.
States: `Strong Bullish / Bullish / Neutral / Bearish / Strong Bearish`.
**진입 시그널이 아니라 다른 시그널의 진입 게이트.**

---

## 2. 자산 × 시그널 매트릭스

| 시그널 \ 자산        | crypto (4H) | ETF (1D) | stock (1D) | bond (1D) |
|----------------------|:-----------:|:--------:|:----------:|:---------:|
| Structure Shift      | ✅ L / S    | ✅ L     | ✅ L       | ✅ L only |
| FVG Entry            | ✅ L / S    | ✅ L     | ✅ L       | ❌        |
| RSI Divergence       | ✅ L only   | ✅ L     | ✅ L       | ❌        |
| MA120 Support        | ❌          | ✅ L     | ❌         | ❌        |
| Price Dip            | ❌          | ❌       | ✅ L       | ❌        |
| Liquidity Sweep      | (planned)   | (planned)| (planned)  | (planned) |
| Order Block          | (planned)   | (planned)| (planned)  | (planned) |

L=Long, S=Short. ETF/stock/bond는 `long_only` (signal_engine.py:554) 강제.

---

## 3. Filter gates (`config.json:filters`)

Backtest-derived hard gates. 모든 시그널이 생성 후 통과해야 발화.

| Gate | Default | 소스 | 설명 |
|---|---|---|---|
| `skip_htf_neutral` | `true` | backtest 5y BTC | HTF Bias = Neutral이면 자산 전체 스킵 |
| `block_counter_htf` | `true` | backtest 5y BTC | Strong-bias 역방향 진입 차단 |
| `fvg_min_gap_pct` | `0.002` | 15m cross check | 수수료 대비 SL 거리 확보 (FVG only) |
| `disable_rsi_divergence_short` | `true` | backtest | RSI Div Short은 알파 없음 |
| `min_rr_ratio` | `2.0` | spec | 최소 손익비 (`config.json:4`) |
| `long_only` (asset-class) | etf·stock·bond | spec | Short 차단 |
| bond Structure Shift only | hard-coded | spec | `signal_engine.py:763` |

---

## 4. ML layer (`ml_data_pipeline.py` + `ml_live_monitor.py`)

| 항목 | 값 |
|---|---|
| Scope | **4H FVG only** (rule-layer #2의 부분집합) |
| Assets | BTC-USDT, ETH-USDT, SOL-USDT |
| Features | 20개 (gap_pct, gap_atr_ratio, trend_48bars, swing_count, dist_to_swing_*, higher_tf_trend, rsi_14, rsi_delta_16bars, bb_position, vol_ratio, vol_surge_15m, prev_fvg_*, impulse_purity, consecutive_dir_bars, hour_of_day, day_of_week, atr_percentile, is_trending) |
| Label | SL/TP 선터치 (`label_rr15`, RR=1.5) |
| Model | XGBoost (`ml_fvg_model.pkl`, 2026-03-18 train, 593 samples) |
| Threshold | `top30=0.6454`, `top20=0.6771` |
| State | `partial` — paper trading only, rule-layer와 미통합 |

### Per-asset mode (2026-05-16 추가, `ml_monitor_config.json:asset_modes`)

| Asset | Mode | 사유 |
|---|---|---|
| BTC-USDT | `paper_only` | Spearman −0.473, top-quintile 30% WR (Codex 2026-05-16 review). post-P0 maintain criteria 만족 시까지 격리. |
| ETH-USDT | `normal` | htf 복원만으로 회복 예상. post-P0 재검증 필요. |
| SOL-USDT | `normal` | 동상. |

Mode semantics:
- `normal` = scan + Telegram + paper-track
- `paper_only` = scan + paper-track, **NO Telegram**
- `disabled` = skip the asset entirely

---

## 5. Decision layer (시그널 결합)

| 항목 | State |
|---|---|
| 시그널 OR 발화 | `implemented` — 현재 각 시그널이 독립적으로 signal_log에 기록 |
| 시그널 결합 (FVG + Structure Shift + Liquidity Sweep + HTF) | `planned` — 명세는 `DECISION_LAYER_SPEC.md` 참조 |
| 체크리스트 (15-항목, `dashboard.py:1148`) | `implemented` (UI) — 단 verdict가 TradeRecord에 영구화되지 않음 |
| ML proba ↔ 체크리스트 통합 | `planned` |

---

## 6. Deprecated

| 항목 | Reason | 결정일 |
|---|---|---|
| **15m rule-based forward backtest** (`backtest_15m.py`) | total_R −233.37R / PF 0.59, 모든 setup 음수 | 2026-05-16 |

---

## 7. Liquidity Sweep 결정 프로토콜

**현 상태**: SignalType enum 등록, detect 함수 부재, 체크리스트 항목 존재.

단정적 제거/구현 결정 전 2단계 검증:

1. **체크리스트 사용 통계**: 최근 60일 trade_log에서 "Liquidity sweep completed" 항목이 체크된 비율 측정. <10%면 제거 고려, ≥30%면 구현 우선.
2. **30봉 sweep prototype**: swing high/low를 wick으로 돌파 후 close 회수하는 단순 detect를 backtest에 한 번 돌리고 setup-level alpha(per-asset, per-direction) 측정.

두 결과를 모두 모은 뒤 `implemented`로 promote할지 `deprecated`로 close할지 결정. **그 전엔 `planned` 상태 유지.**

ICT 방법론에서 Liquidity Sweep ↔ FVG는 핵심 쌍이라 가벼운 단정 제거는 위험.

---

## 8. 다음 회차 작업 (별도 task 필수)

| 항목 | 영향 범위 |
|---|---|
| Event table schema 표준화 (#3) | `trade_log.json` / `signal_log.json` (Hard Escalation) |
| Checklist verdict → TradeRecord 영구화 (#7) | `TradeRecord` dataclass + UI |
| ML proba ↔ decision frame 통합 (#8) | `DECISION_LAYER_SPEC.md` 합의 선행 |
| BTC-specific 재학습 | `ml_train.py` + 2024 trend regime 데이터 추가 |
| Post-P0 remeasure (BTC ≥ 20 샘플) | `tools/` 진단 재실행 |
| Liquidity Sweep prototype | 위 §7 결정 프로토콜 |

---

## Change log

- **2026-05-16** v0.4 — 신규 작성. Trading_system_flow.md + CLAUDE.md + dashboard.py에 분산돼 있던 시그널 정의를 통합. Liquidity Sweep을 `planned`로 명시. Order Block 명시. 15m을 `deprecated`로. Fundamental Dip → Price Dip rename. ML asset_modes 도입.
