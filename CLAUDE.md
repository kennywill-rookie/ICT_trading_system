# ⚡ Structural Edge Trading System v0.3

**확률 기반 구조적 대응 매매 시스템**

---

## ⚠️ Collaboration Framework (MUST READ FIRST)

Before any collaborative work or file modification, you MUST read and follow:

- `AGENT_COLLABORATION_FRAMEWORK.md` — overall framework
- `agent_handoff/PHASE1.md` — currently active phase agreement (started 2026-05-15)

**Hard rules** (non-negotiable in Phase-1):

1. Before modifying any file, check whether it falls under `PHASE1.md` § Hard Escalation Items (e.g., `credentials.env`, `ml_live_monitor.py`, `scheduler.py`, `run_scan.*`, `deploy_kenny.sh`, model artifacts, `trade_log.json`, `signal_log.json`, OKX/live order code, kennyserver deployment). If yes, you MUST write a Task document under `agent_handoff/tasks/` and request Kenny's verdict before proceeding.
2. Every "change" as defined in `PHASE1.md` § Change Definition requires the full `task → result → verdict` cycle. Discussion appends, log files, and trivial typo/format fixes are exempt.
3. Mode A (read-only thinking) requires no task. Transition to Mode B (modification) must be declared by Kenny and started with a task file.
4. If an ad-hoc agent suggestion conflicts with the framework, pause and ask Kenny.

---

## 🏗 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    📊 데이터 소스                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ Yahoo    │  │ OKX      │  │ Trading  │  │ 뉴스 RSS │          │
│  │ Finance  │  │ API      │  │ View     │  │ (향후)   │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘         │
│       └──────────────┴──────────────┴──────────────┘            │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                    ⚙️ 신호 감지 엔진 (signal_engine.py)          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Structure    │  │ FVG          │  │ RSI          │          │
│  │ Shift 감지    │  │ 감지         │  │ Divergence   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Liquidity    │  │ 120일선      │  │ Fundamental  │          │
│  │ Sweep 감지   │  │ 지지/저항    │  │ Dip 감지     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                    📋 의사결정 레이어                              │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │ 15항목 체크리스트     │  │ 리스크 계산기         │            │
│  │ (HTF Bias, 구조,     │  │ (4.5% Fixed Loss,   │            │
│  │  진입, 리스크, 심리)  │  │  R:R ≥ 1:2)         │            │
│  └──────────────────────┘  └──────────────────────┘            │
└────────────────────────────┬────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 📱 Telegram  │  │ 📊 Dashboard │  │ 📝 Trade Log │
│ 알림 전송    │  │ (React)      │  │ JSON 저장    │
│              │  │ 성과 추적    │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
```

## 📁 파일 구조

```
trading-system/
├── signal_engine.py      # 핵심 신호 감지 엔진 (데이터 수집, TA, 신호, 거래 관리)
├── scheduler.py          # 자동 스캔 스케줄러
├── config.json           # 설정 파일 (워치리스트, 파라미터)
├── credentials.env       # API 키, 텔레그램 토큰 (git 제외)
├── trading-dashboard.jsx # React 대시보드 (Claude artifact)
├── .gitignore            # 시크릿/로그 파일 제외
├── trade_log.json        # 거래 기록 (자동 생성)
├── signal_log.json       # 신호 로그 (자동 생성)
└── CLAUDE.md             # 이 파일
```

## 🚀 빠른 시작

### 1. 패키지 설치

```bash
pip install yfinance pandas numpy ta requests schedule --break-system-packages
```

### 2. 설정

`config.json` 파일에서 워치리스트와 파라미터를 수정합니다.

### 3. 수동 스캔 실행

```bash
python signal_engine.py
```

### 4. 자동 스케줄러 시작

```bash
python scheduler.py
```

### 5. 시크릿 설정

`credentials.env` 파일에 API 키와 텔레그램 토큰을 설정합니다:

```env
OKX_API_KEY="your_okx_api_key"
OKX_SECRET_KEY="your_okx_secret"
OKX_PASSPHRASE="your_okx_passphrase"
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"
```

### 6. 텔레그램 알림 설정 (선택)

1. Telegram에서 @BotFather를 찾아 `/newbot` 명령으로 봇 생성
2. 받은 토큰을 `credentials.env`의 `TELEGRAM_BOT_TOKEN`에 입력
3. 봇에게 `/start` 메시지 전송
4. `https://api.telegram.org/bot{TOKEN}/getUpdates`에서 `chat_id` 확인
5. `credentials.env`의 `TELEGRAM_CHAT_ID`에 입력
6. `config.json`의 `telegram.enabled`를 `true`로 변경

## 📊 대시보드 (React)

`trading-dashboard.jsx` 파일은 Claude에서 직접 렌더링됩니다.

### 대시보드 탭 구성:

| 탭 | 기능 |
|---|---|
| 📊 시황 & 신호 | HTF Bias 설정, 활성 신호 목록, 자산배분 |
| ✅ 진입 체크리스트 | 15항목 체크리스트 (6개 카테고리) |
| 📝 거래 기록 | 포지션 기록/청산, 리스크 자동 계산 |
| 📈 성과 분석 | 누적 P&L, 일별 손익, 승률 추이 |
| 🧠 루틴 & 심리 | 일일 루틴, 심리 복기, 5가지 규칙 |
| 📖 전략 규칙 | 자산별 진입 규칙, 핵심 이론 레퍼런스 |

## 📐 트레이딩 규칙 요약

### 자산별 전략

