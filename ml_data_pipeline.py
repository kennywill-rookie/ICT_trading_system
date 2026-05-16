"""
⚡ ML Phase 1: 4H FVG Event Data Pipeline
==========================================
BTC-USDT 4H FVG 이벤트를 감지하고, 각 이벤트에 대해
leakage-free features + SL/TP-touch labels를 생성.

구현 순서: fetch → events 수 확인 → labels 분포 → features
출력: ml_fvg_dataset.csv

사용법:
  python ml_data_pipeline.py
"""

import json
import os
import time as _time
from datetime import datetime

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import requests

from signal_engine import TechnicalAnalysis

# ═══════════════════════════════════════
# Constants
# ═══════════════════════════════════════

FEE_TAKER_ONE_WAY = 0.0006      # OKX taker 0.06% per side
FEE_ROUND_TRIP = 0.0012          # 0.12% round trip
FUNDING_RATE_PER_8H = 0.0001    # 0.01% per 8h
HORIZON_BARS = 192               # 48h in 15min bars
RR_RATIOS = [1.5, 2.0]
FEATURE_WINDOW = 192             # 48h lookback
RSI_DELTA_LOOKBACK = 16          # 4h in 15min bars
VOL_AVG_WINDOW = 20
VOL_SURGE_DENOM = 48             # 12h baseline for vol_surge
ATR_PERCENTILE_WINDOW = 100
MA_PERIOD_4H = 20
TRENDING_THRESHOLD = 0.03        # 3% over 48h = trending


# ═══════════════════════════════════════
# Data Fetch (reuse backtest_15m logic)
# ═══════════════════════════════════════

ASSETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]


