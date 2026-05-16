"""
⚡ Structural Edge - Forward Walking Backtest
=============================================
BTC-USD 일봉 기반, bar-by-bar forward walk.
Yahoo Finance 5년 데이터 사용.

사용법:
  python backtest.py
"""

import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
import numpy as np

from signal_engine import (
    TechnicalAnalysis, SignalType, Direction, DEFAULT_CONFIG, deep_merge,
)


# ═══════════════════════════════════════
# 데이터 모델
# ═══════════════════════════════════════

@dataclass
class BacktestSignal:
    bar_index: int
    date: str
    signal_type: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    htf_bias: str
    reason: str


@dataclass
class BacktestTrade:
    entry_bar: int
    entry_date: str
    signal_type: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    htf_bias: str
    exit_bar: Optional[int] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "SL", "TP1", "BE", "COUNTER_FVG", "TIMEOUT"
    pnl: Optional[float] = None
    r_multiple: Optional[float] = None
    fee_cost: Optional[float] = None
    same_bar_conflict: bool = False
    # Trailing exit fields
    tp1_price: Optional[float] = None
    tp1_hit: bool = False
    tp1_bar: Optional[int] = None
    tp1_pnl: Optional[float] = None
    position_size: float = 1.0
    trailing_sl: Optional[float] = None


# ═══════════════════════════════════════
# Forward Walking Backtest
# ═══════════════════════════════════════

