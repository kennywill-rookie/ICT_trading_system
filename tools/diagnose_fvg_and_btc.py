"""
Comprehensive diagnostic for three questions:
  1. Is "FVG is the alpha" still right (in live data, irrespective of model)?
  2. Why does BTC show negative edge (feature-level)?
  3. Is the proba threshold narrow / meaningless / inverted?

Inputs:  logs_kenny/ml_monitor_log.json
Outputs: tools/results_diagnostic.json + ASCII tables to stdout

This is read-only on logs. Joins type='result' with type='bullish'/'bearish'
on event_key to recover features per closed trade.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr, mannwhitneyu, ks_2samp

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs_kenny" / "ml_monitor_log.json"
OUT_PATH = ROOT / "tools" / "results_diagnostic.json"

FEATURE_COLS = [
    "gap_pct", "gap_atr_ratio", "trend_48bars", "swing_count",
    "dist_to_swing_high_pct", "dist_to_swing_low_pct", "higher_tf_trend",
    "rsi_14", "rsi_delta_16bars", "bb_position", "vol_ratio", "vol_surge_15m",
    "prev_fvg_same_dir_dist", "prev_fvg_filled", "impulse_purity",
    "consecutive_dir_bars", "hour_of_day", "day_of_week", "atr_percentile",
    "is_trending",
]
ASSETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]


# ---------- I/O ----------

def load_joined() -> list[dict]:
    """Join result records with their originating bullish/bearish event."""
    raw = json.loads(LOG_PATH.read_text())
    events = {r["event_key"]: r for r in raw if r.get("type") in ("bullish", "bearish")}
    out = []
    for r in raw:
        if r.get("type") != "result":
            continue
        ev = events.get(r["event_key"])
        if not ev:
            continue
        merged = dict(r)
        merged["features"] = ev.get("features", {})
        merged["event_type"] = ev.get("type")  # bullish/bearish
        out.append(merged)
    out.sort(key=lambda r: r["entry_time"])
    return out


# ---------- helpers ----------

def htf_bias_label(htf_trend: float) -> str:
    """Map the higher_tf_trend feature value to a bucket label.

    Training pipeline encodes higher_tf_trend as a categorical proxy with
    values like {-1.0, -0.5, 0.0, 0.5, 1.0} for strong-bear..strong-bull.
    """
    if htf_trend is None:
        return "unknown"
    if htf_trend >= 0.75:
        return "strong_bull"
    if htf_trend >= 0.25:
        return "bull"
    if htf_trend > -0.25:
        return "neutral"
    if htf_trend > -0.75:
        return "bear"
    return "strong_bear"


def metrics(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0, "win_rate": None, "total_R": 0.0, "avg_R": None, "pf": None}
    rs = np.asarray(rs, dtype=float)
    wins = int((rs > 0).sum())
    gp = float(rs[rs > 0].sum())
    gl = float(-rs[rs < 0].sum())
    pf = (gp / gl) if gl > 0 else float("inf")
    return {
        "n": int(len(rs)),
        "win_rate": float(wins) / len(rs),
        "total_R": float(rs.sum()),
        "avg_R": float(rs.mean()),
        "pf": pf,
    }


def fmt_m(m: dict) -> str:
    wr = m["win_rate"]
    return (f"n={m['n']:>3}  WR={wr*100:5.1f}%  totalR={m['total_R']:+7.2f}  "
            f"avgR={m['avg_R']:+6.3f}  PF={m['pf']:.2f}" if wr is not None else f"n=0")


def describe(vals: list[float]) -> dict:
    arr = np.asarray(vals, dtype=float)
    if len(arr) == 0:
        return {"n": 0}
    return {
        "n": int(len(arr)),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "p25": float(np.quantile(arr, 0.25)),
        "p50": float(np.quantile(arr, 0.50)),
        "p75": float(np.quantile(arr, 0.75)),
    }


# ---------- 1. FVG alpha (base rate, regardless of model) ----------

def fvg_alpha(trades: list[dict]) -> dict:
    """All closed FVG events, no model filter — what's the base rate?

    Stratifies by asset, direction, HTF bias bucket, FVG type (bull/bear)
    to test if the backtest claim ('FVG is alpha, HTF-aligned, neutral
    avoid, reverse forbidden') still holds.
    """
    rs = [t["actual_r"] for t in trades]
    out: dict = {"overall": metrics(rs)}

    by_asset: dict = {}
    for a in ASSETS:
        sub = [t for t in trades if t["asset"] == a]
        by_asset[a] = {
            "all": metrics([t["actual_r"] for t in sub]),
            "Long": metrics([t["actual_r"] for t in sub if t["direction"] == "Long"]),
            "Short": metrics([t["actual_r"] for t in sub if t["direction"] == "Short"]),
        }
    out["by_asset_direction"] = by_asset

    # HTF bias × direction
    bias_dir: dict = defaultdict(lambda: defaultdict(list))
    for t in trades:
        bias = htf_bias_label(t["features"].get("higher_tf_trend"))
        bias_dir[bias][t["direction"]].append(t["actual_r"])
    out["htf_bias_x_direction"] = {
        bias: {d: metrics(rs) for d, rs in dirs.items()}
        for bias, dirs in bias_dir.items()
    }

    # HTF bias × FVG type
    bias_type: dict = defaultdict(lambda: defaultdict(list))
    for t in trades:
        bias = htf_bias_label(t["features"].get("higher_tf_trend"))
        bias_type[bias][t["event_type"]].append(t["actual_r"])
    out["htf_bias_x_fvg_type"] = {
        bias: {ev: metrics(rs) for ev, rs in evs.items()}
        for bias, evs in bias_type.items()
    }

    # Reverse trades (direction opposes HTF bias)
    reverse_rs, aligned_rs, neutral_rs = [], [], []
    for t in trades:
        bias = htf_bias_label(t["features"].get("higher_tf_trend"))
        d = t["direction"]
        if bias in ("strong_bull", "bull"):
            (aligned_rs if d == "Long" else reverse_rs).append(t["actual_r"])
        elif bias in ("strong_bear", "bear"):
            (aligned_rs if d == "Short" else reverse_rs).append(t["actual_r"])
        else:
            neutral_rs.append(t["actual_r"])
    out["alignment"] = {
        "aligned":  metrics(aligned_rs),
        "reverse":  metrics(reverse_rs),
        "neutral":  metrics(neutral_rs),
    }
    return out


# ---------- 2. BTC negative edge — feature-level ----------

def btc_diagnostic(trades: list[dict]) -> dict:
    """Why is BTC inverted? Compare BTC feature distributions in
    proba>=median vs proba<median bins, and check feature-vs-R rank
    correlations PER ASSET to localize what's flipped for BTC.
    """
    out: dict = {}
    for a in ASSETS:
        sub = [t for t in trades if t["asset"] == a]
        if len(sub) < 8:
            out[a] = {"n": len(sub), "note": "insufficient"}
            continue
        probas = np.array([t["proba"] for t in sub])
        med = float(np.median(probas))
        hi = [t for t in sub if t["proba"] >= med]
        lo = [t for t in sub if t["proba"] < med]

        feat_stats: dict = {}
        for f in FEATURE_COLS:
            hi_vals = [t["features"].get(f) for t in hi if t["features"].get(f) is not None]
            lo_vals = [t["features"].get(f) for t in lo if t["features"].get(f) is not None]
            # rank corr feature vs actual_r
            xs, ys = [], []
            for t in sub:
                v = t["features"].get(f)
                if v is None:
                    continue
                xs.append(v)
                ys.append(t["actual_r"])
            if len(xs) < 5:
                continue
            rho, p = spearmanr(xs, ys)
            try:
                u_stat, u_p = mannwhitneyu(hi_vals, lo_vals, alternative="two-sided")
            except ValueError:
                u_stat, u_p = float("nan"), float("nan")
            feat_stats[f] = {
                "rho_feature_vs_r": float(rho) if rho == rho else None,
                "p_rho": float(p) if p == p else None,
                "hi_mean": float(np.mean(hi_vals)) if hi_vals else None,
                "lo_mean": float(np.mean(lo_vals)) if lo_vals else None,
                "diff": (float(np.mean(hi_vals)) - float(np.mean(lo_vals)))
                        if hi_vals and lo_vals else None,
                "mwu_p": float(u_p) if u_p == u_p else None,
            }
        out[a] = {
            "n": len(sub),
            "median_proba": med,
            "hi_mean_R": float(np.mean([t["actual_r"] for t in hi])),
            "lo_mean_R": float(np.mean([t["actual_r"] for t in lo])),
            "features": feat_stats,
        }
    return out


# ---------- 3. Threshold validity (calibration) ----------

def calibration(trades: list[dict]) -> dict:
    """Bucket trades by proba decile, compute realized WR and avg-R.

    A well-calibrated model: higher proba bucket -> higher realized WR.
    An inverted model: monotonically decreasing WR with proba.
    A meaningless model: flat (no relationship).
    """
    out: dict = {}
    for label, sub in [
        ("ALL", trades),
        ("BTC-USDT", [t for t in trades if t["asset"] == "BTC-USDT"]),
        ("ETH-USDT", [t for t in trades if t["asset"] == "ETH-USDT"]),
        ("SOL-USDT", [t for t in trades if t["asset"] == "SOL-USDT"]),
    ]:
        if len(sub) < 10:
            out[label] = {"n": len(sub), "note": "insufficient"}
            continue
        probas = np.array([t["proba"] for t in sub])
        edges = np.quantile(probas, np.linspace(0, 1, 6))  # quintiles
        bins = []
        for i in range(5):
            lo, hi = edges[i], edges[i + 1]
            if i == 4:
                mask = (probas >= lo) & (probas <= hi)
            else:
                mask = (probas >= lo) & (probas < hi)
            slice_t = [t for t, m in zip(sub, mask) if m]
            rs = [t["actual_r"] for t in slice_t]
            m = metrics(rs)
            m.update({
                "bin": i + 1,
                "lo": float(lo),
                "hi": float(hi),
                "mean_proba": float(probas[mask].mean()) if mask.any() else None,
            })
            bins.append(m)
        # Brier score: requires actual class label (WIN=1, LOSS=0). TIMEOUT
        # is ambiguous; drop those for Brier.
        binary = [(t["proba"], 1 if t["result"] == "WIN" else 0)
                  for t in sub if t["result"] in ("WIN", "LOSS")]
        if binary:
            ps = np.array([b[0] for b in binary])
            ys = np.array([b[1] for b in binary])
            brier = float(np.mean((ps - ys) ** 2))
            # Naive baseline: predict the base rate for all
            baseline = float(ys.mean())
            brier_base = float(np.mean((baseline - ys) ** 2))
        else:
            brier = brier_base = None
        out[label] = {
            "n": len(sub),
            "bins": bins,
            "brier": brier,
            "brier_baseline": brier_base,
            "brier_skill": (1 - brier / brier_base) if (brier and brier_base) else None,
        }
    return out


# ---------- 4. Proba distribution narrowness ----------

def proba_distribution(trades: list[dict], all_events: list[dict]) -> dict:
    """Test whether live proba is too narrow (low variance -> threshold
    falls in the fat middle, becoming meaningless)."""
    out: dict = {}
    for label, sub in [
        ("ALL", all_events),
        ("BTC-USDT", [e for e in all_events if e["asset"] == "BTC-USDT"]),
        ("ETH-USDT", [e for e in all_events if e["asset"] == "ETH-USDT"]),
        ("SOL-USDT", [e for e in all_events if e["asset"] == "SOL-USDT"]),
    ]:
        if not sub:
            continue
        ps = np.array([e["proba"] for e in sub])
        out[label] = {
            **describe(ps),
            "pct_above_0.6454": float((ps >= 0.6454).mean() * 100),
            "pct_above_0.6771": float((ps >= 0.6771).mean() * 100),
            "pct_in_band_0.5_0.65": float(((ps >= 0.5) & (ps <= 0.65)).mean() * 100),
            # range from 5th to 95th percentile = effective dynamic range
            "p05_p95_range": float(np.quantile(ps, 0.95) - np.quantile(ps, 0.05)),
        }
    return out


# ---------- Print helpers ----------

def print_metrics_table(title: str, rows: list[tuple[str, dict]]) -> None:
    print()
    print(title)
    print("-" * len(title))
    for label, m in rows:
        if m.get("n", 0) == 0:
            print(f"  {label:<22}  n=0")
            continue
        wr = m.get("win_rate")
        wr_s = f"{wr*100:5.1f}%" if wr is not None else "   nan"
        pf = m.get("pf", float("nan"))
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        print(f"  {label:<22}  n={m['n']:>3}  WR={wr_s}  totalR={m['total_R']:+7.2f}  "
              f"avgR={m['avg_R']:+6.3f}  PF={pf_s}")


def main():
    trades = load_joined()
    raw = json.loads(LOG_PATH.read_text())
    fvg_events = [r for r in raw if r.get("type") in ("bullish", "bearish") and r.get("proba") is not None]

    print(f"=== Loaded ===")
    print(f"  closed trades (joined w/ features): {len(trades)}")
    print(f"  all FVG events (open):              {len(fvg_events)}")
    print(f"  span: {trades[0]['entry_time'][:10]} -> {trades[-1]['entry_time'][:10]}")

    # ---- 1. FVG ALPHA ----
    print("\n" + "=" * 70)
    print(" 1. FVG ALPHA — base rate of all 137 FVG events (no model filter)")
    print("=" * 70)
    fvg = fvg_alpha(trades)
    print_metrics_table("Overall (FVG only, all closed trades)", [("ALL", fvg["overall"])])

    rows = []
    for a, blk in fvg["by_asset_direction"].items():
        for d in ("all", "Long", "Short"):
            rows.append((f"{a:<10} {d}", blk[d]))
    print_metrics_table("By asset × direction", rows)

    rows = []
    for bias, dirs in fvg["htf_bias_x_direction"].items():
        for d, m in dirs.items():
            rows.append((f"{bias:<12} {d}", m))
    print_metrics_table("HTF bias × direction (validates backtest rules)", rows)

    rows = [(k, v) for k, v in fvg["alignment"].items()]
    print_metrics_table("HTF alignment: aligned / reverse / neutral", rows)

    # ---- 4. Proba distribution narrowness ----
    print("\n" + "=" * 70)
    print(" 4. PROBA DISTRIBUTION — is the live proba too narrow to be useful?")
    print("=" * 70)
    pd_ = proba_distribution(trades, fvg_events)
    print(f"{'label':<10} {'n':>4} {'mean':>7} {'std':>7} {'p25':>7} {'p50':>7} {'p75':>7} "
          f"{'p5_p95':>7} {'%>=0.6454':>10}  {'%mid(0.5-0.65)':>15}")
    for k, v in pd_.items():
        print(f"{k:<10} {v['n']:>4} {v['mean']:>7.4f} {v['std']:>7.4f} "
              f"{v['p25']:>7.4f} {v['p50']:>7.4f} {v['p75']:>7.4f} "
              f"{v['p05_p95_range']:>7.4f} {v['pct_above_0.6454']:>9.1f}%  "
              f"{v['pct_in_band_0.5_0.65']:>14.1f}%")

    # ---- 3. CALIBRATION ----
    print("\n" + "=" * 70)
    print(" 3. CALIBRATION — proba quintile vs realized WR / R")
    print("=" * 70)
    cal = calibration(trades)
    for label, blk in cal.items():
        if "bins" not in blk:
            continue
        print(f"\n  {label} (n={blk['n']}, brier={blk['brier']:.4f}, "
              f"baseline={blk['brier_baseline']:.4f}, skill={blk['brier_skill']:+.4f})")
        print(f"    {'bin':>3} {'lo':>6} {'hi':>6} {'mean_p':>7} {'n':>3} "
              f"{'WR':>6} {'avgR':>7} {'totalR':>8}")
        for b in blk["bins"]:
            if b["n"] == 0:
                print(f"    {b['bin']:>3} {b['lo']:>6.3f} {b['hi']:>6.3f}  n=0")
                continue
            print(f"    {b['bin']:>3} {b['lo']:>6.3f} {b['hi']:>6.3f} {b['mean_proba']:>7.4f} "
                  f"{b['n']:>3} {b['win_rate']*100:>5.1f}% {b['avg_R']:>+7.3f} "
                  f"{b['total_R']:>+8.2f}")

    # ---- 2. BTC FEATURE DIAGNOSTIC ----
    print("\n" + "=" * 70)
    print(" 2. BTC DIAGNOSTIC — feature-vs-R rank correlations per asset")
    print("=" * 70)
    btc = btc_diagnostic(trades)
    # show top discriminators per asset: features with |rho| largest
    for a in ASSETS:
        blk = btc[a]
        if "features" not in blk:
            print(f"\n  {a}: {blk.get('note')}")
            continue
        print(f"\n  {a}  (n={blk['n']}, hi-half mean_R={blk['hi_mean_R']:+.3f}, "
              f"lo-half mean_R={blk['lo_mean_R']:+.3f})")
        feats = blk["features"]
        top = sorted(feats.items(),
                     key=lambda kv: abs(kv[1].get("rho_feature_vs_r") or 0),
                     reverse=True)[:8]
        print(f"    {'feature':<28} {'rho(feat,r)':>11} {'p':>7} {'hi-mean':>9} {'lo-mean':>9} {'diff':>9} {'mwu_p':>7}")
        for f, s in top:
            rho = s["rho_feature_vs_r"]
            p = s["p_rho"]
            hi_m = s["hi_mean"]; lo_m = s["lo_mean"]; diff = s["diff"]
            mp = s["mwu_p"]
            print(f"    {f:<28} {rho:>+11.3f} {p:>7.3f} "
                  f"{hi_m:>+9.3f} {lo_m:>+9.3f} {diff:>+9.3f} {mp:>7.3f}")

    # ---- Save JSON ----
    OUT_PATH.write_text(json.dumps({
        "meta": {
            "n_trades": len(trades),
            "n_fvg_events": len(fvg_events),
            "span_start": trades[0]["entry_time"],
            "span_end":   trades[-1]["entry_time"],
        },
        "fvg_alpha": fvg,
        "btc_diagnostic": btc,
        "calibration": cal,
        "proba_distribution": pd_,
    }, indent=2, default=str))
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
