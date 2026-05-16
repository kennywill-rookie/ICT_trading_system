# ML Paper Trading 진단 보고서 — 2026-05-11

**범위**: 2026-03-18 ~ 2026-05-10 (54일, 137 청산 거래)
**대상 모델**: `ml_fvg_model.pkl` (XGBoost, 4H FVG, BTC/ETH/SOL)
**분석 범위 주의**: 본 문서는 Structural Edge 전체 시스템이 아니라, 현재 live paper trading에 배포된 **4H FVG ML 필터**만을 분석한다. Structure Shift, Liquidity Sweep, RSI Divergence, 120일선 지지 등 다른 rule-based signal layer는 별도 검증 대상이다.
**핵심 결론**: FVG 이벤트 자체는 live에서 alpha 가능성을 보였으나, 현재 ML 필터는 구현상 feature 수집 버그와 BTC regime mismatch 가능성 때문에 FVG alpha를 제대로 선별하지 못했다.

---

## -1. 본 분석의 올바른 해석

이 보고서의 목적은 "트레이딩 시스템 전체의 성공/실패"를 판정하는 것이 아니다.
목적은 **FVG라는 개별 시그널이 live market에서 어떤 조건하에 alpha를 가지는지 측정**하고, 향후 Structure Shift, Liquidity Sweep, HTF Bias 등 다른 시그널과 결합하기 위한 객관적 데이터를 축적하는 것이다.

따라서 결론은 다음처럼 제한해서 해석해야 한다.

```text
잘못된 해석:
  Structural Edge 전체 시스템이 실패했다.
  FVG는 폐기해야 한다.

올바른 해석:
  현재 4H FVG ML 필터는 실패했다.
  그러나 FVG 이벤트 자체는 HTF alignment, 자산, 방향, regime 조건에 따라 alpha 가능성을 보인다.
  FVG는 조건부 alpha-bearing signal candidate로 지속적으로 측정해야 한다.
```

장기 목표는 다음 흐름이다.

```text
시그널 후보 정의(FVG, Structure Shift, Liquidity Sweep 등)
  → 개별 시그널 백테스트/ML 검증
  → live paper trading
  → 시그널별 time-course 통계 수집
  → FVG + Structure Shift + HTF Bias + Liquidity Sweep 결합 의사결정 레이어 구성
  → ML 반영
  → trading
  → 결과를 계속 데이터셋과 모델에 반영
  → 모델 개선
```

---

## 0. TL;DR

| 항목 | 발견 | 신뢰도 |
|---|---|---|
| **FVG = alpha 여부** | ✅ 유효. FVG 베이스레이트 +21.96R / 53.3% WR / PF 1.32. HTF-aligned가 carrier. | 높음 |
| **버그 #1: htf freeze** | `LOOKBACK_15M=300` → df_4h=19 < `MA_PERIOD_4H=20` → 137/137 이벤트가 fallback `htf=0.5` | 결정적 |
| **잔존 리스크: BTC regime mismatch 가능성** | 학습기간(2025-08~2026-03 횡보) ≠ 라이브(2026-03~05 상승추세). htf 복원해도 BTC top-quintile 20% WR 지속 | 강한 가설 |
| **Drift vs born-broken** | late-onset drift라기보다 초기부터 존재한 train/live mismatch. BTC negative rho는 1일차부터 (2026-03-20) | 강함 |
| **Threshold 0.6454 유효성** | 분포 좁고(std 0.08, train 0.14) 부호 역전. Brier skill **−0.085** (no-model보다 나쁨) | 결정적 |

---

## 1. 라이브 실측 결과 (137 거래)

### 1.1 베이스레이트 (모델 무시, FVG 자체)
```
ALL FVG          n=137  WR=53.3%  totalR=+21.96  avgR=+0.160  PF=1.32
  HTF-aligned    n= 72  WR=59.7%  totalR=+22.60  avgR=+0.314  PF=1.69
  HTF-reverse    n= 65  WR=46.2%  totalR= −0.64  avgR=−0.010  PF=0.98
```

