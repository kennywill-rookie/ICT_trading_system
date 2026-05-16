"""
Augmented backtest: simulate what would have happened in paper trading
if higher_tf_trend had been computed correctly online (instead of frozen
to 0.5 due to LOOKBACK_15M=300 vs MA_PERIOD_4H=20).

Methodology
-----------
1. For each asset, fetch enough historical 15m bars (≈90 days) via OKX so
   that every live event has ≥20 prior 4H bars available.
2. Resample to 4H. For each live FVG event, locate the matching 4H bar
   (cutoff_4h_idx_eff), compute real higher_tf_trend using the SAME
   formula the training pipeline uses:
       (close_at_event - low_over_last_20_4H) / (high - low)
3. Rescore the trade with the trained model, holding all other features
   fixed (they were computed correctly in live).
4. Compare:
     - proba distribution: original (htf=0.5) vs augmented (real htf)
     - threshold selection: which trades become signals under each
     - realized R for original signals vs augmented signals
   Both run against the SAME actual_r outcomes — entries are deterministic,
   so only "which events would have triggered is_signal=True" changes.

Output
------
- ASCII tables to stdout
- tools/results_htf_fix.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs_kenny" / "ml_monitor_log.json"
MODEL_PATH = ROOT / "ml_fvg_model.pkl"
OUT_PATH = ROOT / "tools" / "results_htf_fix.json"

# Same constants as ml_data_pipeline.py
MA_PERIOD_4H = 20

FEATURE_COLS = [
    "gap_pct", "swing_count",
    "dist_to_swing_high_pct", "dist_to_swing_low_pct", "higher_tf_trend",
    "rsi_14", "rsi_delta_16bars", "bb_position", "vol_ratio", "vol_surge_15m",
    "prev_fvg_same_dir_dist", "prev_fvg_filled",
    "consecutive_dir_bars", "day_of_week", "atr_percentile",
]
ASSETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]

# Live thresholds (set on training top-30/20%)
THRESHOLD_30 = 0.6454
THRESHOLD_20 = 0.6771


# ─────────────────────────────────────────────────────────────
# Fetch historical 15m for the live event time range
# ─────────────────────────────────────────────────────────────

def fetch_15m_history(inst_id: str, bars_needed: int = 8000) -> pd.DataFrame:
    """Pull >=`bars_needed` 15m bars via OKX history-candles paging.

    8000 × 15m ≈ 83 days. Live events span ~53 days, so we need at least
    that + 20 4H bars (80h) buffer for the earliest event.
    """
    all_rows = []
    # First call: market/candles (most recent)
    r = requests.get(
        "https://www.okx.com/api/v5/market/candles",
        params={"instId": inst_id, "bar": "15m", "limit": "300"},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "0":
        raise RuntimeError(f"OKX error {inst_id}: {body.get('msg')}")
    all_rows.extend(body["data"])

    after = all_rows[-1][0]
    while len(all_rows) < bars_needed:
        r = requests.get(
            "https://www.okx.com/api/v5/market/history-candles",
            params={"instId": inst_id, "bar": "15m", "limit": "100", "after": after},
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != "0" or not body.get("data"):
            break
        all_rows.extend(body["data"])
        after = body["data"][-1][0]
        time.sleep(0.05)

    df = pd.DataFrame(all_rows, columns=[
        "timestamp", "open", "high", "low", "close",
        "volume", "volCcy", "volCcyQuote", "confirm",
    ])[["timestamp", "open", "high", "low", "close", "volume"]]
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms", utc=True)
    df = (df.sort_values("timestamp")
            .set_index("timestamp")
            .pipe(lambda d: d[~d.index.duplicated(keep="first")]))
    return df


def resample_to_4h(df_15m: pd.DataFrame) -> pd.DataFrame:
    return df_15m.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


# ─────────────────────────────────────────────────────────────
# Recompute htf for one event (replicates pipeline logic exactly)
# ─────────────────────────────────────────────────────────────

def compute_real_htf(df_4h: pd.DataFrame, df_15m: pd.DataFrame,
                     event_ts_utc: pd.Timestamp) -> dict:
    """Returns {'htf': float, 'note': str, 'cutoff_4h_idx': int|None,
                'closes_-1': float|None}."""
    # The pipeline uses the 4H bar that ENDS at the event timestamp (or
    # the last completed bar before it). event_ts in log is the bar's
    # close stamp like "2026-03-18 12:00:00" (4H bar ending at 12:00).
    bars_le = df_4h.index <= event_ts_utc
    if not bars_le.any():
        return {"htf": None, "note": "no 4H bar before event", "cutoff_4h_idx": None, "close_15m": None}
    cutoff_4h = int(np.where(bars_le)[0][-1])
    # 15m close at the event time = last 15m bar <= event_ts
    mask_15m = df_15m.index <= event_ts_utc
    if not mask_15m.any():
        return {"htf": None, "note": "no 15m bar before event", "cutoff_4h_idx": cutoff_4h, "close_15m": None}
    cutoff_15m = int(np.where(mask_15m)[0][-1])
    close_15m = float(df_15m["close"].iloc[cutoff_15m])
    if cutoff_4h < MA_PERIOD_4H:
        return {"htf": 0.5, "note": "fallback (still too few bars)", "cutoff_4h_idx": cutoff_4h, "close_15m": close_15m}
    lo = float(df_4h["low"].iloc[cutoff_4h - MA_PERIOD_4H + 1: cutoff_4h + 1].min())
    hi = float(df_4h["high"].iloc[cutoff_4h - MA_PERIOD_4H + 1: cutoff_4h + 1].max())
    rng = hi - lo
    htf = (close_15m - lo) / rng if rng > 0 else 0.5
    return {"htf": float(htf), "note": "ok", "cutoff_4h_idx": cutoff_4h, "close_15m": close_15m}


# ─────────────────────────────────────────────────────────────
# Metrics helpers
# ─────────────────────────────────────────────────────────────

def metrics(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0, "win_rate": None, "total_R": 0.0, "avg_R": None, "pf": None}
    arr = np.asarray(rs, dtype=float)
    wins = int((arr > 0).sum())
    gp = float(arr[arr > 0].sum())
    gl = float(-arr[arr < 0].sum())
    pf = (gp / gl) if gl > 0 else float("inf")
    return {
        "n": len(arr),
        "win_rate": float(wins) / len(arr),
        "total_R": float(arr.sum()),
        "avg_R": float(arr.mean()),
        "pf": pf,
    }


def fmt_row(label: str, m: dict) -> str:
    if m["n"] == 0:
        return f"  {label:<26}  n=0"
    pf = m["pf"]
    pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
    return (f"  {label:<26}  n={m['n']:>3}  WR={m['win_rate']*100:5.1f}%  "
            f"totalR={m['total_R']:+7.2f}  avgR={m['avg_R']:+6.3f}  PF={pf_s}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print("Loading model + log...")
    model = joblib.load(MODEL_PATH)
    raw = json.loads(LOG_PATH.read_text())
    results = [r for r in raw if r.get("type") == "result"]
    # Join with event features
    events = {r["event_key"]: r for r in raw if r.get("type") in ("bullish", "bearish")}
    rows = []
    for r in results:
        ev = events.get(r["event_key"])
        if not ev:
            continue
        rows.append({
            "asset": r["asset"],
            "direction": r["direction"],
            "event_ts": pd.to_datetime(ev["timestamp"], utc=True),
            "entry_time": r["entry_time"],
            "actual_r": float(r["actual_r"]),
            "result": r["result"],
            "is_signal_orig": bool(r["is_signal"]),
            "proba_orig": float(r["proba"]),
            "features": dict(ev["features"]),
            "event_key": r["event_key"],
        })
    print(f"  events to rescore: {len(rows)}")
    print(f"  span (event ts):    {min(r['event_ts'] for r in rows)} → {max(r['event_ts'] for r in rows)}")

    # Fetch & resample 15m per asset (one call each)
    print("\nFetching historical 15m bars (one call per asset)...")
    bars_data = {}
    for a in ASSETS:
        df_15m = fetch_15m_history(a, bars_needed=8000)
        df_4h = resample_to_4h(df_15m)
        print(f"  {a}:  15m={len(df_15m)}  4h={len(df_4h)}  "
              f"span 4h: {df_4h.index[0]} → {df_4h.index[-1]}")
        bars_data[a] = (df_15m, df_4h)

    # Recompute htf for each event
    print("\nRecomputing higher_tf_trend per event...")
    n_ok, n_fallback, n_missing = 0, 0, 0
    for r in rows:
        df_15m, df_4h = bars_data[r["asset"]]
        # Convert event timestamp (no tz in log) — pipeline events use UTC
        ts = r["event_ts"]
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        info = compute_real_htf(df_4h, df_15m, ts)
        r["htf_real"] = info["htf"]
        r["htf_note"] = info["note"]
        if info["htf"] is None:
            n_missing += 1
        elif info["note"] == "ok":
            n_ok += 1
        else:
            n_fallback += 1
    print(f"  ok: {n_ok}   fallback: {n_fallback}   missing: {n_missing}")

    # Drop missing events
    rows = [r for r in rows if r["htf_real"] is not None]

    # Rescore with corrected features
    feats_real = []
    for r in rows:
        f = dict(r["features"])
        f["higher_tf_trend"] = r["htf_real"]
        feats_real.append({k: f.get(k, 0) for k in FEATURE_COLS})
    X_real = pd.DataFrame(feats_real)
    proba_real = model.predict_proba(X_real)[:, 1]
    for r, p in zip(rows, proba_real):
        r["proba_aug"] = float(p)
        r["is_signal_aug"] = bool(p >= THRESHOLD_30)

    # Comparison statistics
    print()
    print("=" * 72)
    print(" htf VALUE COMPARISON: live (0.5 frozen) vs simulated real")
    print("=" * 72)
    arr_htf = np.array([r["htf_real"] for r in rows])
    print(f"  Live htf:        all 0.5 (frozen)")
    print(f"  Simulated htf:   mean={arr_htf.mean():.4f}  std={arr_htf.std():.4f}  "
          f"min={arr_htf.min():.4f}  max={arr_htf.max():.4f}")
    print(f"  Distribution:    p25={np.quantile(arr_htf, 0.25):.3f}  "
          f"p50={np.quantile(arr_htf, 0.5):.3f}  p75={np.quantile(arr_htf, 0.75):.3f}")
    for a in ASSETS:
        sub = [r["htf_real"] for r in rows if r["asset"] == a]
        if not sub:
            continue
        sub = np.array(sub)
        print(f"  {a}:  mean={sub.mean():.3f}  std={sub.std():.3f}  "
              f"min={sub.min():.3f}  max={sub.max():.3f}")

    print()
    print("=" * 72)
    print(" PROBA COMPARISON: live (htf=0.5) vs augmented (real htf)")
    print("=" * 72)
    p_orig = np.array([r["proba_orig"] for r in rows])
    p_aug  = np.array([r["proba_aug"]  for r in rows])
    print(f"  Original: mean={p_orig.mean():.4f}  std={p_orig.std():.4f}")
    print(f"  Augmented: mean={p_aug.mean():.4f}  std={p_aug.std():.4f}")
    print(f"  Mean |Δproba|: {np.abs(p_aug - p_orig).mean():.4f}   max: {np.abs(p_aug - p_orig).max():.4f}")
    rs_real = np.array([r["actual_r"] for r in rows])
    rho_orig, _ = spearmanr(p_orig, rs_real)
    rho_aug, _  = spearmanr(p_aug,  rs_real)
    print(f"  Spearman(proba_orig, actual_r):  {rho_orig:+.4f}")
    print(f"  Spearman(proba_aug,  actual_r):  {rho_aug:+.4f}   "
          f"(sign-flip from {'-' if rho_orig<0 else '+'} to {'-' if rho_aug<0 else '+'})")

    print()
    print("=" * 72)
    print(" SIGNAL SELECTION COUNTS: original vs augmented (threshold=0.6454)")
    print("=" * 72)
    print(f"  Original is_signal=True: {sum(r['is_signal_orig'] for r in rows)}")
    print(f"  Augmented is_signal=True: {sum(r['is_signal_aug'] for r in rows)}")
    flips_T = sum(1 for r in rows if not r["is_signal_orig"] and r["is_signal_aug"])
    flips_F = sum(1 for r in rows if r["is_signal_orig"] and not r["is_signal_aug"])
    same = sum(1 for r in rows if r["is_signal_orig"] == r["is_signal_aug"])
    print(f"  Same:           {same}   Flipped → signal: {flips_T}   Flipped → not-signal: {flips_F}")

    print()
    print("=" * 72)
    print(" PERFORMANCE: original signals vs augmented signals (same actual_r)")
    print("=" * 72)
    rows_by_asset = lambda a: [r for r in rows if r["asset"] == a]
    print(fmt_row("ALL (FVG, no filter)", metrics([r["actual_r"] for r in rows])))
    print()
    print(" -- ORIGINAL (htf=0.5 frozen, threshold 0.6454) --")
    print(fmt_row("ALL  signals", metrics([r["actual_r"] for r in rows if r["is_signal_orig"]])))
    for a in ASSETS:
        print(fmt_row(f"{a}  signals", metrics(
            [r["actual_r"] for r in rows_by_asset(a) if r["is_signal_orig"]])))

    print()
    print(" -- AUGMENTED (real htf, threshold 0.6454) --")
    print(fmt_row("ALL  signals", metrics([r["actual_r"] for r in rows if r["is_signal_aug"]])))
    for a in ASSETS:
        print(fmt_row(f"{a}  signals", metrics(
            [r["actual_r"] for r in rows_by_asset(a) if r["is_signal_aug"]])))

    # Calibration: bin by augmented proba
    print()
    print("=" * 72)
    print(" AUGMENTED CALIBRATION: proba quintile vs realized WR / R")
    print("=" * 72)
    for label, sub in [("ALL", rows)] + [(a, rows_by_asset(a)) for a in ASSETS]:
        if len(sub) < 10:
            continue
        ps = np.array([r["proba_aug"] for r in sub])
        edges = np.quantile(ps, np.linspace(0, 1, 6))
        print(f"\n  {label} (n={len(sub)})")
        print(f"    {'bin':>3} {'lo':>6} {'hi':>6} {'mean_p':>7} {'n':>3} {'WR':>6} {'avgR':>7} {'totalR':>8}")
        for i in range(5):
            lo, hi = edges[i], edges[i + 1]
            mask = (ps >= lo) & (ps < hi) if i < 4 else (ps >= lo) & (ps <= hi)
            slc = [r for r, m in zip(sub, mask) if m]
            if not slc:
                continue
            m = metrics([r["actual_r"] for r in slc])
            mp = ps[mask].mean()
            print(f"    {i+1:>3} {lo:>6.3f} {hi:>6.3f} {mp:>7.4f} {m['n']:>3} "
                  f"{m['win_rate']*100:>5.1f}% {m['avg_R']:>+7.3f} {m['total_R']:>+8.2f}")

    # Save JSON
    OUT_PATH.write_text(json.dumps({
        "meta": {
            "n_events_rescored": len(rows),
            "threshold_30": THRESHOLD_30,
            "n_fetched_4h_per_asset": {a: len(bars_data[a][1]) for a in ASSETS},
            "n_ok": n_ok, "n_fallback": n_fallback, "n_missing": n_missing,
        },
        "spearman_orig": float(rho_orig),
        "spearman_aug": float(rho_aug),
        "signals_orig": sum(r["is_signal_orig"] for r in rows),
        "signals_aug":  sum(r["is_signal_aug"]  for r in rows),
        "flips_to_signal":     flips_T,
        "flips_to_not_signal": flips_F,
        "perf": {
            "all_fvg":  metrics([r["actual_r"] for r in rows]),
            "original": {
                "ALL": metrics([r["actual_r"] for r in rows if r["is_signal_orig"]]),
                **{a: metrics([r["actual_r"] for r in rows_by_asset(a) if r["is_signal_orig"]]) for a in ASSETS},
            },
            "augmented": {
                "ALL": metrics([r["actual_r"] for r in rows if r["is_signal_aug"]]),
                **{a: metrics([r["actual_r"] for r in rows_by_asset(a) if r["is_signal_aug"]]) for a in ASSETS},
            },
        },
        "rows": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items() if k != "features"}
            for r in rows
        ],
    }, indent=2, default=str))
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
