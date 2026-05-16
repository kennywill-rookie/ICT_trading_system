"""
⚡ Structural Edge Trading System - Signal Engine v0.3
=====================================================
확률 기반 구조적 대응 매매 시스템

데이터 소스: Yahoo Finance (yfinance), OKX REST API
신호 감지: Liquidity Sweep, Structure Shift, FVG, RSI Divergence
알림: Telegram Bot, 콘솔 출력

사용법:
  pip install yfinance pandas ta requests schedule --break-system-packages
  python signal_engine.py

설정:
  config.json - 워치리스트, 파라미터
  credentials.env - API 키, 텔레그램 토큰 (시크릿)
"""

import json
import os
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import warnings
warnings.filterwarnings('ignore')


def load_env(filepath="credentials.env"):
    """credentials.env 파일에서 환경변수 로드"""
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)


load_env()


def deep_merge(base: dict, override: dict) -> dict:
    """nested dict를 재귀적으로 병합"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    print("⚠️  yfinance/pandas/numpy 설치 필요: pip install yfinance pandas numpy --break-system-packages")

try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False
    print("⚠️  ta 라이브러리 설치 필요: pip install ta --break-system-packages")

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("ℹ️  requests 미설치 - OKX 데이터 사용 불가, yfinance로 대체합니다")


# ═══════════════════════════════════════
# 설정 (Config)
# ═══════════════════════════════════════

DEFAULT_CONFIG = {
    "seed_capital": 1000000,          # 시드 자금 (원)
    "max_risk_per_trade_pct": 4.5,     # 트레이드당 최대 손실 %
    "min_rr_ratio": 2.0,               # 최소 손익비

    "watchlist": {
        "crypto": ["BTC-USD", "ETH-USD"],
        "etf": ["TQQQ", "SOXL", "QQQ", "SPY", "TLT"],
        "stocks": ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"],
        "bonds": ["IEF", "SHY"]
    },

    "crypto_okx_symbols": ["BTC/USDT", "ETH/USDT"],

    "timeframes": {
        "htf": "1wk",       # 상위 시간대 (주봉)
        "daily": "1d",       # 일봉
        "h4": "4h",          # 4시간 (OKX용)
        "entry": "15m"       # 진입 (향후 사용)
    },

    "indicators": {
        "rsi_period": 14,
        "rsi_overbought": 80,
        "rsi_oversold": 20,
        "ma_120": 120,
        "ma_60": 60,
        "bollinger_period": 20,
        "bollinger_std": 2
    },

    "telegram": {
        "enabled": False
    },

    "filters": {
        "skip_htf_neutral": False,
        "block_counter_htf": False,
        "fvg_min_gap_pct": 0,
        "disable_rsi_divergence_short": False,
    },

    "execution": {
        "slippage_pct": 0,
        "fee_pct": 0,
        "entry_delay_bars": 0,
        "fvg_only": False,
        "use_trailing_exit": False,
        "tp1_partial_pct": 0.5,
    },

    "trade_log_file": "trade_log.json",
    "signal_log_file": "signal_log.json"
}


# ═══════════════════════════════════════
# 데이터 모델
# ═══════════════════════════════════════

class SignalType(Enum):
    LIQUIDITY_SWEEP = "Liquidity Sweep"
    STRUCTURE_SHIFT = "Structure Shift"
    FVG_ENTRY = "FVG Entry"
    RSI_DIVERGENCE = "RSI Divergence"
    MA120_SUPPORT = "120일선 지지"
    PRICE_DIP = "Price Dip"

class Direction(Enum):
    LONG = "Long"
    SHORT = "Short"
    NEUTRAL = "Neutral"

@dataclass
class Signal:
    timestamp: str
    asset: str
    asset_type: str           # crypto_futures, crypto_spot, etf, stock, bond
    signal_type: str
    direction: str
    timeframe: str
    confidence: float         # 0-100
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    reason: str
    checklist_passed: int     # 체크리스트 통과 항목 수
    htf_bias: str
    status: str = "PENDING"

@dataclass
class TradeRecord:
    id: str
    timestamp: str
    asset: str
    asset_type: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    size: float
    leverage: float
    reason: str
    psychology: str
    status: str = "OPEN"
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    r_multiple: Optional[float] = None
    closed_at: Optional[str] = None


# ═══════════════════════════════════════
# 데이터 수집 (Data Fetcher)
# ═══════════════════════════════════════

class DataFetcher:
    """Yahoo Finance 및 OKX REST API에서 가격 데이터 수집"""

    @staticmethod
    def fetch_yahoo(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        """Yahoo Finance에서 데이터 가져오기"""
        if not HAS_YFINANCE:
            return pd.DataFrame()
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                print(f"  ⚠️ {symbol}: 데이터 없음")
                return df
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            print(f"  ❌ {symbol} 데이터 수집 실패: {e}")
            return pd.DataFrame()

    # OKX bar 포맷 매핑 (config timeframe → OKX bar 파라미터)
    OKX_BAR_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "4h": "4H", "1d": "1D", "1D": "1D",
        "1wk": "1W", "1W": "1W",
    }

    @staticmethod
    def fetch_okx(symbol: str, timeframe: str = "1d", limit: int = 300):
        """OKX REST API에서 암호화폐 OHLCV 데이터 가져오기 (인증 불필요)"""
        if not HAS_REQUESTS or not HAS_YFINANCE:
            return None

        bar = DataFetcher.OKX_BAR_MAP.get(timeframe, "1D")
        # OKX instId 포맷: BTC-USDT (슬래시 → 하이픈)
        inst_id = symbol.replace("/", "-")

        try:
            all_data = []
            after = ""
            # 최근 데이터는 /market/candles (최대 300), 과거는 /market/history-candles (최대 100)
            per_page = min(limit, 300)
            url = "https://www.okx.com/api/v5/market/candles"

            params = {"instId": inst_id, "bar": bar, "limit": str(per_page)}
            resp = _requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != "0":
                print(f"  ❌ {symbol} OKX API 에러: {body.get('msg')}")
                return None
            all_data.extend(body["data"])

            # 추가 과거 데이터가 필요하면 history-candles로 페이징
            remaining = limit - len(all_data)
            if remaining > 0 and all_data:
                url_hist = "https://www.okx.com/api/v5/market/history-candles"
                after = all_data[-1][0]  # 마지막 타임스탬프
                while remaining > 0:
                    page_size = min(remaining, 100)
                    params_hist = {"instId": inst_id, "bar": bar, "limit": str(page_size), "after": after}
                    resp = _requests.get(url_hist, params=params_hist, timeout=10)
                    resp.raise_for_status()
                    body = resp.json()
                    if body.get("code") != "0" or not body["data"]:
                        break
                    all_data.extend(body["data"])
                    after = body["data"][-1][0]
                    remaining -= len(body["data"])
                    time.sleep(0.05)  # rate limit 대응

            if not all_data:
                return None

            # OKX 응답: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            df = pd.DataFrame(all_data, columns=[
                "timestamp", "open", "high", "low", "close",
                "volume", "volCcy", "volCcyQuote", "confirm"
            ])
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df = df.sort_values("timestamp").set_index("timestamp")
            return df

        except Exception as e:
            print(f"  ❌ {symbol} OKX 데이터 실패: {e}")
            return None


# ═══════════════════════════════════════
# 기술적 분석 (Technical Analysis)
# ═══════════════════════════════════════

class TechnicalAnalysis:
    """기술적 지표 계산"""

    @staticmethod
    def add_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
        """주요 지표 추가"""
        if df.empty or not HAS_TA:
            return df

        ind = config.get("indicators", DEFAULT_CONFIG["indicators"])

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=ind["rsi_period"]).rsi()

        # 볼린저 밴드
        bb = ta.volatility.BollingerBands(df["close"], window=ind["bollinger_period"], window_dev=ind["bollinger_std"])
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"] = bb.bollinger_mavg()
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

        # 이동평균
        if len(df) >= ind["ma_120"]:
            df["ma_120"] = df["close"].rolling(window=ind["ma_120"]).mean()
        if len(df) >= ind["ma_60"]:
            df["ma_60"] = df["close"].rolling(window=ind["ma_60"]).mean()
        df["ma_20"] = df["close"].rolling(window=20).mean()

        # ATR (Average True Range)
        df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

        # 볼륨 SMA
        df["vol_sma"] = df["volume"].rolling(window=20).mean()
        df["vol_ratio"] = df["volume"] / df["vol_sma"]

        return df

    @staticmethod
    def detect_swing_points(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
        """스윙 고점/저점 탐지 (유동성 풀 식별용)"""
        df["swing_high"] = False
        df["swing_low"] = False

        for i in range(window, len(df) - window):
            high_slice = df["high"].iloc[i - window:i + window + 1]
            low_slice = df["low"].iloc[i - window:i + window + 1]

            if df["high"].iloc[i] == high_slice.max():
                df.iloc[i, df.columns.get_loc("swing_high")] = True
            if df["low"].iloc[i] == low_slice.min():
                df.iloc[i, df.columns.get_loc("swing_low")] = True

        return df

    @staticmethod
    def detect_fvg(df: pd.DataFrame) -> list:
        """Fair Value Gap (FVG) 탐지"""
        fvgs = []
        for i in range(2, len(df)):
            # Bullish FVG: 3번째 캔들의 low > 1번째 캔들의 high
            if df["low"].iloc[i] > df["high"].iloc[i - 2]:
                fvgs.append({
                    "type": "bullish",
                    "index": i,
                    "top": df["low"].iloc[i],
                    "bottom": df["high"].iloc[i - 2],
                    "date": str(df.index[i])
                })
            # Bearish FVG: 3번째 캔들의 high < 1번째 캔들의 low
            elif df["high"].iloc[i] < df["low"].iloc[i - 2]:
                fvgs.append({
                    "type": "bearish",
                    "index": i,
                    "top": df["low"].iloc[i - 2],
                    "bottom": df["high"].iloc[i],
                    "date": str(df.index[i])
                })
        return fvgs

    @staticmethod
    def detect_rsi_divergence(df: pd.DataFrame, lookback: int = 14) -> list:
        """RSI 다이버전스 탐지 (iloc 기반으로 인덱스 안전성 확보)"""
        divergences = []
        if "rsi" not in df.columns or len(df) < lookback * 2:
            return divergences

        lows = df["low"].values
        highs = df["high"].values
        rsi_vals = df["rsi"].values

        for i in range(lookback, len(df)):
            seg_lows = lows[i - lookback:i + 1]
            seg_rsi = rsi_vals[i - lookback:i + 1]

            # Bullish divergence: 가격 Lower Low + RSI Higher Low
            min_pos = seg_lows.argmin()
            if lows[i] <= seg_lows.min() * 1.002 and min_pos < lookback:
                if seg_rsi[lookback] > seg_rsi[min_pos]:
                    divergences.append({
                        "type": "bullish",
                        "index": i,
                        "date": str(df.index[i]),
                        "price": float(lows[i]),
                        "rsi": float(rsi_vals[i])
                    })

            # Bearish divergence: 가격 Higher High + RSI Lower High
            seg_highs = highs[i - lookback:i + 1]
            max_pos = seg_highs.argmax()
            if highs[i] >= seg_highs.max() * 0.998 and max_pos < lookback:
                if seg_rsi[lookback] < seg_rsi[max_pos]:
                    divergences.append({
                        "type": "bearish",
                        "index": i,
                        "date": str(df.index[i]),
                        "price": float(highs[i]),
                        "rsi": float(rsi_vals[i])
                    })

        if not divergences:
            return []
        # Return only the single most recent divergence to avoid conflicting signals
        return [divergences[-1]]

    @staticmethod
    def detect_structure_shift(df: pd.DataFrame) -> dict:
        """
        Structure Shift 감지
        - 하락추세의 반전: 전저점 돌파 후 의미있게 지지 or FVG 동반 돌파
        - 상승추세의 반전: 전고점 실패 후 하방 전환
        """
        if len(df) < 20:
            return {"detected": False}

        recent = df.tail(20)
        lows = recent["low"].values
        highs = recent["high"].values
        closes = recent["close"].values

        # HH/HL 또는 LH/LL 시퀀스 확인
        swing_highs = []
        swing_lows = []

        for i in range(2, len(recent) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append((i, highs[i]))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append((i, lows[i]))

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            # Bullish shift: LH → HH 전환
            if swing_highs[-1][1] > swing_highs[-2][1] and swing_lows[-1][1] > swing_lows[-2][1]:
                return {
                    "detected": True,
                    "direction": "bullish",
                    "level": swing_lows[-1][1],
                    "description": "LH/LL → HH/HL 전환 감지"
                }
            # Bearish shift: HH → LH 전환
            if swing_highs[-1][1] < swing_highs[-2][1] and swing_lows[-1][1] < swing_lows[-2][1]:
                return {
                    "detected": True,
                    "direction": "bearish",
                    "level": swing_highs[-1][1],
                    "description": "HH/HL → LH/LL 전환 감지"
                }

        return {"detected": False}

    @staticmethod
    def determine_htf_bias(df: pd.DataFrame) -> str:
        """상위 시간대 방향성 판단"""
        if df.empty or len(df) < 10:
            return "Neutral"

        close = df["close"].iloc[-1]
        ma20 = df["close"].rolling(20).mean().iloc[-1] if len(df) >= 20 else close

        # 최근 5봉 기준 추세
        recent_closes = df["close"].tail(5).values
        trend = (recent_closes[-1] - recent_closes[0]) / recent_closes[0] * 100

        rsi = df["rsi"].iloc[-1] if "rsi" in df.columns else 50

        if close > ma20 and trend > 3 and rsi > 55:
            return "Strong Bullish"
        elif close > ma20 and trend > 0:
            return "Bullish"
        elif close < ma20 and trend < -3 and rsi < 45:
            return "Strong Bearish"
        elif close < ma20 and trend < 0:
            return "Bearish"
        return "Neutral"


# ═══════════════════════════════════════
# 신호 감지 엔진 (Signal Engine)
# ═══════════════════════════════════════

class SignalEngine:
    """규칙 기반 신호 감지"""

    def __init__(self, config: dict = None):
        self.config = config or DEFAULT_CONFIG
        self.fetcher = DataFetcher()
        self.ta = TechnicalAnalysis()
        self.signals: list[Signal] = []

    def scan_asset(self, symbol: str, asset_type: str) -> list[Signal]:
        """개별 자산 스캔"""
        signals = []
        print(f"\n🔍 스캔 중: {symbol} ({asset_type})")

        # Signal timeframe per asset type
        #   crypto      → 4H (OKX 4H bars; Yahoo 1h→4h resample fallback)
        #   etf/stock/bond → Daily
        if asset_type == "crypto":
            signal_tf = "4H"
            okx_symbol = symbol.replace("-USD", "/USDT")
            df_signal = self.fetcher.fetch_okx(okx_symbol, timeframe="4h", limit=500)
            if df_signal is None or df_signal.empty:
                print(f"  ℹ️ OKX fallback → Yahoo Finance (1h → 4h resample)")
                df_1h = self.fetcher.fetch_yahoo(symbol, period="60d", interval="1h")
                if not df_1h.empty:
                    df_signal = df_1h.resample("4h").agg({
                        "open": "first", "high": "max", "low": "min",
                        "close": "last", "volume": "sum"
                    }).dropna()
                else:
                    df_signal = pd.DataFrame()
        else:
            signal_tf = "1D"
            df_signal = self.fetcher.fetch_yahoo(symbol, period="1y", interval="1d")

        df_weekly = self.fetcher.fetch_yahoo(symbol, period="2y", interval="1wk")

        if df_signal.empty:
            print(f"  ⚠️ 데이터 없음, 스킵")
            return signals

        # 지표 추가
        df_signal = self.ta.add_indicators(df_signal, self.config)
        df_weekly = self.ta.add_indicators(df_weekly, self.config)

        # HTF Bias
        htf_bias = self.ta.determine_htf_bias(df_weekly)
        print(f"  📊 HTF Bias: {htf_bias}")

        # Backtest-derived filters
        filters = self.config.get("filters", {})

        # 3a. HTF Neutral skip
        if filters.get("skip_htf_neutral", False) and htf_bias == "Neutral":
            print(f"  ⏭️ HTF Neutral → 스킵")
            return signals

        # Non-crypto assets: Long only (no short selling without futures)
        long_only = asset_type in ("etf", "stock", "bond")

        # ─── 1. Structure Shift 감지 ───
        shift = self.ta.detect_structure_shift(df_signal)
        if shift["detected"]:
            direction = Direction.LONG if shift["direction"] == "bullish" else Direction.SHORT

            # Skip Short signals for long-only assets
            if long_only and direction == Direction.SHORT:
                pass
            # 3b. Counter-HTF block
            elif filters.get("block_counter_htf", False) and (
                (direction == Direction.LONG and "Strong Bear" in htf_bias) or
                (direction == Direction.SHORT and "Strong Bull" in htf_bias)
            ):
                print(f"  ⏭️ Structure Shift {direction.value} blocked (counter-HTF: {htf_bias})")
            else:
                confidence = 75

                # HTF 방향과 일치하면 신뢰도 상승
                if (direction == Direction.LONG and "Bull" in htf_bias) or \
                   (direction == Direction.SHORT and "Bear" in htf_bias):
                    confidence += 10

                entry = df_signal["close"].iloc[-1]
                atr = df_signal["atr"].iloc[-1] if "atr" in df_signal.columns else entry * 0.02
                sl = entry - (2 * atr) if direction == Direction.LONG else entry + (2 * atr)
                tp = entry + (4 * atr) if direction == Direction.LONG else entry - (4 * atr)
                rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

                if rr >= self.config["min_rr_ratio"]:
                    signals.append(Signal(
                        timestamp=datetime.now().isoformat(),
                        asset=symbol, asset_type=asset_type,
                        signal_type=SignalType.STRUCTURE_SHIFT.value,
                        direction=direction.value,
                        timeframe=signal_tf,
                        confidence=min(confidence, 95),
                        entry_price=round(entry, 2),
                        stop_loss=round(sl, 2),
                        take_profit=round(tp, 2),
                        rr_ratio=round(rr, 1),
                        reason=shift["description"],
                        checklist_passed=0,
                        htf_bias=htf_bias
                    ))
                    print(f"  🔔 Structure Shift: {direction.value} @ {entry:.2f}")

        # ─── 2. FVG 감지 ───
        fvgs = self.ta.detect_fvg(df_signal)
        recent_fvgs = [f for f in fvgs if f["index"] >= len(df_signal) - 5]
        for fvg in recent_fvgs[-2:]:  # 최근 2개만
            direction = Direction.LONG if fvg["type"] == "bullish" else Direction.SHORT

            # Skip Short FVG for long-only assets
            if long_only and direction == Direction.SHORT:
                continue

            # Bullish bias에서 Long FVG만, Bearish bias에서 Short FVG만
            if ("Bull" in htf_bias and direction == Direction.LONG) or \
               ("Bear" in htf_bias and direction == Direction.SHORT):

                entry = (fvg["top"] + fvg["bottom"]) / 2
                gap_size = abs(fvg["top"] - fvg["bottom"])

                # 3c. FVG gap minimum size filter (SL distance > fee)
                fvg_min_gap_pct = filters.get("fvg_min_gap_pct", 0)
                if fvg_min_gap_pct > 0 and entry > 0 and (gap_size / entry) < fvg_min_gap_pct:
                    continue
                sl = fvg["bottom"] - gap_size * 0.5 if direction == Direction.LONG else fvg["top"] + gap_size * 0.5
                tp = entry + gap_size * 3 if direction == Direction.LONG else entry - gap_size * 3
                rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

                if rr >= self.config["min_rr_ratio"]:
                    signals.append(Signal(
                        timestamp=datetime.now().isoformat(),
                        asset=symbol, asset_type=asset_type,
                        signal_type=SignalType.FVG_ENTRY.value,
                        direction=direction.value,
                        timeframe=signal_tf,
                        confidence=80,
                        entry_price=round(entry, 2),
                        stop_loss=round(sl, 2),
                        take_profit=round(tp, 2),
                        rr_ratio=round(rr, 1),
                        reason=f"{fvg['type'].title()} FVG @ {fvg['date'][:10]}",
                        checklist_passed=0,
                        htf_bias=htf_bias
                    ))
                    print(f"  🔔 FVG: {direction.value} zone {fvg['bottom']:.2f}-{fvg['top']:.2f}")

        # ─── 3. RSI 다이버전스 ───
        divs = self.ta.detect_rsi_divergence(df_signal)
        for div in divs:
            direction = Direction.LONG if div["type"] == "bullish" else Direction.SHORT
            # Skip Short RSI divergence for long-only assets
            if long_only and direction == Direction.SHORT:
                continue
            # 3d. RSI Divergence Short disable
            if filters.get("disable_rsi_divergence_short", False) and direction == Direction.SHORT:
                continue
            # 3e. RSI Divergence counter-HTF block
            if filters.get("block_counter_htf", False) and (
                (direction == Direction.LONG and "Strong Bear" in htf_bias) or
                (direction == Direction.SHORT and "Strong Bull" in htf_bias)
            ):
                continue
            entry = df_signal["close"].iloc[-1]
            atr = df_signal["atr"].iloc[-1] if "atr" in df_signal.columns else entry * 0.02
            sl = entry - 2 * atr if direction == Direction.LONG else entry + 2 * atr
            tp = entry + 4 * atr if direction == Direction.LONG else entry - 4 * atr
            rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

            if rr >= self.config["min_rr_ratio"]:
                signals.append(Signal(
                    timestamp=datetime.now().isoformat(),
                    asset=symbol, asset_type=asset_type,
                    signal_type=SignalType.RSI_DIVERGENCE.value,
                    direction=direction.value,
                    timeframe=signal_tf,
                    confidence=55,
                    entry_price=round(entry, 2),
                    stop_loss=round(sl, 2),
                    take_profit=round(tp, 2),
                    rr_ratio=round(rr, 1),
                    reason=f"{div['type'].title()} RSI Divergence (RSI: {div['rsi']:.1f})",
                    checklist_passed=0,
                    htf_bias=htf_bias
                ))
                print(f"  🔔 RSI Divergence: {div['type']} (RSI: {div['rsi']:.1f})")

        # ─── 4. 120일선 지지 (ETF 전용) ───
        if asset_type == "etf" and "ma_120" in df_signal.columns:
            close = df_signal["close"].iloc[-1]
            ma120 = df_signal["ma_120"].iloc[-1]
            if pd.notna(ma120) and close > ma120 * 0.97 and close < ma120 * 1.03:
                # 120일선 근처에서 지지
                if close > ma120 and df_signal["close"].iloc[-2] < ma120:
                    signals.append(Signal(
                        timestamp=datetime.now().isoformat(),
                        asset=symbol, asset_type=asset_type,
                        signal_type=SignalType.MA120_SUPPORT.value,
                        direction=Direction.LONG.value,
                        timeframe=signal_tf,
                        confidence=68,
                        entry_price=round(close, 2),
                        stop_loss=round(ma120 * 0.95, 2),
                        take_profit=round(close * 1.1, 2),
                        rr_ratio=round((close * 0.1) / (close - ma120 * 0.95), 1),
                        reason=f"120일선 지지 반등 (MA120: {ma120:.2f})",
                        checklist_passed=0,
                        htf_bias=htf_bias
                    ))
                    print(f"  🔔 120일선 지지: Long @ {close:.2f}")

        # ─── 5. Price Dip (개별주식) ───
        # NOTE: 순수 가격 트리거. fundamental/news 필터는 미구현 — 사람이 수동 검증.
        if asset_type == "stock":
            close = df_signal["close"].iloc[-1]
            recent_high = df_signal["high"].tail(20).max()
            drop_pct = (close - recent_high) / recent_high * 100

            if drop_pct < -10:  # 20일 최고가 대비 10% 이상 하락
                signals.append(Signal(
                    timestamp=datetime.now().isoformat(),
                    asset=symbol, asset_type=asset_type,
                    signal_type=SignalType.PRICE_DIP.value,
                    direction=Direction.LONG.value,
                    timeframe=signal_tf,
                    confidence=60,
                    entry_price=round(close, 2),
                    stop_loss=round(close * 0.93, 2),
                    take_profit=round(recent_high * 0.95, 2),
                    rr_ratio=round(abs(recent_high * 0.95 - close) / abs(close * 0.07), 1),
                    reason=f"20일 고점 대비 {drop_pct:.1f}% 하락 (수동 fundamental/news 검증 필요)",
                    checklist_passed=0,
                    htf_bias=htf_bias
                ))
                print(f"  🔔 Price Dip: {symbol} {drop_pct:.1f}% 하락")

        return signals

    def run_full_scan(self) -> list[Signal]:
        """전체 워치리스트 스캔"""
        all_signals = []
        wl = self.config["watchlist"]

        print("=" * 60)
        print(f"⚡ Structural Edge Signal Scan - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 60)

        # 암호화폐
        for symbol in wl.get("crypto", []):
            sigs = self.scan_asset(symbol, "crypto")
            all_signals.extend(sigs)

        # ETF
        for symbol in wl.get("etf", []):
            sigs = self.scan_asset(symbol, "etf")
            all_signals.extend(sigs)

        # 개별주식
        for symbol in wl.get("stocks", []):
            sigs = self.scan_asset(symbol, "stock")
            all_signals.extend(sigs)

        # 채권 (Structure Shift만)
        for symbol in wl.get("bonds", []):
            sigs = self.scan_asset(symbol, "bond")
            # 채권은 Structure Shift 신호만 유지
            bond_sigs = [s for s in sigs if s.signal_type == SignalType.STRUCTURE_SHIFT.value]
            all_signals.extend(bond_sigs)

        # 결과 정렬 (신뢰도 내림차순)
        all_signals.sort(key=lambda s: s.confidence, reverse=True)
        self.signals = all_signals

        # 결과 출력
        self._print_results(all_signals)

        # 로그 저장
        self._save_signals(all_signals)

        return all_signals

    def _print_results(self, signals: list[Signal]):
        """결과 출력"""
        print("\n" + "=" * 60)
        print(f"📊 스캔 결과: {len(signals)}개 신호 감지")
        print("=" * 60)

        if not signals:
            print("  ℹ️ 현재 조건에 맞는 신호가 없습니다.")
            return

        for i, sig in enumerate(signals, 1):
            direction_icon = "🟢" if sig.direction == "Long" else "🔴"
            confidence_bar = "█" * int(sig.confidence / 10) + "░" * (10 - int(sig.confidence / 10))
            print(f"\n  [{i}] {direction_icon} {sig.asset} ({sig.asset_type})")
            print(f"      신호: {sig.signal_type}")
            print(f"      방향: {sig.direction} | TF: {sig.timeframe} | HTF Bias: {sig.htf_bias}")
            print(f"      신뢰도: [{confidence_bar}] {sig.confidence:.0f}%")
            print(f"      진입: {sig.entry_price} | 손절: {sig.stop_loss} | 목표: {sig.take_profit}")
            print(f"      R:R = 1:{sig.rr_ratio}")
            print(f"      근거: {sig.reason}")

        # 자산별 요약
        print(f"\n{'─' * 40}")
        print("  📋 자산유형별 요약:")
        types = set(s.asset_type for s in signals)
        for t in types:
            count = len([s for s in signals if s.asset_type == t])
            print(f"     {t}: {count}개 신호")

    def _save_signals(self, signals: list[Signal]):
        """신호 로그 저장"""
        log_file = self.config.get("signal_log_file", "signal_log.json")
        try:
            existing = []
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    existing = json.load(f)

            new_entries = [asdict(s) for s in signals]
            existing.extend(new_entries)

            # 최근 500개만 유지
            existing = existing[-500:]

            with open(log_file, "w") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)

            print(f"\n  💾 신호 로그 저장: {log_file}")
        except Exception as e:
            print(f"  ❌ 로그 저장 실패: {e}")


# ═══════════════════════════════════════
# 거래 기록 관리 (Trade Manager)
# ═══════════════════════════════════════

class TradeManager:
    """거래 기록 및 성과 추적"""

    def __init__(self, config: dict = None):
        self.config = config or DEFAULT_CONFIG
        self.log_file = self.config.get("trade_log_file", "trade_log.json")
        self.trades: list[dict] = self._load_trades()

    def _load_trades(self) -> list:
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                return json.load(f)
        return []

    def _save_trades(self):
        with open(self.log_file, "w") as f:
            json.dump(self.trades, f, indent=2, ensure_ascii=False)

    def record_trade(self, trade: TradeRecord):
        """거래 기록"""
        self.trades.append(asdict(trade))
        self._save_trades()
        print(f"  ✅ 거래 기록 완료: {trade.asset} {trade.direction} @ {trade.entry_price}")

    def close_trade(self, trade_id: str, exit_price: float):
        """거래 청산"""
        for trade in self.trades:
            if trade["id"] == trade_id and trade["status"] == "OPEN":
                entry = trade["entry_price"]
                sl = trade["stop_loss"]
                direction = trade["direction"]

                pnl = (exit_price - entry) if direction == "Long" else (entry - exit_price)
                risk = abs(entry - sl)
                r_multiple = pnl / risk if risk > 0 else 0

                trade["status"] = "CLOSED"
                trade["exit_price"] = exit_price
                trade["pnl"] = round(pnl, 4)
                trade["r_multiple"] = round(r_multiple, 2)
                trade["closed_at"] = datetime.now().isoformat()

                self._save_trades()
                result = "✅ WIN" if pnl > 0 else "❌ LOSS"
                print(f"  {result}: {trade['asset']} P&L: {pnl:.4f} ({r_multiple:.2f}R)")
                return

        print(f"  ⚠️ 거래 ID {trade_id} 를 찾을 수 없습니다.")

    def get_performance_stats(self) -> dict:
        """성과 통계"""
        closed = [t for t in self.trades if t["status"] == "CLOSED"]
        if not closed:
            return {"message": "청산된 거래 없음"}

        wins = [t for t in closed if t["pnl"] > 0]
        losses = [t for t in closed if t["pnl"] <= 0]

        total_pnl = sum(t["pnl"] for t in closed)
        avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0
        avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0
        avg_r = np.mean([t["r_multiple"] for t in closed if t["r_multiple"] is not None])

        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": f"{len(wins)/len(closed)*100:.1f}%",
            "total_pnl": round(total_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "avg_r_multiple": round(avg_r, 2),
            "best_trade": max(closed, key=lambda t: t["pnl"])["asset"] if closed else "N/A",
            "worst_trade": min(closed, key=lambda t: t["pnl"])["asset"] if closed else "N/A"
        }

    def print_stats(self):
        """성과 출력"""
        stats = self.get_performance_stats()
        print("\n" + "=" * 50)
        print("📈 트레이딩 성과 요약")
        print("=" * 50)
        for key, value in stats.items():
            print(f"  {key}: {value}")


# ═══════════════════════════════════════
# 텔레그램 알림 (선택)
# ═══════════════════════════════════════

class TelegramNotifier:
    """텔레그램 봇을 통한 알림 전송"""

    def __init__(self, config: dict):
        self.enabled = config.get("telegram", {}).get("enabled", False)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._price_cache = {}

    def send(self, message: str):
        if not self.enabled:
            return
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(url, json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"})
        except Exception as e:
            print(f"  ❌ 텔레그램 전송 실패: {e}")

    def _get_price_context(self, symbol: str, asset_type: str) -> tuple:
        """현재가 및 가격 방향 조회 (캐시).
        crypto: 1h 봉 × 4 = 최근 4h 변동률
        그 외:  일봉 1봉 = 최근 1d 변동률 (전일 종가 대비)
        """
        if symbol in self._price_cache:
            return self._price_cache[symbol]
        try:
            fetcher = DataFetcher()
            if asset_type == "crypto":
                okx_symbol = symbol.replace("-USD", "/USDT")
                df = fetcher.fetch_okx(okx_symbol, timeframe="1h", limit=5)
                if df is None or df.empty:
                    df = fetcher.fetch_yahoo(symbol, period="5d", interval="1h")
                lookback = 4
                label = "4h"
            else:
                df = fetcher.fetch_yahoo(symbol, period="10d", interval="1d")
                lookback = 1
                label = "1d"
            if df is not None and len(df) > lookback:
                current = float(df["close"].iloc[-1])
                prior = float(df["close"].iloc[-1 - lookback])
                direction = "🔺" if current >= prior else "🔻"
                pct = (current - prior) / prior * 100
                result = (current, direction, pct, label)
                self._price_cache[symbol] = result
                return result
        except Exception:
            pass
        result = (0, "➖", 0.0, "n/a")
        self._price_cache[symbol] = result
        return result

    def format_signal(self, signal: Signal) -> str:
        direction_icon = "🟢" if signal.direction == "Long" else "🔴"
        current_price, trend_icon, pct_change, ctx_label = self._get_price_context(signal.asset, signal.asset_type)
        price_str = f"{current_price:,.2f}" if current_price >= 1 else f"{current_price:.6f}"
        return (
            f"{direction_icon} <b>{signal.asset}</b> ({signal.asset_type})\n"
            f"현재가: {price_str} {trend_icon} {pct_change:+.2f}% ({ctx_label})\n"
            f"신호: {signal.signal_type}\n"
            f"방향: {signal.direction} | TF: {signal.timeframe} | 신뢰도: {signal.confidence:.0f}%\n"
            f"진입: {signal.entry_price} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"R:R = 1:{signal.rr_ratio}\n"
            f"HTF Bias: {signal.htf_bias}\n"
            f"근거: {signal.reason}"
        )


# ═══════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════

def main():
    """메인 실행 함수"""
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║  ⚡ Structural Edge Trading System v0.3                 ║
    ║  확률 기반 구조적 대응 매매 시스템                       ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # 설정 로드
    config = DEFAULT_CONFIG.copy()
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            user_config = json.load(f)
            config = deep_merge(config, user_config)
        print("  📁 config.json 로드 완료")

    # 엔진 초기화
    engine = SignalEngine(config)
    trade_manager = TradeManager(config)
    notifier = TelegramNotifier(config)

    # 전체 스캔 실행
    signals = engine.run_full_scan()

    # 텔레그램 알림 전송
    if signals and notifier.enabled:
        for sig in signals[:5]:  # 상위 5개만
            notifier.send(notifier.format_signal(sig))
        print(f"\n  📱 텔레그램 알림 {min(len(signals), 5)}건 전송 완료")

    # 성과 통계
    trade_manager.print_stats()

    print(f"\n✅ 스캔 완료 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("─" * 50)
    print("💡 다음 단계:")
    print("  1. 신호를 확인하고 체크리스트를 통과한 후 진입 결정")
    print("  2. 대시보드에서 거래 기록 및 성과 추적")
    print("  3. schedule 라이브러리로 자동 스캔 예약 가능")
    print("  4. 텔레그램 봇 설정으로 실시간 알림 수신")


if __name__ == "__main__":
    main()