**FVG는 라이브에서도 alpha. HTF 방향 일치가 수익 캐리어** — 백테스트 규칙 재현됨.

### 1.2 자산별 (FVG 자체)
| 자산 | n | WR | totalR | Long R | Short R |
|---|---|---|---|---|---|
| BTC | 48 | 47.9% | **−2.21R** | +3.87 | −6.08 (출혈) |
| ETH | 48 | 58.3% | +14.79R | +8.35 | +6.44 |
| SOL | 41 | 53.7% | +9.38R | +10.38 | −1.00 |

### 1.3 모델 신호 vs 가상매매 (threshold 0.6454)
| 분류 | n | WR | totalR |
|---|---|---|---|
| `is_signal=True` | 34 | 50.0% | **−1.35R** |
| `is_signal=False` (가상) | 103 | 54.4% | **+23.31R** |

**모델이 양수 베이스레이트를 음수로 뒤집는 중.**

### 1.4 Spearman(proba, actual_r)
| 자산 | rho | p |
|---|---|---|
| **BTC** | **−0.473** | **0.0007** |
| ETH | −0.173 | 0.238 |
| SOL | −0.254 | 0.109 |
| ALL | **−0.295** | **0.0005** |

### 1.5 Calibration (라이브 proba quintile → 실제 WR)
**BTC**:
```
bin1 (proba 0.42-0.51)  WR 80%   totalR +8.69  ← BEST
bin5 (proba 0.65-0.73)  WR 30%   totalR −7.09  ← WORST
```
단조 역상관. Brier skill **−0.177** (BTC), **−0.085** (ALL).

---

## 2. 원인 분석

### 2.1 버그 #1: higher_tf_trend Frozen at 0.5

**증거**:
1. 라이브 로그 137/137 이벤트 모두 `higher_tf_trend = 0.5` 정확히
2. 학습 데이터: 747 unique values, [0.015, 0.969], mean 0.48 std 0.28 (연속형)
3. 코드 추적 (`ml_data_pipeline.py:336-343`):
   ```python
   if cutoff_4h >= MA_PERIOD_4H:    # MA_PERIOD_4H = 20
       ... real computation ...
   else:
       features["higher_tf_trend"] = 0.5    # FALLBACK
   ```
4. `ml_live_monitor.py:57`: `LOOKBACK_15M = 300`
   - 300 × 15m = 75h ÷ 4 = **18.75 4H bars** (실측 19)
   - 최신 FVG `cutoff_4h_idx ≈ 16-17 < 20` → fallback 항상 발동
5. 라이브 시뮬 (방금 OKX 호출):
   ```
   BTC df_4h=19, cutoff_4h_idx=16 → htf=0.5
   ETH df_4h=19, cutoff_4h_idx=16 → htf=0.5
   SOL df_4h=19, cutoff_4h_idx=7  → htf=0.5
   ```

**영향 (counterfactual on training data)**:
- 모델 gain importance: **htf=5.43 (1위)** , rsi_14=4.29 (2위)
- 학습 데이터에 `htf=0.5` 강제: proba std **0.141 → 0.082 (−42%)**, Spearman **+0.537 → +0.419**
- 자산별 std 축소: **BTC −47.2%**, ETH −38.6%, SOL −38.9%

### 2.2 시뮬레이션: htf를 정상화하면 어떻게 되는가?

**방법**: 137 라이브 이벤트의 실제 htf를 OKX 8,000 15m bars(500 4H bars)로 재계산 후 모델 재예측.

**htf 분포 회복**: mean 0.51, std **0.27**, range [0.06, 0.97] — 학습 분포(std 0.28)와 일치.

**Proba 분산 회복**:
| | mean | std |
|---|---|---|
| 라이브 (frozen) | 0.582 | 0.081 |
| 시뮬 (real htf) | 0.557 | **0.127** |
| 학습 (정상) | 0.553 | 0.141 |

**Spearman 개선**: ALL −0.295 → **−0.176** (음수는 그대로지만 약화)