def fetch_15m_data(inst_id: str = "BTC-USDT") -> pd.DataFrame:
    """OKX 15분봉 최대 수집 (페이징)"""
    print(f"📥 {inst_id} 15분봉 수집 중...")
    bar = "15m"
    all_data = []

    url = "https://www.okx.com/api/v5/market/candles"
    resp = requests.get(url, params={"instId": inst_id, "bar": bar, "limit": "300"}, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != "0":
        raise RuntimeError(f"OKX API error: {body.get('msg')}")
    all_data.extend(body["data"])

    url_hist = "https://www.okx.com/api/v5/market/history-candles"
    after = all_data[-1][0]
    for page in range(200):
        resp = requests.get(url_hist, params={
            "instId": inst_id, "bar": bar, "limit": "100", "after": after
        }, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "0" or not body.get("data"):
            break
        all_data.extend(body["data"])
        after = body["data"][-1][0]
        if (page + 1) % 20 == 0:
            print(f"   {len(all_data)}봉 (page {page + 1})...")
        _time.sleep(0.05)

    df = pd.DataFrame(all_data, columns=[
        "timestamp", "open", "high", "low", "close",
        "volume", "volCcy", "volCcyQuote", "confirm"
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df = df.sort_values("timestamp").set_index("timestamp")
    df = df[~df.index.duplicated(keep='first')]

    days = (df.index[-1] - df.index[0]).days
    print(f"   완료: {len(df)}봉 ({days}일)")
    return df


def resample_to_4h(df_15m: pd.DataFrame) -> pd.DataFrame:
    """15분봉 → 4시간봉 리샘플링"""
    return df_15m.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum',
    }).dropna()


# ═══════════════════════════════════════
# 4H FVG Event Detection
# ═══════════════════════════════════════

def detect_4h_fvg_events(df_4h: pd.DataFrame, df_15m: pd.DataFrame) -> list[dict]:
    """
    4H FVG 감지 + cutoff_15m_idx 부여.
    cutoff = FVG 형성 완료 봉(4H bar[i])의 마지막 15분봉.
    """
    events = []
    for i in range(2, len(df_4h)):
        h_i = df_4h["high"].iloc[i]
        l_i = df_4h["low"].iloc[i]
        h_i2 = df_4h["high"].iloc[i - 2]
        l_i2 = df_4h["low"].iloc[i - 2]

        fvg_type = None
        if l_i > h_i2:
            fvg_type = "bullish"
            top, bottom = l_i, h_i2
        elif h_i < l_i2:
            fvg_type = "bearish"
            top, bottom = l_i2, h_i

        if fvg_type is None:
            continue

        gap_size = abs(top - bottom)
        midpoint = (top + bottom) / 2
        gap_pct = gap_size / midpoint if midpoint > 0 else 0

        # cutoff: 4H bar[i]의 종료 시각 이전의 마지막 15분봉
        bar_4h_end = df_4h.index[i]
        cutoff_mask = df_15m.index <= bar_4h_end
        if cutoff_mask.sum() == 0:
            continue
        cutoff_15m_idx = int(np.where(cutoff_mask)[0][-1])

        # entry = cutoff + 1 (다음 15분봉 open)
        entry_15m_idx = cutoff_15m_idx + 1
        if entry_15m_idx >= len(df_15m):
            continue

        events.append({
            "timestamp": str(bar_4h_end),
            "type": fvg_type,
            "top": float(top),
            "bottom": float(bottom),
            "gap_size": float(gap_size),
            "gap_pct": float(gap_pct),
            "cutoff_4h_idx": i,
            "cutoff_15m_idx": cutoff_15m_idx,
            "entry_15m_idx": entry_15m_idx,
        })

    return events


# ═══════════════════════════════════════
# Label Generation
# ═══════════════════════════════════════

def build_labels(df_15m: pd.DataFrame, event: dict,
                 rr_ratios: list[float] = None) -> dict:
    """
    고정 RR 기반 SL/TP 먼저 터치 label.
    Entry = entry_15m_idx bar의 open (market order).
    SL = FVG gap 반대편 (bullish→bottom, bearish→top).
    TP = entry + risk * rr_ratio.
    """
    if rr_ratios is None:
        rr_ratios = RR_RATIOS

    entry_idx = event["entry_15m_idx"]
    entry_price = float(df_15m["open"].iloc[entry_idx])
    is_long = event["type"] == "bullish"

    # SL = gap opposite end
    sl = event["bottom"] if is_long else event["top"]
    risk = abs(entry_price - sl)
    if risk <= 0:
        return None

    result = {
        "entry_price": entry_price,
        "sl_price": sl,
        "risk": risk,
        "direction": "Long" if is_long else "Short",
    }

    end_idx = min(entry_idx + HORIZON_BARS, len(df_15m))

    for rr in rr_ratios:
        tp = entry_price + risk * rr if is_long else entry_price - risk * rr
        label = -1  # timeout (excluded)
        timeout_flag = True
        ambiguous_bar = False
        actual_hold_bars = end_idx - entry_idx
        exit_price = float(df_15m["close"].iloc[end_idx - 1]) if end_idx > entry_idx else entry_price

        for j in range(entry_idx + 1, end_idx):
            bar_high = float(df_15m["high"].iloc[j])
            bar_low = float(df_15m["low"].iloc[j])

            if is_long:
                hit_sl = bar_low <= sl
                hit_tp = bar_high >= tp
            else:
                hit_sl = bar_high >= sl
                hit_tp = bar_low <= tp

            if hit_sl and hit_tp:
                # Ambiguous: SL priority
                label = 0
                timeout_flag = False
                ambiguous_bar = True
                actual_hold_bars = j - entry_idx
                exit_price = sl
                break
            elif hit_sl:
                label = 0
                timeout_flag = False
                actual_hold_bars = j - entry_idx
                exit_price = sl
                break
            elif hit_tp:
                label = 1
                timeout_flag = False
                actual_hold_bars = j - entry_idx
                exit_price = tp
                break

        # Costs
        fee = entry_price * FEE_TAKER_ONE_WAY + exit_price * FEE_TAKER_ONE_WAY
        funding_periods = actual_hold_bars // 32
        funding = entry_price * FUNDING_RATE_PER_8H * funding_periods

        raw_pnl = (exit_price - entry_price) if is_long else (entry_price - exit_price)
        net_pnl = raw_pnl - fee - funding
        actual_r = net_pnl / risk if risk > 0 else 0

        rr_key = str(rr).replace(".", "")
        result[f"label_rr{rr_key}"] = label
        result[f"tp_rr{rr_key}"] = tp
        result[f"timeout_flag_rr{rr_key}"] = timeout_flag
        result[f"ambiguous_bar_rr{rr_key}"] = ambiguous_bar
        result[f"actual_r_rr{rr_key}"] = round(actual_r, 4)
        result[f"hold_bars_rr{rr_key}"] = actual_hold_bars
        result[f"fee_rr{rr_key}"] = round(fee, 2)
        result[f"funding_rr{rr_key}"] = round(funding, 2)

    return result


# ═══════════════════════════════════════
# Feature Engineering (20 features)
# ═══════════════════════════════════════

def build_features(df_15m: pd.DataFrame, df_4h: pd.DataFrame,
                   event: dict, all_events: list[dict]) -> dict:
    """
    cutoff_15m_idx까지만 참조하여 features 계산.
    Leakage prevention: cutoff 이후 데이터 절대 접근 안 함.
    """
    cutoff = event["cutoff_15m_idx"]
    start = max(0, cutoff - FEATURE_WINDOW)
    window = df_15m.iloc[start:cutoff + 1]

    if len(window) < 50:
        return None

    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    volumes = window["volume"].values
    entry_price = float(df_15m["open"].iloc[event["entry_15m_idx"]])

    features = {}

    # ─── A. Price Structure (7) ───

    # 1. gap_pct
    features["gap_pct"] = event["gap_pct"]

    # 2. gap_atr_ratio
    atr_vals = _calc_atr(highs, lows, closes, 14)
    current_atr = atr_vals[-1] if len(atr_vals) > 0 and atr_vals[-1] > 0 else entry_price * 0.01
    features["gap_atr_ratio"] = event["gap_size"] / current_atr

    # 3. trend_48bars
    if len(closes) >= FEATURE_WINDOW:
        trend = (closes[-1] - closes[0]) / closes[0]
    else:
        trend = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
    features["trend_48bars"] = round(trend, 6)

    # 4. swing_count
    swing_count = 0
    for k in range(2, len(highs) - 2):
        if highs[k] > max(highs[k-1], highs[k-2], highs[k+1], highs[k+2]):
            swing_count += 1
        if lows[k] < min(lows[k-1], lows[k-2], lows[k+1], lows[k+2]):
            swing_count += 1
    features["swing_count"] = swing_count

    # 5-6. dist_to_swing_high/low_pct
    swing_highs_vals = []
    swing_lows_vals = []
    for k in range(2, len(highs) - 2):
        if highs[k] > max(highs[k-1], highs[k-2], highs[k+1], highs[k+2]):
            swing_highs_vals.append(highs[k])
        if lows[k] < min(lows[k-1], lows[k-2], lows[k+1], lows[k+2]):
            swing_lows_vals.append(lows[k])

    current_price = closes[-1]
    if swing_highs_vals:
        nearest_sh = min(swing_highs_vals, key=lambda x: abs(x - current_price))
        features["dist_to_swing_high_pct"] = (nearest_sh - current_price) / current_price
    else:
        features["dist_to_swing_high_pct"] = 0.0

    if swing_lows_vals:
        nearest_sl = min(swing_lows_vals, key=lambda x: abs(x - current_price))
        features["dist_to_swing_low_pct"] = (nearest_sl - current_price) / current_price
    else:
        features["dist_to_swing_low_pct"] = 0.0

    # 7. higher_tf_trend (price position vs 4H MA20)
    cutoff_4h = event["cutoff_4h_idx"]
    if cutoff_4h >= MA_PERIOD_4H:
        ma20_4h = df_4h["close"].iloc[cutoff_4h - MA_PERIOD_4H + 1:cutoff_4h + 1].mean()
        recent_4h_high = df_4h["high"].iloc[cutoff_4h - MA_PERIOD_4H + 1:cutoff_4h + 1].max()
        recent_4h_low = df_4h["low"].iloc[cutoff_4h - MA_PERIOD_4H + 1:cutoff_4h + 1].min()
        rng = recent_4h_high - recent_4h_low
        features["higher_tf_trend"] = (current_price - recent_4h_low) / rng if rng > 0 else 0.5
    else:
        features["higher_tf_trend"] = 0.5

    # ─── B. Momentum (5) ───

    # 8. rsi_14
    rsi_vals = _calc_rsi(closes, 14)
    features["rsi_14"] = rsi_vals[-1] if len(rsi_vals) > 0 else 50.0

    # 9. rsi_delta_16bars
    if len(rsi_vals) > RSI_DELTA_LOOKBACK:
        features["rsi_delta_16bars"] = rsi_vals[-1] - rsi_vals[-RSI_DELTA_LOOKBACK - 1]
    else:
        features["rsi_delta_16bars"] = 0.0

    # 10. bb_position
    bb_period = 20
    if len(closes) >= bb_period:
        ma = np.mean(closes[-bb_period:])
        std = np.std(closes[-bb_period:])
        if std > 0:
            features["bb_position"] = (current_price - (ma - 2 * std)) / (4 * std)
        else:
            features["bb_position"] = 0.5
    else:
        features["bb_position"] = 0.5

    # 11. vol_ratio
    if len(volumes) >= VOL_AVG_WINDOW and np.mean(volumes[-VOL_AVG_WINDOW:]) > 0:
        features["vol_ratio"] = volumes[-1] / np.mean(volumes[-VOL_AVG_WINDOW:])
    else:
        features["vol_ratio"] = 1.0

    # 12. vol_surge_15m: top3 of FVG's 12 bars / prev 48-bar avg
    # FVG 4H bar spans 16 fifteen-min bars (4h / 15min = 16)
    fvg_bar_count = 16
    fvg_end = cutoff
    fvg_start = max(0, fvg_end - fvg_bar_count + 1)
    fvg_vols = volumes[fvg_start - start:fvg_end - start + 1] if fvg_end >= start else np.array([])

    if len(fvg_vols) >= 3:
        top3_avg = np.mean(sorted(fvg_vols, reverse=True)[:3])
    else:
        top3_avg = np.mean(fvg_vols) if len(fvg_vols) > 0 else 0

    denom_end = fvg_start - 1
    denom_start = max(0, denom_end - VOL_SURGE_DENOM + 1)
    denom_vols = volumes[denom_start - start:denom_end - start + 1] if denom_end >= start else np.array([])
    denom_avg = np.mean(denom_vols) if len(denom_vols) > 0 else 1.0

    features["vol_surge_15m"] = top3_avg / denom_avg if denom_avg > 0 else 1.0

    # ─── C. FVG Context (4) ───

    event_idx_in_list = None
    for idx, e in enumerate(all_events):
        if e["cutoff_15m_idx"] == event["cutoff_15m_idx"] and e["timestamp"] == event["timestamp"]:
            event_idx_in_list = idx
            break

    # 13. prev_fvg_same_dir_dist
    prev_same = None
    if event_idx_in_list is not None:
        for k in range(event_idx_in_list - 1, -1, -1):
            if all_events[k]["type"] == event["type"]:
                prev_same = all_events[k]
                break
    if prev_same is not None:
        features["prev_fvg_same_dir_dist"] = event["cutoff_4h_idx"] - prev_same["cutoff_4h_idx"]
    else:
        features["prev_fvg_same_dir_dist"] = 999

    # 14. prev_fvg_filled
    if prev_same is not None:
        filled = _check_fvg_filled(df_15m, prev_same, event["cutoff_15m_idx"])
        features["prev_fvg_filled"] = int(filled)
    else:
        features["prev_fvg_filled"] = 0

    # 15. impulse_purity: sum(bodies) / sum(ranges) for FVG's 3 4H bars
    ci = event["cutoff_4h_idx"]
    if ci >= 2:
        bodies = 0.0
        ranges = 0.0
        for k in range(ci - 2, ci + 1):
            o = float(df_4h["open"].iloc[k])
            c = float(df_4h["close"].iloc[k])
            h = float(df_4h["high"].iloc[k])
            l = float(df_4h["low"].iloc[k])
            bodies += abs(c - o)
            ranges += (h - l) if h > l else 0.001
        features["impulse_purity"] = bodies / ranges if ranges > 0 else 0.5
    else:
        features["impulse_purity"] = 0.5

    # 16. consecutive_dir_bars
    is_bullish = event["type"] == "bullish"
    consec = 0
    for k in range(len(closes) - 1, 0, -1):
        if is_bullish and closes[k] > closes[k - 1]:
            consec += 1
        elif not is_bullish and closes[k] < closes[k - 1]:
            consec += 1
        else:
            break
    features["consecutive_dir_bars"] = consec

    # ─── D. Time/Regime (4) ───

    # 17. hour_of_day (4H bar start UTC hour)
    ts = pd.Timestamp(event["timestamp"])
    features["hour_of_day"] = ts.hour

    # 18. day_of_week
    features["day_of_week"] = ts.dayofweek

    # 19. atr_percentile
    if len(atr_vals) >= ATR_PERCENTILE_WINDOW:
        recent_atrs = atr_vals[-ATR_PERCENTILE_WINDOW:]
        features["atr_percentile"] = float(np.searchsorted(np.sort(recent_atrs), current_atr)) / len(recent_atrs)
    else:
        features["atr_percentile"] = 0.5

    # 20. is_trending
    features["is_trending"] = int(abs(trend) > TRENDING_THRESHOLD)

    return features


# ═══════════════════════════════════════
# Helper: ATR / RSI calculations (numpy)
# ═══════════════════════════════════════

def _calc_atr(highs: np.ndarray, lows: np.ndarray,
              closes: np.ndarray, period: int = 14) -> np.ndarray:
    """ATR 계산 (numpy only, no ta dependency for pipeline)"""
    if len(highs) < period + 1:
        return np.array([np.mean(highs - lows)] * len(highs))
    tr = np.maximum(highs[1:] - lows[1:],
                    np.maximum(np.abs(highs[1:] - closes[:-1]),
                               np.abs(lows[1:] - closes[:-1])))
    tr = np.concatenate([[highs[0] - lows[0]], tr])
    atr = np.full_like(tr, np.nan)
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    # backfill NaN
    first_valid = atr[period - 1]
    atr[:period - 1] = first_valid
    return atr


def _calc_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI 계산 (numpy only)"""
    if len(closes) < period + 1:
        return np.full(len(closes), 50.0)
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    rsi = np.full(len(closes), 50.0)
    if avg_loss > 0:
        rs = avg_gain / avg_loss
        rsi[period] = 100 - 100 / (1 + rs)
    else:
        rsi[period] = 100.0
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss > 0:
            rsi[i] = 100 - 100 / (1 + avg_gain / avg_loss)
        else:
            rsi[i] = 100.0
    return rsi


def _check_fvg_filled(df_15m: pd.DataFrame, prev_event: dict,
                      current_cutoff: int) -> bool:
    """이전 FVG가 현재 시점까지 fill 되었는지 확인"""
    start = prev_event["entry_15m_idx"]
    end = min(current_cutoff, len(df_15m))
    if start >= end:
        return False

    for j in range(start, end):
        if prev_event["type"] == "bullish":
            # Bullish FVG filled = price drops below bottom
            if float(df_15m["low"].iloc[j]) <= prev_event["bottom"]:
                return True
        else:
            # Bearish FVG filled = price rises above top
            if float(df_15m["high"].iloc[j]) >= prev_event["top"]:
                return True
    return False


# ═══════════════════════════════════════
# Split & fold_id
# ═══════════════════════════════════════

def assign_splits(n_events: int) -> tuple[list[str], list[int]]:
    """
    70/15/15 time-ordered split + expanding window fold_id.
    fold_id: 4-fold expanding window (50/60/70/80% train, 10% test each).
    """
    splits = []
    fold_ids = []

    train_end = int(n_events * 0.70)
    val_end = int(n_events * 0.85)

    for i in range(n_events):
        if i < train_end:
            splits.append("train")
        elif i < val_end:
            splits.append("val")
        else:
            splits.append("test")

    # Expanding window fold_id
    # fold 0: train=50%, test=50-60%
    # fold 1: train=60%, test=60-70%
    # fold 2: train=70%, test=70-80%
    # fold 3: train=80%, test=80-90% (rest is holdout)
    boundaries = [0.5, 0.6, 0.7, 0.8, 0.9]
    for i in range(n_events):
        pct = i / n_events
        if pct < boundaries[0]:
            fold_ids.append(-1)  # always train
        elif pct < boundaries[1]:
            fold_ids.append(0)
        elif pct < boundaries[2]:
            fold_ids.append(1)
        elif pct < boundaries[3]:
            fold_ids.append(2)
        elif pct < boundaries[4]:
            fold_ids.append(3)
        else:
            fold_ids.append(-2)  # holdout

    return splits, fold_ids


# ═══════════════════════════════════════
# Pipeline: create_dataset
# ═══════════════════════════════════════

def _process_asset(inst_id: str) -> list[dict]:
    """단일 자산 파이프라인: fetch → events → labels → features"""
    df_15m = fetch_15m_data(inst_id)
    df_4h = resample_to_4h(df_15m)
    print(f"   4H 봉: {len(df_4h)}개")

    events = detect_4h_fvg_events(df_4h, df_15m)
    print(f"   4H FVG 이벤트: {len(events)}개")
    if not events:
        return []

    bullish = sum(1 for e in events if e["type"] == "bullish")
    print(f"   Bullish: {bullish} | Bearish: {len(events) - bullish}")

    # Labels
    labeled_events = []
    for event in events:
        label_data = build_labels(df_15m, event)
        if label_data is not None:
            labeled_events.append((event, label_data))

    for rr in RR_RATIOS:
        rr_key = str(rr).replace(".", "")
        wins = sum(1 for _, ld in labeled_events if ld[f"label_rr{rr_key}"] == 1)
        losses = sum(1 for _, ld in labeled_events if ld[f"label_rr{rr_key}"] == 0)
        timeouts = sum(1 for _, ld in labeled_events if ld[f"label_rr{rr_key}"] == -1)
        total_valid = wins + losses
        wr = wins / total_valid * 100 if total_valid > 0 else 0
        print(f"   RR {rr}: W={wins} L={losses} T={timeouts} (승률 {wr:.1f}%)")

    # Features
    all_event_dicts = [e for e, _ in labeled_events]
    rows = []
    for event, label_data in labeled_events:
        feat = build_features(df_15m, df_4h, event, all_event_dicts)
        if feat is None:
            continue
        row = {"timestamp": event["timestamp"], "type": event["type"], "asset": inst_id}
        row.update(feat)
        row.update(label_data)
        rows.append(row)

    print(f"   유효 행: {len(rows)}개")
    return rows


def create_dataset() -> pd.DataFrame:
    """전체 파이프라인: 멀티 자산 fetch → events → labels → features → CSV"""

    all_rows = []
    for inst_id in ASSETS:
        print(f"\n{'─' * 50}")
        print(f"📊 {inst_id}")
        print(f"{'─' * 50}")
        rows = _process_asset(inst_id)
        all_rows.extend(rows)
        print()

    print(f"\n총 이벤트: {len(all_rows)}개")
    if not all_rows:
        print("❌ 유효한 데이터 없음")
        return pd.DataFrame()

    # 시간순 정렬 (멀티 자산이므로 timestamp 기준)
    all_rows.sort(key=lambda r: r["timestamp"])

    # Split + fold_id (전체 시간순 기준)
    splits, fold_ids = assign_splits(len(all_rows))
    for i, row in enumerate(all_rows):
        row["split"] = splits[i]
        row["fold_id"] = fold_ids[i]

    df = pd.DataFrame(all_rows)

    # Column order
    meta_cols = ["timestamp", "asset", "type", "direction", "entry_price", "sl_price", "risk"]
    feature_cols = [
        "gap_pct", "gap_atr_ratio", "trend_48bars", "swing_count",
        "dist_to_swing_high_pct", "dist_to_swing_low_pct", "higher_tf_trend",
        "rsi_14", "rsi_delta_16bars", "bb_position", "vol_ratio", "vol_surge_15m",
        "prev_fvg_same_dir_dist", "prev_fvg_filled",
        "consecutive_dir_bars", "day_of_week",
        "atr_percentile",
    ]
    label_cols = []
    for rr in RR_RATIOS:
        rr_key = str(rr).replace(".", "")
        label_cols.extend([
            f"label_rr{rr_key}", f"tp_rr{rr_key}",
            f"timeout_flag_rr{rr_key}", f"ambiguous_bar_rr{rr_key}",
            f"actual_r_rr{rr_key}", f"hold_bars_rr{rr_key}",
            f"fee_rr{rr_key}", f"funding_rr{rr_key}",
        ])
    split_cols = ["split", "fold_id"]

    all_cols = meta_cols + feature_cols + label_cols + split_cols
    existing = [c for c in all_cols if c in df.columns]
    df = df[existing]

    return df


# ═══════════════════════════════════════
# Main
# ═══════════════════════════════════════

def main():
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║  ⚡ ML Phase 1: 4H FVG Event Data Pipeline v2           ║
    ║  Multi-asset (BTC/ETH/SOL) → 4H FVG → Features+Labels  ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    df = create_dataset()
    if df.empty:
        print("❌ 데이터셋 생성 실패")
        return

    out_path = "ml_fvg_dataset.csv"
    df.to_csv(out_path, index=False)
    print(f"\n💾 저장: {out_path} ({len(df)}행 × {len(df.columns)}열)")

    # Summary
    print(f"\n{'═' * 50}")
    print("📋 데이터셋 요약")
    print(f"{'═' * 50}")
    print(f"  행: {len(df)}")
    print(f"  열: {len(df.columns)}")
    print(f"  기간: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    if "asset" in df.columns:
        print(f"\n  자산별 분포:")
        for asset in sorted(df["asset"].unique()):
            cnt = (df["asset"] == asset).sum()
            print(f"    {asset}: {cnt}개")
    print(f"\n  Split 분포:")
    for s in ["train", "val", "test"]:
        cnt = (df["split"] == s).sum()
        print(f"    {s}: {cnt}개 ({cnt/len(df)*100:.1f}%)")
    print(f"\n  Fold 분포:")
    for fid in sorted(df["fold_id"].unique()):
        cnt = (df["fold_id"] == fid).sum()
        label = {-1: "always-train", -2: "holdout"}.get(fid, f"fold-{fid}")
        print(f"    {label}: {cnt}개")

    print(f"\n  Feature 통계:")
    feature_cols = [
        "gap_pct", "gap_atr_ratio", "trend_48bars", "rsi_14",
        "bb_position", "vol_ratio", "vol_surge_15m", "atr_percentile",
    ]
    for col in feature_cols:
        if col in df.columns:
            print(f"    {col:25s}  mean={df[col].mean():.4f}  std={df[col].std():.4f}")

    print(f"\n✅ 완료 — 다음 단계: XGBoost 학습 (AUC > 0.55 목표)")


if __name__ == "__main__":
    main()
