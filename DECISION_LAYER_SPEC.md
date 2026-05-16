# Decision Layer Specification

**Version**: v0.1 (proposal, not yet implemented) · **Date**: 2026-05-16 · **Status**: `planned` · **Author**: Claude (with Codex review pending)

> **Purpose**: 현재 분산된 의사결정 경로(rule signal · 체크리스트 · ML proba · per-asset mode)를 단일 결정 계층으로 통합하는 명세. **코드 작성 전에 문서 합의(Phase-1 verdict cycle) 단계.**

---

## 0. Problem statement

현재 의사결정 경로:
```
rule signals (signal_engine)  ──► signal_log.json  ──► Telegram + dashboard
ML proba (ml_live_monitor)    ──► ml_monitor_log.json ──► Telegram (별도 채널)
체크리스트 verdict (dashboard) ──► localStorage  ──► 휘발성, TradeRecord 미반영
TradeRecord (signal_engine)   ──► trade_log.json  ──► 어떤 시그널/체크리스트로 만들어졌는지 trace 불가
```

**4개 채널이 독립**. 시그널 결합도, alpha-aware 의사결정도, 사후 attribution도 불가.

---

## 1. Design principles

1. **Human-in-the-loop 유지**: 자동매매 아님. 결정 계층은 사람이 보는 단일 결재 화면 + 사후 trace.
2. **Additive, not replacing**: 기존 rule signals, ML proba, 체크리스트는 그대로 두고 위에 결정 계층을 추가.
3. **No new threshold without backtest**: 결합 점수의 cut-off는 backtest로 도출 (`config.json:filters`처럼).
4. **Per-asset mode aware**: BTC paper_only면 결정 계층도 paper로 분류.
5. **Auditable**: 모든 결정 입력(시그널, 체크리스트, ML proba)을 TradeRecord에 snapshot.

---

## 2. Decision record (proposed schema)

```jsonc
{
  "decision_id": "2026-05-16T08:00:00Z_BTC-USDT_long",
  "timestamp": "2026-05-16T08:00:00Z",
  "asset": "BTC-USDT",
  "asset_class": "crypto",
  "asset_mode": "paper_only",          // from ml_monitor_config asset_modes
  "direction": "Long",
  "timeframe": "4H",

  // ── inputs (snapshot at decision time) ──
  "signals": [
    {
      "type": "FVG Entry",
      "source": "rule",                 // rule | ml | manual
      "direction": "Long",
      "confidence": 80,
      "htf_aligned": true,
      "passed_filters": ["skip_htf_neutral", "block_counter_htf", "fvg_min_gap_pct"],
      "reason": "Bullish FVG @ 2026-05-16 04:00",
      "code_ref": "signal_engine.py:602"
    },
    {
      "type": "Structure Shift",
      "source": "rule",
      "direction": "Long",
      "confidence": 85,
      "htf_aligned": true
    }
  ],
  "ml": {
    "model": "ml_fvg_model.pkl",
    "trained_at": "2026-03-18",
    "proba": 0.71,
    "percentile": "top20",
    "bucket": "top20",                 // top20 | top30 | mid | bottom30 | bottom20
    "would_signal_normal": true
  },
  "checklist": {
    "version": "v0.3",
    "categories": {
      "htf_bias": 3,
      "market_structure": 2,
      "entry_criteria": 3,
      "risk_management": 3,
      "psychology": 2
    },
    "total": 13,
    "verdict": "GO"                    // GO | CAUTION | NO_GO
  },
  "regime": {
    "htf_bias": "Bullish",
    "is_trending": true,
    "atr_percentile": 0.55,
    "session": "asia"
  },

  // ── decision ──
  "combined_score": 0.78,              // §3 참조
  "decision": "EXECUTE",               // EXECUTE | PAPER | SKIP | DEFER
  "decision_reason": "rule (FVG + Structure Shift, HTF aligned) + ML top20 + checklist GO",
  "size_multiplier": 1.0,              // 1.0 = normal; 0.3 = inverse small; 0.0 = paper
  "executor": "human_kenny",           // who pressed go

  // ── outcome (populated after close) ──
  "outcome": {
    "entry_price": 64500,
    "exit_price": 66100,
    "exit_reason": "TP",
    "pnl": 1600,
    "actual_r": 1.85,
    "hold_bars": 12,
    "closed_at": "2026-05-17T20:00:00Z"
  }
}
```

---

## 3. Combined score (v0.1 proposal — backtest 필요)

**전적으로 placeholder.** 실제 가중치는 §6 backtest 후 결정.