**자산별 threshold 0.6454 적용 결과**:
| 자산 | 원본 (frozen) | 시뮬 (real htf) |
|---|---|---|
| BTC | 10건/30%/**−7.09R** | 12건/25%/**−9.21R** ❌ 더 나빠짐 |
| ETH | 16건/56%/+4.04R | 17건/59%/+3.76R |
| SOL | 8건/63%/+1.70R | 9건/56%/+1.45R |
| ALL | 34건/50%/−1.35R | **38건/47%/−4.01R** ❌ |

**Apples-to-apples (각 scheme 자체 top-30%)**:
| 자산 | orig top-30% | aug top-30% | Δ |
|---|---|---|---|
| BTC | 33% WR / −8.84R | 33% WR / **−9.07R** | ≈ 같음 |
| **ETH** | 53% WR / +2.84R | **67% WR / +6.06R** | ✅ +114% |
| SOL | 62% WR / +3.81R | 62% WR / +4.39R | ✅ +15% |

### 2.3 잔존 리스크: BTC Regime Mismatch 가능성

**핵심 잔존 문제**: htf 정상화 시뮬 후에도 **BTC top-quintile = 20% WR / −8.49R**.

**가설**: 학습기간 BTC가 횡보→약세였으나 라이브는 강세 추세. 모델이 "큰 갭 + 높은 RSI = mean-reversion 신호"로 학습했으나 추세장에서는 momentum-continuation으로 작동.

**시뮬 후 BTC calibration**:
```
bin2 (0.45-0.55)  n=9   WR 77.8%  totalR +7.24  ← BEST
bin5 (0.65-0.78)  n=10  WR 20.0%  totalR −8.49  ← 여전히 WORST
```
모델의 BTC top-quintile은 htf와 무관하게 거꾸로 작동.

---

## 3. 검증된 사실 / 부분 검증 / 미해결

### ✅ 확실
- htf가 라이브에서 100% frozen
- 학습 모델의 #1 importance feature가 frozen 상태
- htf 복원 시 proba 분산 거의 회복 (90% 복원)
- ETH/SOL은 htf 복원으로 실질적 개선 (top-30% 기준 ETH +114%)
- FVG 자체는 라이브에서도 양수 alpha (베이스레이트 +21.96R)
- HTF-alignment 규칙 라이브 재현 (aligned +22.60R, reverse −0.64R)
- late-onset drift라기보다 초기부터 존재한 mismatch — BTC negative rho는 1일차부터

### ⚠️ 부분 검증
- BTC 잔존 negative edge → regime bias 가설 유력하나 모델 재학습 없이는 단정 불가
- threshold 0.6454는 학습 정상 분포 기준 → htf 복원 시 라이브 분포가 학습과 다시 일치하므로 의미 회복 가능하나 실측 검증 필요
- htf 정상화 시뮬레이션은 htf-only counterfactual이다. 실제 lookback 패치 후에는 `prev_fvg_same_dir_dist`, `prev_fvg_filled` 등 다른 context feature도 함께 달라질 수 있다.

### ❌ 미해결
- 라이브 코드 패치 후 실제 1-2주 데이터의 검증
- BTC가 htf 정상화 + 임계값 재산정으로도 살아나는지

---

## 4. TO-DO (우선순위)

### 🔴 P0 — 즉시 (코드 패치)
- [ ] **`ml_live_monitor.py`의 15m 데이터 수집을 history-candles paging 방식으로 변경**
  - 현재 단일 `/market/candles` 호출은 실질적으로 300봉 한계가 있으므로, 단순히 `LOOKBACK_15M` 숫자만 800으로 바꾸면 충분하지 않을 수 있음
- [ ] **`ml_live_monitor.py:57` `LOOKBACK_15M` 300 → 800 이상 변경**
  - 800 × 15m = 200h ÷ 4 = 50 4H bars → cutoff ≈ 48 ≫ 20 안전
  - 기대 효과: htf 정상 작동, proba 분산 회복
- [ ] kennyserver 재배포 (`bash deploy_kenny.sh`)
- [ ] 배포 직후 첫 스캔 로그에서 `higher_tf_trend != 0.5` 확인 (검증 단계)
- [ ] LOOKBACK 변경 영향 검증: 다른 피처 (`gap_atr_ratio`, `rsi_14`, `swing_count`, `prev_fvg_same_dir_dist`, `prev_fvg_filled`) 분포가 학습과 일치하는지 sanity check

### 🟠 P1 — 1-2주 (실측 검증 후 결정)
- [ ] 1-2주 라이브 재수집 (htf 정상화 상태)
- [ ] 자산별 Spearman 재측정 — 가설: ETH ≈ 0, SOL ≈ 0, BTC ≈ −0.2 잔존 예상
- [ ] BTC 잔존 negative edge 확인 시:
  - 옵션 A: BTC만 monitor에서 제외
  - 옵션 B: BTC 인버트 (proba < lo_threshold에서만 발송)
  - 옵션 C: BTC 별도 학습 (BTC 전용 모델)
- [ ] threshold 재산정: 라이브 분포 기준 top-30%로 재설정 (현재 fixed 0.6454)
- [ ] Calibration 모니터링: 30건 rolling Brier skill > 0 유지 여부

### 🟡 P2 — 1개월 (모델 개선)
- [ ] 학습 데이터 확장: 2024 이전까지 (1.5년+) 포함하여 다중 regime 학습
- [ ] regime feature 추가 또는 분리 학습 검토 (trending vs ranging)
- [ ] Hold-out test에 별도 추세장 구간 명시적 포함
- [ ] Re-train Phase 2: 새 데이터셋 + 새 라벨링 + Walk-forward CV 정식 운영
- [ ] Structure Shift, Liquidity Sweep, RSI Divergence도 FVG와 동일한 event → feature → label → outcome 데이터셋으로 구축
- [ ] 시그널별 독립 성과 리포트 생성: asset, direction, HTF alignment, regime, rolling window 기준

### 🟢 P3 — 향후 확장
- [ ] FVG ML 검증 후 Structure Shift에도 동일 파이프라인 적용 (기존 계획)
- [ ] htf와 같은 feature freeze 방지 위해 monitor 시작 시 self-test: 첫 스캔에서 모든 피처가 학습 분포 내인지 확인
- [ ] 가상매매 vs 신호 발송 결과 자동 비교 dashboard
- [ ] FVG, Structure Shift, Liquidity Sweep, HTF Bias를 결합한 decision layer 설계
- [ ] 개별 시그널 모델을 ensemble 또는 meta-model의 feature로 반영

---

## 5. 산출 파일 인덱스 (이 분석에 사용된 자산)

| 파일 | 용도 |
|---|---|
| `tools/verify_drift.py` + `results_drift.json` | PSI/KS 분포 드리프트 (training proba vs live proba) |
| `tools/verify_invert.py` + `results_invert.json` | 인버트 전략, permutation test |
| `tools/verify_temporal.py` + `results_temporal.json` | Rolling/cumulative Spearman, born-broken 판별 |
| `tools/diagnose_fvg_and_btc.py` + `results_diagnostic.json` | FVG alpha 베이스레이트, BTC 피처 진단, calibration |
| `tools/simulate_htf_fix.py` + `results_htf_fix.json` | htf 정상화 시뮬레이션 (counterfactual) |
| `logs_kenny/ml_monitor_log.json` | 라이브 137 이벤트 원본 (kennyserver 동기화) |

---

## 6. 면책

- 시뮬레이션은 라이브 entries/exits가 결정적이라는 가정 하에 진행 (사실).
- 137 이벤트는 통계적으로 충분하나 BTC 표본 48건은 신뢰구간이 넓음. 단 Spearman p=0.0007 + permutation p=0.020 + 단조 calibration 3개 독립 신호가 모두 negative 방향으로 일치하여 false positive 가능성 낮음.
- htf freeze는 결정적 (137/137 frozen이 우연일 확률 0).
- 코드 패치는 라이브 트레이딩 환경에 영향. 배포 전 사용자 확인 필요.
