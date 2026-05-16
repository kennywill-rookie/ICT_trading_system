"""
Backtest Trade Visualizer
=========================
Plotly candlestick chart with trade entry/exit overlays.

Usage:
  pip install plotly
  python3 visualize_trades.py                          # 15min default
  python3 visualize_trades.py --daily                  # daily timeframe
  python3 visualize_trades.py --signal "FVG Entry"     # filter by signal
  python3 visualize_trades.py --direction Long          # filter by direction
  python3 visualize_trades.py --start 2025-10-01 --end 2025-11-01
  python3 visualize_trades.py --max-trades 30
"""

import argparse
import json
import os
import time as _time
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    print("plotly 필요: pip install plotly")
    raise SystemExit(1)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False


# ─── OHLC Data Fetchers ───

def fetch_okx_15m(start_ts: int, end_ts: int) -> pd.DataFrame:
    """OKX BTC-USDT 15min candles between start_ts and end_ts (ms)."""
    if not HAS_REQUESTS:
        raise RuntimeError("requests 필요")

    all_data = []
    # Fetch recent first
    url = "https://www.okx.com/api/v5/market/candles"
    resp = requests.get(url, params={
        "instId": "BTC-USDT", "bar": "15m", "limit": "300"
    }, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") == "0":
        all_data.extend(body["data"])

    # Page backwards via history-candles
    url_hist = "https://www.okx.com/api/v5/market/history-candles"
    after = all_data[-1][0] if all_data else str(end_ts)

    for _ in range(200):
        resp = requests.get(url_hist, params={
            "instId": "BTC-USDT", "bar": "15m", "limit": "100", "after": after
        }, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "0" or not body.get("data"):
            break
        all_data.extend(body["data"])
        after = body["data"][-1][0]
        # Stop if we've gone past our start
        if int(after) < start_ts:
            break
        _time.sleep(0.05)

    if not all_data:
        return pd.DataFrame()

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

    # Filter to range
    start_dt = pd.Timestamp(start_ts, unit="ms")
    end_dt = pd.Timestamp(end_ts, unit="ms")
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    return df


def fetch_yahoo_daily(start_date: str, end_date: str) -> pd.DataFrame:
    """Yahoo Finance BTC-USD daily candles."""
    if not HAS_YF:
        raise RuntimeError("yfinance 필요")
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start=start_date, end=end_date, interval="1d")
    df.columns = [c.lower() for c in df.columns]
    return df


# ─── Chart Builder ───

def build_chart(df: pd.DataFrame, trades: list, timeframe: str) -> go.Figure:
    """Build plotly candlestick + volume chart with trade markers."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.8, 0.2],
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="BTC", increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # Volume
    colors = ["#26a69a" if c >= o else "#ef5350"
              for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df.index, y=df["volume"], name="Volume",
        marker_color=colors, opacity=0.5,
    ), row=2, col=1)

    # Trade overlays
    for t in trades:
        entry_dt = pd.Timestamp(t["entry_date"])
        exit_dt = pd.Timestamp(t["exit_date"]) if t.get("exit_date") else entry_dt

        is_long = t["direction"] == "Long"
        r_mult = t.get("r_multiple", 0)
        signal = t.get("signal_type", "")
        htf = t.get("htf_bias", "")
        hover_text = (
            f"{signal}<br>"
            f"{t['direction']} | HTF: {htf}<br>"
            f"Entry: {t['entry_price']:,.0f}<br>"
            f"Exit: {t.get('exit_price', 0):,.0f} ({t.get('exit_reason', '')})<br>"
            f"R: {r_mult:+.2f}"
        )

        # Entry marker
        fig.add_trace(go.Scatter(
            x=[entry_dt], y=[t["entry_price"]],
            mode="markers",
            marker=dict(
                symbol="triangle-up" if is_long else "triangle-down",
                size=12,
                color="#00c853" if is_long else "#ff1744",
                line=dict(width=1, color="white"),
            ),
            text=hover_text, hoverinfo="text",
            name=f"{'L' if is_long else 'S'} {signal[:3]}",
            showlegend=False,
        ), row=1, col=1)

        # Exit marker
        exit_price = t.get("exit_price")
        exit_reason = t.get("exit_reason", "")
        if exit_price:
            exit_symbol = {"SL": "x", "TP": "star", "TIMEOUT": "circle"}.get(exit_reason, "diamond")
            exit_color = {"SL": "#ff1744", "TP": "#00c853", "TIMEOUT": "#ffc107"}.get(exit_reason, "#9e9e9e")
            fig.add_trace(go.Scatter(
                x=[exit_dt], y=[exit_price],
                mode="markers",
                marker=dict(symbol=exit_symbol, size=10, color=exit_color,
                            line=dict(width=1, color="white")),
                text=hover_text, hoverinfo="text",
                showlegend=False,
            ), row=1, col=1)

            # SL/TP horizontal lines (entry to exit span)
            fig.add_trace(go.Scatter(
                x=[entry_dt, exit_dt], y=[t["stop_loss"], t["stop_loss"]],
                mode="lines", line=dict(color="#ff1744", width=0.8, dash="dot"),
                showlegend=False, hoverinfo="skip",
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=[entry_dt, exit_dt], y=[t["take_profit"], t["take_profit"]],
                mode="lines", line=dict(color="#00c853", width=0.8, dash="dot"),
                showlegend=False, hoverinfo="skip",
            ), row=1, col=1)

    tf_label = "15min" if timeframe == "15m" else "Daily"
    fig.update_layout(
        title=f"BTC Trade Visualization ({tf_label}) - {len(trades)} trades",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=True,
        height=800,
        margin=dict(l=60, r=30, t=50, b=30),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig


# ─── Main ───

def main():
    parser = argparse.ArgumentParser(description="Backtest Trade Visualizer")
    parser.add_argument("--daily", action="store_true", help="Use daily timeframe (default: 15min)")
    parser.add_argument("--signal", type=str, help="Filter by signal type (e.g. 'FVG Entry')")
    parser.add_argument("--direction", type=str, help="Filter by direction (Long/Short)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--max-trades", type=int, default=50, help="Max trades to display (default: 50)")
    parser.add_argument("--output", type=str, default="trade_chart.html", help="Output HTML file")
    args = parser.parse_args()

    timeframe = "1d" if args.daily else "15m"
    result_file = "backtest_result.json" if args.daily else "backtest_15m_result.json"

    if not os.path.exists(result_file):
        print(f"Result file not found: {result_file}")
        print(f"Run {'backtest.py' if args.daily else 'backtest_15m.py'} first.")
        return

    with open(result_file, "r") as f:
        data = json.load(f)

    trades = data.get("trades", [])
    print(f"Loaded {len(trades)} trades from {result_file}")

    # Apply filters
    if args.signal:
        trades = [t for t in trades if args.signal.lower() in t.get("signal_type", "").lower()]
    if args.direction:
        trades = [t for t in trades if t.get("direction", "").lower() == args.direction.lower()]
    if args.start:
        trades = [t for t in trades if t.get("entry_date", "") >= args.start]
    if args.end:
        trades = [t for t in trades if t.get("entry_date", "") <= args.end]

    if not trades:
        print("No trades match filters.")
        return

    # Limit trades
    if len(trades) > args.max_trades:
        trades = trades[:args.max_trades]
        print(f"Showing first {args.max_trades} trades")

    # Determine OHLC range (with padding)
    all_dates = []
    for t in trades:
        all_dates.append(t["entry_date"])
        if t.get("exit_date"):
            all_dates.append(t["exit_date"])
    min_date = min(all_dates)
    max_date = max(all_dates)

    print(f"Trade range: {min_date} ~ {max_date}")
    print(f"Fetching {timeframe} candle data...")

    # Fetch OHLC
    if timeframe == "15m":
        # Add padding: 1 day before and after
        start_dt = pd.Timestamp(min_date) - timedelta(days=1)
        end_dt = pd.Timestamp(max_date) + timedelta(days=1)
        df = fetch_okx_15m(int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000))
    else:
        start_dt = pd.Timestamp(min_date) - timedelta(days=5)
        end_dt = pd.Timestamp(max_date) + timedelta(days=5)
        df = fetch_yahoo_daily(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))

    if df.empty:
        print("Failed to fetch candle data.")
        return

    print(f"Candles: {len(df)} bars")

    # Build and save chart
    fig = build_chart(df, trades, timeframe)
    fig.write_html(args.output)
    print(f"Chart saved: {args.output}")


if __name__ == "__main__":
    main()