```text
combined_score =
    0.35 * rule_score             // count + confidence + HTF alignment
  + 0.25 * ml_score               // proba 또는 inverse(proba) per asset_mode
  + 0.30 * checklist_score        // verdict 정량화: GO=1.0, CAUTION=0.5, NO_GO=0
  + 0.10 * regime_score           // 추세장 가산
```

### `ml_score` per asset mode

| asset_mode | source | ml_score 계산 |
|---|---|---|
| normal | model proba | `proba` (∈ [0,1]) |
| paper_only (BTC) | model **inverse** | `1 - proba` if bottom-30 bucket, else 0.5 (중립) |
| disabled | — | 0.5 (기여 0) |

BTC inverse는 paper에서만 적용. 실거래 가중은 maintain criteria 통과 후 별도 task로 결정.

### Decision threshold (placeholder)

```text
combined_score >= 0.70 → EXECUTE (size_multiplier per asset_mode)
0.50 <= score < 0.70  → PAPER
0.30 <= score < 0.50  → DEFER (왔던 거 그대로)
score < 0.30          → SKIP
```

---

## 4. asset_mode → size_multiplier mapping

| asset_mode | size_multiplier | 결정 가능 결과 |
|---|---|---|
| normal | 1.0 | EXECUTE / PAPER / SKIP |
| paper_only | 0.0 | PAPER만 가능 (EXECUTE → PAPER로 강제) |
| disabled | — | DEFER (스캔 자체 안 함) |

inverse가 maintain criteria 통과 시:
- p20 bucket: size_multiplier = 0.25 (Codex 권장 20-30%)
- p30 bucket: size_multiplier = 0.10 (paper-only 유지 권장)

---

## 5. Integration points (코드 변경 영향, 모두 별도 task)

| 변경 위치 | task ID 후보 | 영향 |
|---|---|---|
| `signal_engine.py` Signal 객체에 `decision_id` 부여 | T-DEC-1 | append-only, 기존 schema 호환 |
| `dashboard.py` 체크리스트 → POST `/api/decision` | T-DEC-2 | UI 변경 + 신규 endpoint |
| `ml_live_monitor.py` proba를 decision record에 publish | T-DEC-3 | inverse mode 처리 |
| `decision_log.json` 신규 파일 (cumulative, Hard Escalation) | T-DEC-4 | PHASE1.md 명시 필요 |
| `TradeRecord` dataclass에 `decision_id` FK 추가 | T-DEC-5 | trade_log.json schema 변경 |

---

## 6. Backtest before commit

이 명세를 코드로 옮기기 전, 최소 다음을 검증:

1. **Combined score 가중치 sensitivity**: rule/ml/checklist/regime 비율을 (0.5,0.2,0.2,0.1) ... (0.2,0.4,0.3,0.1) 등 grid로 변동시켜 5년 BTC backtest에서 PF·MDD·trade count 변화 측정.
2. **Threshold 0.70 calibration**: rolling 50-trade 윈도우로 calibration 확인.
3. **BTC inverse contribution**: BTC paper_only 모드에서 ml_score를 1-proba로 바꿨을 때 decision_log에 어떤 비율로 PAPER decision이 생기는지 시뮬레이션.
4. **체크리스트 GO 빈도**: 체크리스트 verdict 분포를 trade_log 사후 분석 (현재 데이터 없음 → §7 선결 과제).

---

## 7. Hard prerequisites (이 명세 코드화 전 반드시)

| 선행 task | 이유 |
|---|---|
| #3 Event table schema 표준화 | `decision_log.json`의 `signals[]`, `outcome` 필드가 event table 스키마와 정합해야 함 |
| #7 Checklist verdict → TradeRecord | 현재 checklist verdict가 localStorage라 backtest 불가 |
| Post-P0 verification (BTC ≥ 20 샘플) | ml_score의 inverse 가중치가 의미 있으려면 P0 후 데이터 |

이 셋이 끝나기 전엔 본 명세는 **proposal 상태 유지**.

---

## 8. Open questions (Codex review에 회부)

1. Combined score는 weighted sum이 맞나 vs decision tree (예: checklist NO_GO이면 무조건 SKIP)?
2. ML inverse는 BTC만 적용해야 하나, 학습 regime이 추세인 자산 전체에 적용해야 하나?
3. Decision record를 신규 파일로 둘지 trade_log.json 확장으로 둘지?
4. UI 결재 화면의 형식: dashboard 탭 추가 vs 별도 페이지?
5. `executor: human_kenny` 외에 자동 결재 모드를 둘지 (현재는 NO 권장)?

---

## Change log

- **2026-05-16** v0.1 — 신규 작성. 명세만, 구현 0. Backtest + Codex review + Kenny verdict 후에야 코드화 시작.
