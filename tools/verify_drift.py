"""
Distribution drift verification: training-time proba vs live proba.

Usage:
  python tools/verify_drift.py

Outputs:
  - ASCII summary table to stdout
  - tools/results_drift.json
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT / "ml_fvg_dataset.csv"
MODEL_PATH = ROOT / "ml_fvg_model.pkl"
LIVE_LOG_PATH = ROOT / "logs_kenny" / "ml_monitor_log.json"
RESULTS_PATH = ROOT / "tools" / "results_drift.json"

FEATURE_COLS = [
    "gap_pct", "swing_count",
    "dist_to_swing_high_pct", "dist_to_swing_low_pct", "higher_tf_trend",
    "rsi_14", "rsi_delta_16bars", "bb_position", "vol_ratio", "vol_surge_15m",
    "prev_fvg_same_dir_dist", "prev_fvg_filled",
    "consecutive_dir_bars", "day_of_week",
    "atr_percentile",
]

ASSETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
THRESHOLD_TOP30 = 0.6454
THRESHOLD_TOP20 = 0.6771
HIST_BINS = np.arange(0.0, 1.0001, 0.05)


# ──────────────────────────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────────────────────────

def load_training_probas(model, dataset_path: Path) -> pd.DataFrame:
    """Reconstruct training-time proba distribution from cached CSV.

    The pipeline output is cached as ml_fvg_dataset.csv with a `split` column
    (train/val/test). We score the model on the FULL training population
    (train + val + test) — these are the events the model was trained on.
    """
    df = pd.read_csv(dataset_path)
    # Filter to populations used in training (drop timeout label=-1 to match training)
    df = df[df["label_rr15"] != -1].copy()
    X = df[FEATURE_COLS]
    proba = model.predict_proba(X)[:, 1]
    df["proba"] = proba
    return df[["timestamp", "asset", "split", "proba"]].copy()


def load_live_probas(log_path: Path) -> pd.DataFrame:
    with open(log_path) as f:
        records = json.load(f)
    rows = []
    for r in records:
        if r.get("type") not in ("bullish", "bearish"):
            continue
        if r.get("proba") is None:
            continue
        rows.append({
            "timestamp": r["timestamp"],
            "asset": r["asset"],
            "type": r["type"],
            "proba": float(r["proba"]),
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────

def psi(expected: np.ndarray, actual: np.ndarray, bins: np.ndarray) -> float:
    """Population Stability Index using the standard 0.0001 floor convention.

    PSI = sum (actual_pct - expected_pct) * ln(actual_pct / expected_pct)
    """
    eps = 1e-4
    e_counts, _ = np.histogram(expected, bins=bins)
    a_counts, _ = np.histogram(actual, bins=bins)
    e_pct = e_counts / max(e_counts.sum(), 1)
    a_pct = a_counts / max(a_counts.sum(), 1)
    e_pct = np.where(e_pct < eps, eps, e_pct)
    a_pct = np.where(a_pct < eps, eps, a_pct)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def describe(values: np.ndarray) -> dict:
    if len(values) == 0:
        return {"n": 0, "mean": None, "std": None, "q1": None, "q2": None, "q3": None}
    return {
        "n": int(len(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "q1": float(np.quantile(values, 0.25)),
        "q2": float(np.quantile(values, 0.50)),
        "q3": float(np.quantile(values, 0.75)),
    }


def histogram(values: np.ndarray, bins: np.ndarray) -> list:
    counts, _ = np.histogram(values, bins=bins)
    return counts.tolist()


def compare(train_p: np.ndarray, live_p: np.ndarray) -> dict:
    out = {
        "train": describe(train_p),
        "live": describe(live_p),
        "train_hist": histogram(train_p, HIST_BINS),
        "live_hist": histogram(live_p, HIST_BINS),
    }
    if len(train_p) >= 2 and len(live_p) >= 2:
        ks = ks_2samp(train_p, live_p)
        out["ks_stat"] = float(ks.statistic)
        out["ks_pvalue"] = float(ks.pvalue)
    else:
        out["ks_stat"] = None
        out["ks_pvalue"] = None
    if len(train_p) > 0 and len(live_p) > 0:
        out["psi"] = psi(train_p, live_p, HIST_BINS)
        out["mean_shift"] = float(np.mean(live_p) - np.mean(train_p))
    else:
        out["psi"] = None
        out["mean_shift"] = None
    if len(live_p) > 0:
        out["pct_above_top30_thresh"] = float((live_p >= THRESHOLD_TOP30).mean() * 100)
        out["pct_above_top20_thresh"] = float((live_p >= THRESHOLD_TOP20).mean() * 100)
    else:
        out["pct_above_top30_thresh"] = None
        out["pct_above_top20_thresh"] = None
    if len(train_p) > 0:
        out["train_pct_above_top30_thresh"] = float((train_p >= THRESHOLD_TOP30).mean() * 100)
    else:
        out["train_pct_above_top30_thresh"] = None
    return out


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main():
    print(f"[drift] Loading model: {MODEL_PATH.name}")
    model = joblib.load(MODEL_PATH)

    print(f"[drift] Reconstructing training proba from {DATASET_PATH.name}")
    train_df = load_training_probas(model, DATASET_PATH)
    print(f"        rows={len(train_df)}  splits={train_df['split'].value_counts().to_dict()}")

    print(f"[drift] Loading live proba from {LIVE_LOG_PATH.name}")
    live_df = load_live_probas(LIVE_LOG_PATH)
    print(f"        live events (bullish/bearish only): {len(live_df)}")

    results = OrderedDict()
    results["meta"] = {
        "model_path": str(MODEL_PATH.relative_to(ROOT)),
        "dataset_path": str(DATASET_PATH.relative_to(ROOT)),
        "live_log_path": str(LIVE_LOG_PATH.relative_to(ROOT)),
        "features": FEATURE_COLS,
        "train_threshold_top30": THRESHOLD_TOP30,
        "train_threshold_top20": THRESHOLD_TOP20,
        "psi_drift_threshold": 0.2,
        "train_population_n": int(len(train_df)),
        "live_population_n": int(len(live_df)),
        "train_date_range": [str(train_df["timestamp"].min()), str(train_df["timestamp"].max())],
        "live_date_range": [str(live_df["timestamp"].min()), str(live_df["timestamp"].max())] if len(live_df) else [None, None],
    }

    # Overall
    results["overall"] = compare(train_df["proba"].values, live_df["proba"].values)

    # Per asset
    per_asset = {}
    for asset in ASSETS:
        t = train_df[train_df["asset"] == asset]["proba"].values
        l = live_df[live_df["asset"] == asset]["proba"].values
        per_asset[asset] = compare(t, l)
    results["per_asset"] = per_asset

    # ──────────────────────────────────────────────────────────────
    # Print summary
    # ──────────────────────────────────────────────────────────────
    print()
    print("=" * 96)
    print(" Distribution Drift Summary: Training proba vs Live proba")
    print("=" * 96)

    header = f"{'asset':<10} {'n_train':>7} {'n_live':>6} {'mean_tr':>8} {'mean_lv':>8} {'shift':>7} {'KS':>6} {'p':>8} {'PSI':>6} {'flag':>6} {'%>=0.6454(lv)':>13}"
    print(header)
    print("-" * 96)

    def fmt_row(name, blk):
        n_tr = blk["train"]["n"]
        n_lv = blk["live"]["n"]
        m_tr = blk["train"]["mean"]
        m_lv = blk["live"]["mean"]
        shift = blk["mean_shift"]
        ks = blk["ks_stat"]
        p = blk["ks_pvalue"]
        psi_v = blk["psi"]
        pct = blk["pct_above_top30_thresh"]
        flag = ""
        if psi_v is not None:
            if psi_v > 0.2:
                flag = "DRIFT"
            elif psi_v > 0.1:
                flag = "watch"
            else:
                flag = "ok"
        return (
            f"{name:<10} {n_tr:>7d} {n_lv:>6d} "
            f"{m_tr:>8.4f} {m_lv:>8.4f} {shift:>+7.4f} "
            f"{ks:>6.3f} {p:>8.4f} {psi_v:>6.3f} {flag:>6} {pct:>12.1f}%"
        )

    print(fmt_row("OVERALL", results["overall"]))
    for asset in ASSETS:
        print(fmt_row(asset, per_asset[asset]))

    print("-" * 96)
    print(f" Training top-30% threshold = {THRESHOLD_TOP30:.4f} "
          f"(train should have ~30% above; live % is observed live signal rate)")
    print(f" PSI flag rule:  PSI <= 0.10 ok  |  0.10 < PSI <= 0.20 watch  |  PSI > 0.20 DRIFT")
    print("=" * 96)

    # Save JSON
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[drift] Wrote results: {RESULTS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