| 자산 | 진입 조건 | 포지션 크기 |
|---|---|---|
| 암호화폐 선물 | FVG + Order Block + 15분 Entry | 소액, Seed 4.5% 고정손실 |
| 암호화폐 현물 | Structure Shift 확인 후 분할매수 | 목돈 |
| ETF | 120일선 지지, 추세추종 | 중기 |
| 개별주식 | Fundamental 견고 + 뉴스 하락 | 분할매수 |
| 채권 | Structure Shift 발생 시에만 | 소량 |

### 핵심 판단 기준

1. **HTF Bias**: 주봉 기준 방향성 → Bull이면 Short 금지
2. **Liquidity Sweep vs Structure Shift**: 가장 먼저 판단
3. **FVG**: 1H 이상에서 완성 필수
4. **손익비**: 최소 1:2 이상
5. **고정 손실**: Seed의 4.5% (₩450,000)

### 회피 조건
- 큰 변동성 직후
- RSI > 80 또는 < 20
- 뉴스 이벤트 직전
- 50:50 상황 (일방적 논리 없을 때)

## 🧠 ML 전략 개발 철학

이 시스템은 특정 단일 시그널, 예를 들어 FVG 하나만으로 완성되는 자동매매 시스템이 아니다.
목표는 여러 구조적 시그널을 개별적으로 검증하고, 자산·방향·시장 regime에 따라 alpha edge가 어떻게 변하는지 장기적으로 측정한 뒤, 이를 결합 의사결정 레이어와 ML 모델에 반영하는 것이다.

### 핵심 연구 질문

1. **개별 시그널은 alpha를 가지는가?**
   - FVG, Structure Shift, Liquidity Sweep, RSI Divergence, HTF Bias 등 각 시그널을 독립 이벤트로 기록한다.
   - 신호 발생 여부와 실제 진입 여부를 분리하고, 발생한 모든 이벤트의 outcome을 추적한다.

2. **alpha는 시장 상황에 따라 어떻게 변하는가?**
   - trend/range, high/low volatility, risk-on/risk-off, funding, macro/news proxy 등 regime feature를 함께 기록한다.
   - 고정 threshold보다 regime-aware threshold와 rolling calibration을 우선한다.

3. **alpha는 자산별·방향별로 어떻게 다른가?**
   - BTC, ETH, SOL, ETF, stock, bond 등 자산별 통계를 분리한다.
   - Long/Short 성과를 분리하고, HTF-aligned/reverse 여부를 항상 함께 본다.

### 권장 개발 흐름

```
트레이딩 전략에 따른 시그널 후보 정의
  → 개별 시그널 백테스트 및 ML 이벤트 데이터셋 생성
  → live paper trading
  → 시그널별 time-course 통계 수집
  → FVG + Structure Shift + HTF Bias + Liquidity Sweep 결합 의사결정 레이어 구성
  → ML 모델 반영
  → 소액 실전 / trading
  → 결과를 계속 데이터셋에 반영
  → 모델·threshold·decision layer 개선
```

### 데이터 설계 원칙

모든 시그널은 장기적으로 동일한 형태의 event table에 기록되어야 한다.

| 필드 | 설명 |
|---|---|
| `signal_type` | FVG, Structure Shift, Liquidity Sweep, RSI Divergence 등 |
| `asset` | BTC, ETH, SOL, ETF, stock 등 |
| `direction` | Long / Short |
| `timeframe` | 15m, 4H, 1D, 1W 등 |
| `htf_bias` | Bullish, Bearish, Neutral 및 aligned/reverse 여부 |
| `signal_features` | 각 시그널 고유 feature |
| `regime_features` | trend, volatility, funding, session, sentiment proxy 등 |
| `entry_plan` | entry, SL, TP, RR, timeout |
| `outcome` | WIN/LOSS/TIMEOUT, actual R, hold bars |
| `model_score` | 모델 확률, threshold, calibration bucket |

### FVG ML Monitor 해석 주의

현재 `ml_live_monitor.py`와 `ml_fvg_model.pkl`은 전체 Structural Edge 시스템이 아니라 **4H FVG 이벤트만을 대상으로 한 ML paper trading 실험**이다.
따라서 FVG ML 성과를 Structure Shift, Liquidity Sweep, RSI Divergence, 120일선 지지 등 전체 rule-based signal layer의 성과로 일반화하면 안 된다.

2026-05-11 기준 FVG live 분석의 핵심 해석은 다음과 같다.

- FVG 이벤트 자체는 live에서 양수 alpha 가능성을 보였다.
- alpha는 HTF alignment, 자산, 방향, 시장 regime에 따라 크게 달라진다.
- ML 필터의 실패는 FVG 시그널 폐기를 의미하지 않는다.
- feature 수집 버그는 alpha 측정 장비의 오류에 가깝기 때문에 먼저 수정해야 한다.
- 이후 Structure Shift, Liquidity Sweep 등도 동일한 event → feature → label → outcome 흐름으로 검증한다.

## 🔧 향후 확장 계획

1. **TradingView Webhook 연동**: Pine Script 알림 → 자동 신호 수신
2. **뉴스 감정분석**: RSS + LLM으로 개별주식 뉴스 분석 자동화
3. **OKX 자동매매 API**: 자동 주문 실행 (credentials.env 키 활용)
4. **Next.js 웹 대시보드**: 독립 웹앱으로 배포
5. **백테스팅 엔진**: 과거 데이터로 전략 검증
6. **Wedge Pattern 감지**: 쐐기형 패턴 자동 감지

## ⚠️ 면책 조항

이 시스템은 트레이딩 의사결정을 **보조**하는 도구입니다.
모든 투자 판단의 최종 책임은 사용자 본인에게 있습니다.
