"""
⚡ Structural Edge - Forward Walking Backtest (15min)  [DEPRECATED 2026-05-16]
=============================================================================

╔══════════════════════════════════════════════════════════════════════════╗
║  STATUS: DEPRECATED — rule-based 15m strategy is shelved (do NOT trade) ║
║                                                                          ║
║  Why:                                                                    ║
║   backtest_15m_result.json (BTC-USD, 693 trades):                        ║
║     total_R = -233.37R   PF = 0.59   WR = 41.8%                          ║
║     All setups (FVG / RSI Div / Structure Shift) negative.               ║
║     Fees alone (~₩129K) exceed any setup edge.                           ║
║                                                                          ║
║  Decision (Codex review 2026-05-16 + integrated overhaul task):          ║
║   - Stop running this script as a live or paper trading source.          ║
║   - Keep code + dataset for FUTURE ML feature learning only              ║
║     (event/feature/label table per CLAUDE.md ML philosophy §).           ║
║   - Re-enable only if exit logic is replaced by ML-derived stops         ║
║     (COUNTER_FVG exit avgR = +1.35R hints exit logic is the issue).      ║
║                                                                          ║
║  Reference:                                                              ║
║   agent_handoff/tasks/2026-05-16_integrated_signal_decision_overhaul.md  ║
║   SIGNAL_TAXONOMY.md (state: deprecated)                                 ║
╚══════════════════════════════════════════════════════════════════════════╝

BTC-USDT 15분봉 기반, bar-by-bar forward walk.
HTF = 4H (15분봉에서 리샘플링), OKX REST API 데이터.

사용법 (research only):
  python3 backtest_15m.py
"""

import json
import time as _time
from datetime import datetime, timedelta
from typing import Optional

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import requests

from signal_engine import (
    TechnicalAnalysis, SignalType, Direction, DEFAULT_CONFIG, deep_merge,
)
from backtest import BacktestSignal, BacktestTrade, BacktestAnalyzer


# ═══════════════════════════════════════
# 15분봉 Forward Walking Backtest
# ═══════════════════════════════════════