class ForwardWalkBacktest:

    WARMUP = 200          # 지표 계산 warmup 봉 수
    MAX_HOLD_BARS = 60    # 최대 보유 기간 (60일봉 = ~2개월)
    SIGNAL_COOLDOWN = 5   # 동일 신호 재발생 쿨다운 (봉)

    def __init__(self, config: dict = None):
        self.config = config or DEFAULT_CONFIG
        self.ta = TechnicalAnalysis()
        self.trades: list[BacktestTrade] = []

    # ─── 데이터 수집 ───

    def fetch_data(self) -> pd.DataFrame:
        """Yahoo Finance에서 BTC-USD 5년 일봉 수집"""
        print("📥 BTC-USD 5년 일봉 데이터 수집 중...")
        ticker = yf.Ticker("BTC-USD")
        df = ticker.history(period="5y", interval="1d")
        df.columns = [c.lower() for c in df.columns]
        print(f"   수집 완료: {len(df)}봉 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")
        return df

    @staticmethod
    def daily_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
        """일봉 → 주봉 리샘플링 (완성된 주만)"""
        weekly = df.resample('W-SUN').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }).dropna()
        return weekly

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

    # ─── 신호 생성 (단일 바 기준) ───

    def _generate_signals_at_bar(
        self, df: pd.DataFrame, bar_idx: int, htf_bias: str
    ) -> list[BacktestSignal]:
        """
        bar_idx 시점까지의 데이터로 신호 생성.
        future leakage 방지: df.iloc[:bar_idx+1] 만 사용.
        """
        signals = []
        window = df.iloc[:bar_idx + 1]
        if len(window) < 20:
            return signals

        filters = self.config.get("filters", {})
        execution = self.config.get("execution", {})
        fvg_only = execution.get("fvg_only", False)
        entry = window["close"].iloc[-1]
        atr = window["atr"].iloc[-1] if "atr" in window.columns and pd.notna(window["atr"].iloc[-1]) else entry * 0.02
        date_str = str(window.index[-1])[:10]

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

                    sl = entry - 2 * atr if direction == Direction.LONG else entry + 2 * atr
                    tp = entry + 4 * atr if direction == Direction.LONG else entry - 4 * atr
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
        # 최근 5봉 내 FVG만
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
                sl = entry - 2 * atr if direction == Direction.LONG else entry + 2 * atr
                tp = entry + 4 * atr if direction == Direction.LONG else entry - 4 * atr
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
        """Bar-by-bar forward walking backtest 실행"""
        df_raw = self.fetch_data()
        if len(df_raw) < self.WARMUP + 50:
            print("❌ 데이터 부족")
            return []

        # 전체 데이터에 지표 추가 (계산용 — 접근은 bar_idx까지만)
        # 주의: rolling 지표이므로 iloc[:bar_idx+1]로 슬라이스해도
        # 해당 시점까지의 값만 사용됨 (future leakage 없음)
        df = self.ta.add_indicators(df_raw.copy(), self.config)
        df = self.ta.detect_swing_points(df)

        # 주봉 데이터 (HTF bias용)
        df_weekly_full = self.daily_to_weekly(df_raw)
        df_weekly_full = self.ta.add_indicators(df_weekly_full, self.config)

        total_bars = len(df)
        test_start = self.WARMUP
        test_end = total_bars

        print(f"\n🔄 Forward Walk 시작")
        print(f"   Warmup: {test_start}봉 | 테스트: {test_end - test_start}봉")
        print(f"   구간: {df.index[test_start].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
        print()

        # Execution parameters
        execution = self.config.get("execution", {})
        entry_delay = execution.get("entry_delay_bars", 0)
        use_trailing = execution.get("use_trailing_exit", False)
        tp1_partial = execution.get("tp1_partial_pct", 0.5)

        # 상태 변수
        open_trade: Optional[BacktestTrade] = None
        pending_signal: Optional[BacktestSignal] = None
        pending_delay: int = 0
        last_signal_bar: dict[str, int] = {}

        signal_count = 0
        skipped_dup = 0

        for i in range(test_start, test_end):
            bar_date = str(df.index[i])[:10]

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

                    # TP1: 매물대 기반 (trailing mode) or 고정 TP
                    if use_trailing:
                        tp1 = self._find_tp1(df, i, sig.direction, actual_entry)
                        # TP1이 entry와 너무 가까우면 최소 sl_dist 보장
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
                        # 50% 익절, SL → breakeven
                        open_trade.tp1_hit = True
                        open_trade.tp1_bar = i
                        if is_long:
                            open_trade.tp1_pnl = (tp1 - open_trade.entry_price) * tp1_partial
                        else:
                            open_trade.tp1_pnl = (open_trade.entry_price - tp1) * tp1_partial
                        open_trade.position_size = 1.0 - tp1_partial
                        open_trade.trailing_sl = open_trade.entry_price  # breakeven

                elif use_trailing and open_trade.tp1_hit:
                    # === Phase 2: TP1 후 — trailing (breakeven SL + counter FVG) ===
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
                    # === Non-trailing mode (기존 방식) ===
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
                current_date = df.index[i]
                weekly_up_to = df_weekly_full[df_weekly_full.index < current_date]
                htf_bias = self.ta.determine_htf_bias(weekly_up_to) if len(weekly_up_to) >= 10 else "Neutral"

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

            # 진행률 표시
            if (i - test_start) % 200 == 0 and i > test_start:
                pct = (i - test_start) / (test_end - test_start) * 100
                print(f"   ... {pct:.0f}% ({i - test_start}/{test_end - test_start}봉)")

        # 마지막 미청산 포지션 강제 청산
        if open_trade is not None:
            self._close_trade(
                open_trade, df["close"].iloc[-1],
                len(df) - 1, str(df.index[-1])[:10], "END"
            )

        print(f"\n✅ Forward Walk 완료")
        print(f"   총 신호: {signal_count} | 중복 스킵: {skipped_dup} | 총 거래: {len(self.trades)}")

        return self.trades

    def _close_trade(self, trade: BacktestTrade, exit_price: float,
                     exit_bar: int, exit_date: str, exit_reason: str):
        """포지션 청산 — 슬리피지·수수료·분할익절 반영"""
        execution = self.config.get("execution", {})
        slippage_pct = execution.get("slippage_pct", 0) / 100
        fee_pct = execution.get("fee_pct", 0) / 100

        # 슬리피지: 불리한 방향으로 적용
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
            # 분할 익절 모드: TP1 50% PnL + 나머지 비율의 최종 PnL
            remaining_raw = (exit_price - entry) if is_long else (entry - exit_price)
            remaining_pnl = remaining_raw * trade.position_size
            # 수수료: TP1 청산분(50%) + 최종 청산분(나머지)
            tp1_partial = 1.0 - trade.position_size
            fee_tp1 = (entry * fee_pct + trade.tp1_price * fee_pct) * tp1_partial
            fee_final = (entry * fee_pct + exit_price * fee_pct) * trade.position_size
            fee_cost = fee_tp1 + fee_final
            # TP1 PnL에도 슬리피지 적용 (TP1 체결 시)
            tp1_pnl = trade.tp1_pnl
            if slippage_pct > 0:
                tp1_pnl = tp1_pnl * (1 - slippage_pct)
            trade.pnl = tp1_pnl + remaining_pnl - fee_cost
        else:
            # 단일 청산 (SL 등)
            raw_pnl = (exit_price - entry) if is_long else (entry - exit_price)
            fee_cost = entry * fee_pct + exit_price * fee_pct
            trade.pnl = raw_pnl - fee_cost

        trade.fee_cost = round(fee_cost, 2)
        risk = abs(entry - trade.stop_loss)
        trade.r_multiple = round(trade.pnl / risk, 2) if risk > 0 else 0.0

        self.trades.append(trade)


# ═══════════════════════════════════════
# 결과 분석
# ═══════════════════════════════════════

class BacktestAnalyzer:

    def __init__(self, trades: list[BacktestTrade], seed_capital: float = 10_000_000):
        self.trades = trades
        self.seed = seed_capital

    def compute_stats(self) -> dict:
        if not self.trades:
            return {"error": "거래 없음"}

        r_multiples = [t.r_multiple for t in self.trades]
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]

        win_rate = len(wins) / len(self.trades) * 100
        avg_r = np.mean(r_multiples)
        avg_win_r = np.mean([t.r_multiple for t in wins]) if wins else 0
        avg_loss_r = np.mean([t.r_multiple for t in losses]) if losses else 0

        # Expectancy = (WinRate × AvgWin) + (LossRate × AvgLoss)
        expectancy = (win_rate / 100 * avg_win_r) + ((1 - win_rate / 100) * avg_loss_r)

        # Profit Factor = Gross Profit / Gross Loss
        gross_profit = sum(t.r_multiple for t in wins) if wins else 0
        gross_loss = abs(sum(t.r_multiple for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Max Drawdown (R-multiple 기반 누적 equity curve)
        cumulative = np.cumsum(r_multiples)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = cumulative - running_max
        max_dd_r = float(drawdowns.min())

        # Max Drawdown % (seed 4.5% risk per trade 기준)
        risk_per_trade = self.seed * 0.045
        equity_curve = [self.seed]
        for r in r_multiples:
            equity_curve.append(equity_curve[-1] + r * risk_per_trade)
        equity_arr = np.array(equity_curve)
        eq_max = np.maximum.accumulate(equity_arr)
        dd_pct = (equity_arr - eq_max) / eq_max * 100
        max_dd_pct = float(dd_pct.min())

        # Realism metrics
        total_fees = sum(t.fee_cost for t in self.trades if t.fee_cost)
        same_bar_conflicts = sum(1 for t in self.trades if t.same_bar_conflict)

        # Average bars between trades
        entry_bars = sorted(t.entry_bar for t in self.trades)
        if len(entry_bars) >= 2:
            gaps = [entry_bars[j] - entry_bars[j-1] for j in range(1, len(entry_bars))]
            avg_gap = np.mean(gaps)
            immediate_reentry = sum(1 for g in gaps if g <= 1)
        else:
            avg_gap = 0
            immediate_reentry = 0

        # TP1 trailing metrics
        tp1_trades = [t for t in self.trades if t.tp1_hit]
        tp1_hit_rate = len(tp1_trades) / len(self.trades) * 100 if self.trades else 0

        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "avg_r": round(avg_r, 2),
            "avg_win_r": round(avg_win_r, 2),
            "avg_loss_r": round(avg_loss_r, 2),
            "expectancy": round(expectancy, 3),
            "profit_factor": round(profit_factor, 2),
            "max_dd_r": round(max_dd_r, 2),
            "max_dd_pct": round(max_dd_pct, 1),
            "total_r": round(sum(r_multiples), 2),
            "final_equity": round(equity_curve[-1]),
            "total_fees": round(total_fees, 2),
            "same_bar_conflicts": same_bar_conflicts,
            "avg_bars_between_trades": round(avg_gap, 1),
            "immediate_reentry_count": immediate_reentry,
            "tp1_hit_rate": round(tp1_hit_rate, 1),
            "tp1_hit_count": len(tp1_trades),
        }

    def stats_by_setup_type(self) -> dict:
        """셋업 유형별 통계"""
        types = set(t.signal_type for t in self.trades)
        result = {}
        for st in sorted(types):
            subset = [t for t in self.trades if t.signal_type == st]
            wins = [t for t in subset if t.pnl > 0]
            r_vals = [t.r_multiple for t in subset]
            result[st] = {
                "trades": len(subset),
                "win_rate": round(len(wins) / len(subset) * 100, 1) if subset else 0,
                "avg_r": round(np.mean(r_vals), 2),
                "total_r": round(sum(r_vals), 2),
            }
        return result

    def stats_by_confidence(self) -> dict:
        """신뢰도 구간별 통계"""
        buckets = {"50-64": (50, 64), "65-74": (65, 74), "75-84": (75, 84), "85+": (85, 100)}
        result = {}
        for label, (lo, hi) in buckets.items():
            subset = [t for t in self.trades if lo <= t.confidence <= hi]
            if not subset:
                continue
            wins = [t for t in subset if t.pnl > 0]
            r_vals = [t.r_multiple for t in subset]
            result[label] = {
                "trades": len(subset),
                "win_rate": round(len(wins) / len(subset) * 100, 1),
                "avg_r": round(np.mean(r_vals), 2),
                "total_r": round(sum(r_vals), 2),
            }
        return result

    def stats_by_exit_reason(self) -> dict:
        """청산 사유별 통계"""
        reasons = set(t.exit_reason for t in self.trades)
        result = {}
        for reason in sorted(reasons):
            subset = [t for t in self.trades if t.exit_reason == reason]
            r_vals = [t.r_multiple for t in subset]
            result[reason] = {
                "trades": len(subset),
                "avg_r": round(np.mean(r_vals), 2),
            }
        return result

    def stats_by_htf_bias(self) -> dict:
        """HTF Bias별 통계"""
        biases = set(t.htf_bias for t in self.trades)
        result = {}
        for bias in sorted(biases):
            subset = [t for t in self.trades if t.htf_bias == bias]
            if not subset:
                continue
            wins = [t for t in subset if t.pnl > 0]
            r_vals = [t.r_multiple for t in subset]
            result[bias] = {
                "trades": len(subset),
                "win_rate": round(len(wins) / len(subset) * 100, 1),
                "avg_r": round(np.mean(r_vals), 2),
            }
        return result

    def print_report(self):
        """전체 리포트 출력"""
        stats = self.compute_stats()

        print("\n" + "═" * 60)
        print("  ⚡ FORWARD WALK BACKTEST REPORT — BTC-USD")
        print("═" * 60)

        print(f"\n  📊 전체 성과")
        print(f"  {'─' * 40}")
        print(f"  총 거래        : {stats['total_trades']}")
        print(f"  승/패          : {stats['wins']}W / {stats['losses']}L")
        print(f"  승률           : {stats['win_rate']}%")
        print(f"  평균 R         : {stats['avg_r']}R")
        print(f"  평균 승 R      : {stats['avg_win_r']}R")
        print(f"  평균 패 R      : {stats['avg_loss_r']}R")
        print(f"  Expectancy     : {stats['expectancy']}R")
        print(f"  Profit Factor  : {stats['profit_factor']}")
        print(f"  누적 R         : {stats['total_r']}R")
        print(f"  Max Drawdown   : {stats['max_dd_r']}R ({stats['max_dd_pct']}%)")
        print(f"  최종 자산       : ₩{stats['final_equity']:,}")

        # 실행 현실성
        print(f"\n  🔧 실행 현실성")
        print(f"  {'─' * 40}")
        print(f"  총 수수료       : ₩{stats.get('total_fees', 0):,.0f}")
        print(f"  SL/TP 동시터치  : {stats.get('same_bar_conflicts', 0)}건")
        print(f"  평균 거래 간격  : {stats.get('avg_bars_between_trades', 0):.1f}봉")
        print(f"  즉시 재진입     : {stats.get('immediate_reentry_count', 0)}건")
        if stats.get('tp1_hit_count', 0) > 0:
            print(f"  TP1 도달률      : {stats['tp1_hit_rate']}% ({stats['tp1_hit_count']}건)")

        # 셋업 유형별
        by_type = self.stats_by_setup_type()
        print(f"\n  📋 셋업 유형별")
        print(f"  {'─' * 40}")
        for st, s in by_type.items():
            print(f"  {st:20s}  {s['trades']:3d}건  승률 {s['win_rate']:5.1f}%  avgR {s['avg_r']:+.2f}  totR {s['total_r']:+.2f}")

        # 신뢰도별
        by_conf = self.stats_by_confidence()
        if by_conf:
            print(f"\n  🎯 신뢰도 구간별")
            print(f"  {'─' * 40}")
            for label, s in by_conf.items():
                print(f"  {label:10s}  {s['trades']:3d}건  승률 {s['win_rate']:5.1f}%  avgR {s['avg_r']:+.2f}  totR {s['total_r']:+.2f}")

        # 청산 사유별
        by_exit = self.stats_by_exit_reason()
        print(f"\n  🚪 청산 사유별")
        print(f"  {'─' * 40}")
        for reason, s in by_exit.items():
            print(f"  {reason:10s}  {s['trades']:3d}건  avgR {s['avg_r']:+.2f}")

        # HTF Bias별
        by_bias = self.stats_by_htf_bias()
        if by_bias:
            print(f"\n  📈 HTF Bias별")
            print(f"  {'─' * 40}")
            for bias, s in by_bias.items():
                print(f"  {bias:16s}  {s['trades']:3d}건  승률 {s['win_rate']:5.1f}%  avgR {s['avg_r']:+.2f}")

        # 개별 거래 목록 (최근 20건)
        print(f"\n  📝 거래 목록 (최근 20건)")
        print(f"  {'─' * 70}")
        print(f"  {'날짜':12s} {'유형':20s} {'방향':6s} {'진입':>10s} {'청산':>10s} {'R':>6s} {'사유':>6s}")
        for t in self.trades[-20:]:
            print(f"  {t.entry_date:12s} {t.signal_type:20s} {t.direction:6s} "
                  f"{t.entry_price:>10.1f} {t.exit_price:>10.1f} {t.r_multiple:>+6.2f} {t.exit_reason:>6s}")

        print("\n" + "═" * 60)

    def save_results(self, filepath: str = "backtest_result.json"):
        """결과를 JSON으로 저장"""
        result = {
            "run_date": datetime.now().isoformat(),
            "asset": "BTC-USD",
            "stats": self.compute_stats(),
            "by_setup_type": self.stats_by_setup_type(),
            "by_confidence": self.stats_by_confidence(),
            "by_exit_reason": self.stats_by_exit_reason(),
            "by_htf_bias": self.stats_by_htf_bias(),
            "trades": [
                {
                    "entry_date": t.entry_date,
                    "exit_date": t.exit_date,
                    "signal_type": t.signal_type,
                    "direction": t.direction,
                    "confidence": t.confidence,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "r_multiple": t.r_multiple,
                    "exit_reason": t.exit_reason,
                    "htf_bias": t.htf_bias,
                    "fee_cost": t.fee_cost,
                    "same_bar_conflict": t.same_bar_conflict,
                }
                for t in self.trades
            ],
        }
        with open(filepath, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 결과 저장: {filepath}")


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
    ║  ⚡ Forward Walk Backtest — BTC-USD                     ║
    ║  Bar-by-bar, No Future Leakage                         ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    bt = ForwardWalkBacktest(config)
    trades = bt.run()

    if trades:
        analyzer = BacktestAnalyzer(trades, seed_capital=config["seed_capital"])
        analyzer.print_report()
        analyzer.save_results()
    else:
        print("⚠️ 거래 없음 — 신호 조건을 확인하세요.")


if __name__ == "__main__":
    main()