class ForwardWalkBacktest15m:

    WARMUP = 300            # 지표 warmup (300 × 15min = 75시간 ≈ 3일)
    MAX_HOLD_BARS = 192     # 최대 보유 (192 × 15min = 48시간 = 2일)
    SIGNAL_COOLDOWN = 8     # 쿨다운 (8 × 15min = 2시간)

    def __init__(self, config: dict = None):
        self.config = config or DEFAULT_CONFIG
        self.ta = TechnicalAnalysis()
        self.trades: list[BacktestTrade] = []

    # ─── OKX 15분 데이터 수집 ───

    def fetch_data(self) -> pd.DataFrame:
        """OKX REST API에서 BTC-USDT 15분봉 최대 수집 (페이징)"""
        print("📥 BTC-USDT 15분봉 데이터 수집 중 (OKX)...")

        inst_id = "BTC-USDT"
        bar = "15m"
        all_data = []

        # 1단계: /market/candles (최근, max 300)
        url = "https://www.okx.com/api/v5/market/candles"
        resp = requests.get(url, params={"instId": inst_id, "bar": bar, "limit": "300"}, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "0":
            raise RuntimeError(f"OKX API error: {body.get('msg')}")
        all_data.extend(body["data"])
        print(f"   candles: {len(all_data)}봉")

        # 2단계: /market/history-candles (과거, 100/page 페이징)
        url_hist = "https://www.okx.com/api/v5/market/history-candles"
        after = all_data[-1][0]
        page = 0
        max_pages = 200  # 안전 장치

        while page < max_pages:
            resp = requests.get(url_hist, params={
                "instId": inst_id, "bar": bar, "limit": "100", "after": after
            }, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != "0" or not body.get("data"):
                break
            all_data.extend(body["data"])
            after = body["data"][-1][0]
            page += 1
            if page % 20 == 0:
                print(f"   history-candles: {len(all_data)}봉 (page {page})...")
            _time.sleep(0.05)

        if not all_data:
            raise RuntimeError("데이터 수집 실패")

        # DataFrame 변환
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
        print(f"   수집 완료: {len(df)}봉 ({days}일)")
        print(f"   구간: {df.index[0].strftime('%Y-%m-%d %H:%M')} ~ {df.index[-1].strftime('%Y-%m-%d %H:%M')}")
        return df

    @staticmethod
    def to_4h(df: pd.DataFrame) -> pd.DataFrame:
        """15분봉 → 4시간봉 리샘플링"""
        h4 = df.resample('4h').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }).dropna()
        return h4

    # ─── TP1 / Counter FVG ───

    def _find_tp1(self, df: pd.DataFrame, bar_idx: int,
                  direction: str, entry_price: float) -> float:
        """진입 방향의 최근 매물대(swing point)를 TP1으로 설정"""
        start = max(0, bar_idx - 50)
        window = df.iloc[start:bar_idx + 1]
        if direction == "Long":
            if "swing_high" in window.columns:
                swing_highs = window.loc[window["swing_high"], "high"]
                candidates = swing_highs[swing_highs > entry_price]
                if len(candidates) > 0:
                    return float(candidates.iloc[-1])
            return float(window["high"].max())
        else:
            if "swing_low" in window.columns:
                swing_lows = window.loc[window["swing_low"], "low"]
                candidates = swing_lows[swing_lows < entry_price]
                if len(candidates) > 0:
                    return float(candidates.iloc[-1])
            return float(window["low"].min())

    @staticmethod
    def _detect_counter_fvg(df: pd.DataFrame, bar_idx: int, direction: str) -> bool:
        """현재 봉 기준 역방향 FVG 존재 여부"""
        if bar_idx < 2:
            return False
        i = bar_idx
        if direction == "Long":
            return float(df["high"].iloc[i]) < float(df["low"].iloc[i - 2])
        else:
            return float(df["low"].iloc[i]) > float(df["high"].iloc[i - 2])

    # ─── 신호 생성 ───

    def _generate_signals_at_bar(
        self, df: pd.DataFrame, bar_idx: int, htf_bias: str
    ) -> list[BacktestSignal]:
        """bar_idx 시점까지의 최근 200봉으로 신호 생성"""
        signals = []
        start = max(0, bar_idx - 200)
        window = df.iloc[start:bar_idx + 1]
        if len(window) < 20:
            return signals

        filters = self.config.get("filters", {})
        execution = self.config.get("execution", {})
        fvg_only = execution.get("fvg_only", False)
        entry = window["close"].iloc[-1]
        atr_val = window["atr"].iloc[-1] if "atr" in window.columns and pd.notna(window["atr"].iloc[-1]) else entry * 0.005
        date_str = str(window.index[-1])[:19]

        # 1. Structure Shift (skip in FVG Only mode)
        if not fvg_only:
            shift = self.ta.detect_structure_shift(window)
            if shift["detected"]:
                direction = Direction.LONG if shift["direction"] == "bullish" else Direction.SHORT

                # Counter-HTF block
                counter_blocked = filters.get("block_counter_htf", False) and (
                    (direction == Direction.LONG and "Strong Bear" in htf_bias) or
                    (direction == Direction.SHORT and "Strong Bull" in htf_bias)
                )
                if not counter_blocked:
                    confidence = 75
                    if (direction == Direction.LONG and "Bull" in htf_bias) or \
                       (direction == Direction.SHORT and "Bear" in htf_bias):
                        confidence += 10

                    sl = entry - 2 * atr_val if direction == Direction.LONG else entry + 2 * atr_val
                    tp = entry + 4 * atr_val if direction == Direction.LONG else entry - 4 * atr_val
                    rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

                    if rr >= self.config["min_rr_ratio"]:
                        signals.append(BacktestSignal(
                            bar_index=bar_idx, date=date_str,
                            signal_type=SignalType.STRUCTURE_SHIFT.value,
                            direction=direction.value, confidence=min(confidence, 95),
                            entry_price=entry, stop_loss=sl, take_profit=tp,
                            rr_ratio=round(rr, 2), htf_bias=htf_bias,
                            reason=shift["description"],
                        ))

        # 2. FVG
        fvgs = self.ta.detect_fvg(window)
        recent_fvgs = [f for f in fvgs if f["index"] >= len(window) - 5]
        for fvg in recent_fvgs[-2:]:
            direction = Direction.LONG if fvg["type"] == "bullish" else Direction.SHORT
            if ("Bull" in htf_bias and direction == Direction.LONG) or \
               ("Bear" in htf_bias and direction == Direction.SHORT):
                fvg_entry = (fvg["top"] + fvg["bottom"]) / 2
                gap_size = abs(fvg["top"] - fvg["bottom"])

                # FVG gap minimum size filter
                fvg_min_gap_pct = filters.get("fvg_min_gap_pct", 0)
                if fvg_min_gap_pct > 0 and fvg_entry > 0 and (gap_size / fvg_entry) < fvg_min_gap_pct:
                    continue

                sl = fvg["bottom"] - gap_size * 0.5 if direction == Direction.LONG else fvg["top"] + gap_size * 0.5
                tp = fvg_entry + gap_size * 3 if direction == Direction.LONG else fvg_entry - gap_size * 3
                rr = abs(tp - fvg_entry) / abs(fvg_entry - sl) if abs(fvg_entry - sl) > 0 else 0

                if rr >= self.config["min_rr_ratio"]:
                    signals.append(BacktestSignal(
                        bar_index=bar_idx, date=date_str,
                        signal_type=SignalType.FVG_ENTRY.value,
                        direction=direction.value, confidence=80,
                        entry_price=round(fvg_entry, 2), stop_loss=round(sl, 2),
                        take_profit=round(tp, 2), rr_ratio=round(rr, 2),
                        htf_bias=htf_bias,
                        reason=f"{fvg['type'].title()} FVG",
                    ))

        # 3. RSI Divergence (skip in FVG Only mode)
        if not fvg_only:
            divs = self.ta.detect_rsi_divergence(window)
            for div in divs:
                direction = Direction.LONG if div["type"] == "bullish" else Direction.SHORT
                # RSI Divergence Short disable
                if filters.get("disable_rsi_divergence_short", False) and direction == Direction.SHORT:
                    continue
                # RSI Divergence counter-HTF block
                if filters.get("block_counter_htf", False) and (
                    (direction == Direction.LONG and "Strong Bear" in htf_bias) or
                    (direction == Direction.SHORT and "Strong Bull" in htf_bias)
                ):
                    continue
                sl = entry - 2 * atr_val if direction == Direction.LONG else entry + 2 * atr_val
                tp = entry + 4 * atr_val if direction == Direction.LONG else entry - 4 * atr_val
                rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

                if rr >= self.config["min_rr_ratio"]:
                    signals.append(BacktestSignal(
                        bar_index=bar_idx, date=date_str,
                        signal_type=SignalType.RSI_DIVERGENCE.value,
                        direction=direction.value, confidence=55,
                        entry_price=round(entry, 2), stop_loss=round(sl, 2),
                        take_profit=round(tp, 2), rr_ratio=round(rr, 2),
                        htf_bias=htf_bias,
                        reason=f"{div['type'].title()} RSI Div (RSI: {div['rsi']:.1f})",
                    ))

        return signals

    # ─── 메인 루프 ───

    def run(self) -> list[BacktestTrade]:
        """Bar-by-bar forward walking backtest (15min)"""
        df_raw = self.fetch_data()
        if len(df_raw) < self.WARMUP + 100:
            print(f"❌ 데이터 부족: {len(df_raw)}봉 (최소 {self.WARMUP + 100} 필요)")
            return []

        # 지표 추가
        df = self.ta.add_indicators(df_raw.copy(), self.config)
        df = self.ta.detect_swing_points(df)

        # 4시간봉 HTF
        df_4h_full = self.to_4h(df_raw)
        df_4h_full = self.ta.add_indicators(df_4h_full, self.config)

        total_bars = len(df)
        test_start = self.WARMUP
        test_end = total_bars

        print(f"\n🔄 Forward Walk 시작 (15min)")
        print(f"   Warmup: {self.WARMUP}봉 | 테스트: {test_end - test_start}봉")
        print(f"   구간: {df.index[test_start].strftime('%Y-%m-%d %H:%M')} ~ {df.index[-1].strftime('%Y-%m-%d %H:%M')}")
        print()

        # Execution parameters
        execution = self.config.get("execution", {})
        entry_delay = execution.get("entry_delay_bars", 0)
        use_trailing = execution.get("use_trailing_exit", False)
        tp1_partial = execution.get("tp1_partial_pct", 0.5)

        open_trade: Optional[BacktestTrade] = None
        pending_signal: Optional[BacktestSignal] = None
        pending_delay: int = 0
        last_signal_bar: dict[str, int] = {}
        signal_count = 0
        skipped_dup = 0

        for i in range(test_start, test_end):
            bar_date = str(df.index[i])[:19]

            # ── 0. Pending signal → 딜레이 후 진입 (next bar open) ──
            if pending_signal is not None and open_trade is None:
                pending_delay -= 1
                if pending_delay <= 0:
                    actual_entry = df["open"].iloc[i]
                    sig = pending_signal
                    sl_dist = abs(sig.entry_price - sig.stop_loss)
                    if sig.direction == "Long":
                        actual_sl = actual_entry - sl_dist
                    else:
                        actual_sl = actual_entry + sl_dist

                    if use_trailing:
                        tp1 = self._find_tp1(df, i, sig.direction, actual_entry)
                        if abs(tp1 - actual_entry) < sl_dist:
                            tp1 = actual_entry + sl_dist if sig.direction == "Long" else actual_entry - sl_dist
                    else:
                        tp_dist = abs(sig.take_profit - sig.entry_price)
                        tp1 = actual_entry + tp_dist if sig.direction == "Long" else actual_entry - tp_dist

                    open_trade = BacktestTrade(
                        entry_bar=i,
                        entry_date=bar_date,
                        signal_type=sig.signal_type,
                        direction=sig.direction,
                        confidence=sig.confidence,
                        entry_price=actual_entry,
                        stop_loss=actual_sl,
                        take_profit=tp1,
                        rr_ratio=sig.rr_ratio,
                        htf_bias=sig.htf_bias,
                        tp1_price=tp1 if use_trailing else None,
                    )
                    pending_signal = None

            # ── 1. 오픈 포지션 관리 (상태 머신) ──
            if open_trade is not None:
                bar_high = df["high"].iloc[i]
                bar_low = df["low"].iloc[i]
                bar_close = df["close"].iloc[i]
                is_long = open_trade.direction == "Long"

                if use_trailing and not open_trade.tp1_hit:
                    # === Phase 1: TP1 전 — SL 또는 TP1 대기 ===
                    current_sl = open_trade.stop_loss
                    tp1 = open_trade.tp1_price

                    hit_sl = (bar_low <= current_sl) if is_long else (bar_high >= current_sl)
                    hit_tp1 = (bar_high >= tp1) if is_long else (bar_low <= tp1)

                    if hit_sl and hit_tp1:
                        open_trade.same_bar_conflict = True

                    if hit_sl:
                        self._close_trade(open_trade, current_sl, i, bar_date, "SL")
                        open_trade = None
                    elif hit_tp1:
                        open_trade.tp1_hit = True
                        open_trade.tp1_bar = i
                        if is_long:
                            open_trade.tp1_pnl = (tp1 - open_trade.entry_price) * tp1_partial
                        else:
                            open_trade.tp1_pnl = (open_trade.entry_price - tp1) * tp1_partial
                        open_trade.position_size = 1.0 - tp1_partial
                        open_trade.trailing_sl = open_trade.entry_price

                elif use_trailing and open_trade.tp1_hit:
                    # === Phase 2: TP1 후 — trailing ===
                    be_sl = open_trade.trailing_sl

                    hit_be = (bar_low <= be_sl) if is_long else (bar_high >= be_sl)
                    counter_fvg = self._detect_counter_fvg(df, i, open_trade.direction)

                    if hit_be:
                        self._close_trade(open_trade, be_sl, i, bar_date, "BE")
                        open_trade = None
                    elif counter_fvg:
                        self._close_trade(open_trade, bar_close, i, bar_date, "COUNTER_FVG")
                        open_trade = None
                    elif (i - open_trade.entry_bar) >= self.MAX_HOLD_BARS:
                        self._close_trade(open_trade, bar_close, i, bar_date, "TIMEOUT")
                        open_trade = None

                else:
                    # === Non-trailing mode ===
                    hit_sl = (bar_low <= open_trade.stop_loss) if is_long else (bar_high >= open_trade.stop_loss)
                    hit_tp = (bar_high >= open_trade.take_profit) if is_long else (bar_low <= open_trade.take_profit)

                    if hit_sl and hit_tp:
                        open_trade.same_bar_conflict = True
                    if hit_sl:
                        self._close_trade(open_trade, open_trade.stop_loss, i, bar_date, "SL")
                        open_trade = None
                    elif hit_tp:
                        self._close_trade(open_trade, open_trade.take_profit, i, bar_date, "TP")
                        open_trade = None
                    elif (i - open_trade.entry_bar) >= self.MAX_HOLD_BARS:
                        self._close_trade(open_trade, bar_close, i, bar_date, "TIMEOUT")
                        open_trade = None

            # ── 2. 포지션 없고 pending도 없으면 신호 탐색 ──
            if open_trade is None and pending_signal is None:
                current_ts = df.index[i]
                h4_up_to = df_4h_full[df_4h_full.index < current_ts]
                htf_bias = self.ta.determine_htf_bias(h4_up_to) if len(h4_up_to) >= 10 else "Neutral"

                filters = self.config.get("filters", {})
                if filters.get("skip_htf_neutral", False) and htf_bias == "Neutral":
                    continue

                signals = self._generate_signals_at_bar(df, i, htf_bias)

                for sig in signals:
                    dedupe_key = f"{sig.signal_type}_{sig.direction}"
                    last_bar = last_signal_bar.get(dedupe_key, -999)
                    if i - last_bar < self.SIGNAL_COOLDOWN:
                        skipped_dup += 1
                        continue

                    signal_count += 1
                    last_signal_bar[dedupe_key] = i

                    if entry_delay > 0:
                        pending_signal = sig
                        pending_delay = entry_delay
                    else:
                        tp1 = None
                        if use_trailing:
                            tp1 = self._find_tp1(df, i, sig.direction, sig.entry_price)
                            if abs(tp1 - sig.entry_price) < abs(sig.entry_price - sig.stop_loss):
                                sl_d = abs(sig.entry_price - sig.stop_loss)
                                tp1 = sig.entry_price + sl_d if sig.direction == "Long" else sig.entry_price - sl_d
                        open_trade = BacktestTrade(
                            entry_bar=i,
                            entry_date=sig.date,
                            signal_type=sig.signal_type,
                            direction=sig.direction,
                            confidence=sig.confidence,
                            entry_price=sig.entry_price,
                            stop_loss=sig.stop_loss,
                            take_profit=tp1 or sig.take_profit,
                            rr_ratio=sig.rr_ratio,
                            htf_bias=sig.htf_bias,
                            tp1_price=tp1,
                        )
                    break

            # 진행률
            progress_step = max(1, (test_end - test_start) // 8)
            if (i - test_start) % progress_step == 0 and i > test_start:
                pct = (i - test_start) / (test_end - test_start) * 100
                print(f"   ... {pct:.0f}% ({i - test_start}/{test_end - test_start}봉)")

        if open_trade is not None:
            self._close_trade(
                open_trade, df["close"].iloc[-1],
                len(df) - 1, str(df.index[-1])[:19], "END"
            )

        print(f"\n✅ Forward Walk 완료 (15min)")
        print(f"   총 신호: {signal_count} | 중복 스킵: {skipped_dup} | 총 거래: {len(self.trades)}")

        return self.trades

    def _close_trade(self, trade: BacktestTrade, exit_price: float,
                     exit_bar: int, exit_date: str, exit_reason: str):
        """포지션 청산 — 슬리피지·수수료·분할익절 반영"""
        execution = self.config.get("execution", {})
        slippage_pct = execution.get("slippage_pct", 0) / 100
        fee_pct = execution.get("fee_pct", 0) / 100

        if slippage_pct > 0:
            if trade.direction == "Long":
                exit_price = exit_price * (1 - slippage_pct)
            else:
                exit_price = exit_price * (1 + slippage_pct)

        trade.exit_bar = exit_bar
        trade.exit_date = exit_date
        trade.exit_price = round(exit_price, 2)
        trade.exit_reason = exit_reason

        entry = trade.entry_price
        is_long = trade.direction == "Long"

        if trade.tp1_hit and trade.tp1_pnl is not None:
            remaining_raw = (exit_price - entry) if is_long else (entry - exit_price)
            remaining_pnl = remaining_raw * trade.position_size
            tp1_partial = 1.0 - trade.position_size
            fee_tp1 = (entry * fee_pct + trade.tp1_price * fee_pct) * tp1_partial
            fee_final = (entry * fee_pct + exit_price * fee_pct) * trade.position_size
            fee_cost = fee_tp1 + fee_final
            tp1_pnl = trade.tp1_pnl
            if slippage_pct > 0:
                tp1_pnl = tp1_pnl * (1 - slippage_pct)
            trade.pnl = tp1_pnl + remaining_pnl - fee_cost
        else:
            raw_pnl = (exit_price - entry) if is_long else (entry - exit_price)
            fee_cost = entry * fee_pct + exit_price * fee_pct
            trade.pnl = raw_pnl - fee_cost

        trade.fee_cost = round(fee_cost, 2)
        risk = abs(entry - trade.stop_loss)
        trade.r_multiple = round(trade.pnl / risk, 2) if risk > 0 else 0.0
        self.trades.append(trade)


# ═══════════════════════════════════════
# 교차 분석 (일봉 vs 15분봉)
# ═══════════════════════════════════════

def cross_analysis(trades: list[BacktestTrade]):
    """일봉 백테스트 인사이트가 15분봉에서도 유효한지 검증"""
    print("\n" + "═" * 60)
    print("  🔬 일봉 인사이트 vs 15분봉 검증")
    print("═" * 60)

    # 인사이트 1: FVG가 핵심 알파인가?
    print("\n  ① FVG Entry가 여전히 핵심 알파인가?")
    print(f"  {'─' * 50}")
    setups = sorted(set(t.signal_type for t in trades))
    for st in setups:
        subset = [t for t in trades if t.signal_type == st]
        wins = [t for t in subset if t.pnl > 0]
        r_vals = [t.r_multiple for t in subset]
        wr = len(wins) / len(subset) * 100 if subset else 0
        print(f"  {st:20s}  {len(subset):3d}건  승률 {wr:5.1f}%  avgR {np.mean(r_vals):+.2f}  totR {sum(r_vals):+.2f}")

    # 인사이트 2: HTF Neutral에서 진입하면 손실인가?
    print(f"\n  ② HTF Bias Neutral에서 진입 = 손실?")
    print(f"  {'─' * 50}")
    for bias in sorted(set(t.htf_bias for t in trades)):
        subset = [t for t in trades if t.htf_bias == bias]
        if not subset:
            continue
        wins = [t for t in subset if t.pnl > 0]
        r_vals = [t.r_multiple for t in subset]
        wr = len(wins) / len(subset) * 100
        marker = " ← 검증 대상" if bias == "Neutral" else ""
        print(f"  {bias:16s}  {len(subset):3d}건  승률 {wr:5.1f}%  avgR {np.mean(r_vals):+.2f}  totR {sum(r_vals):+.2f}{marker}")

    # 인사이트 3: 셋업 × 방향
    print(f"\n  ③ 셋업별 Long/Short 선호도")
    print(f"  {'─' * 50}")
    for st in setups:
        for direction in ["Long", "Short"]:
            subset = [t for t in trades if t.signal_type == st and t.direction == direction]
            if not subset:
                continue
            wins = [t for t in subset if t.pnl > 0]
            r_vals = [t.r_multiple for t in subset]
            wr = len(wins) / len(subset) * 100
            print(f"  {st:20s} {direction:6s}  {len(subset):3d}건  승률 {wr:5.1f}%  avgR {np.mean(r_vals):+.2f}  totR {sum(r_vals):+.2f}")

    # 인사이트 4: Strong Bullish에서 Short 금지 유효?
    print(f"\n  ④ Strong Bullish + Short = 위험?")
    print(f"  {'─' * 50}")
    for bias in ["Strong Bullish", "Strong Bearish"]:
        for direction in ["Long", "Short"]:
            subset = [t for t in trades if t.htf_bias == bias and t.direction == direction]
            if not subset:
                continue
            wins = [t for t in subset if t.pnl > 0]
            r_vals = [t.r_multiple for t in subset]
            wr = len(wins) / len(subset) * 100
            marker = " ← 금지 규칙" if bias == "Strong Bullish" and direction == "Short" else ""
            print(f"  {bias:16s} {direction:6s}  {len(subset):3d}건  승률 {wr:5.1f}%  avgR {np.mean(r_vals):+.2f}{marker}")

    # 인사이트 5: RSI Divergence Short 폐기 유효?
    print(f"\n  ⑤ RSI Divergence Short 폐기 유효?")
    print(f"  {'─' * 50}")
    for direction in ["Long", "Short"]:
        subset = [t for t in trades if t.signal_type == "RSI Divergence" and t.direction == direction]
        if not subset:
            print(f"  RSI Div {direction:6s}: 거래 없음")
            continue
        wins = [t for t in subset if t.pnl > 0]
        r_vals = [t.r_multiple for t in subset]
        wr = len(wins) / len(subset) * 100
        print(f"  RSI Div {direction:6s}  {len(subset):3d}건  승률 {wr:5.1f}%  avgR {np.mean(r_vals):+.2f}  totR {sum(r_vals):+.2f}")

    print("\n" + "═" * 60)


# ═══════════════════════════════════════
# 메인
# ═══════════════════════════════════════

def main():
    import os
    config = DEFAULT_CONFIG.copy()
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            user_config = json.load(f)
            config = deep_merge(config, user_config)

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║  ⚡ Forward Walk Backtest — BTC-USDT 15min              ║
    ║  HTF = 4H, Bar-by-bar, No Future Leakage               ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    bt = ForwardWalkBacktest15m(config)
    trades = bt.run()

    if trades:
        analyzer = BacktestAnalyzer(trades, seed_capital=config["seed_capital"])
        analyzer.print_report()
        analyzer.save_results("backtest_15m_result.json")
        cross_analysis(trades)
    else:
        print("⚠️ 거래 없음")


if __name__ == "__main__":
    main()
