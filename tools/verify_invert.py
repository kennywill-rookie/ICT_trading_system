"""
verify_invert.py

Sign-inversion backtest for the ML grading model.

Hypothesis: Spearman(proba, actual_r) is significantly NEGATIVE on the live
closed-trade set (BTC: -0.437, ALL: -0.271). If grading is reversed, then
selecting the BOTTOM 30% of proba should outperform the TOP 30%.

Inputs: logs_kenny/ml_monitor_log.json (records with type=='result')
Outputs:
  - prints ASCII tables
  - tools/results_invert.json (machine-readable summary)

Strategies compared per asset (BTC / ETH / SOL / ALL):
  A. Original          : proba >= 0.6454 (training top-30% threshold)
  B. Inverted          : proba <= P30_live (per-asset bottom 30% of live proba)
  C. Inverted-fixed    : proba <= 0.3546 (mirror of training threshold)

Diagnostics:
  - n / win_rate / total_R / avg_R / profit_factor
  - permutation test (shuffle proba within asset, n=1000, seed=42)
    -> p-value = P(shuffled total_R for inverted strategy >= actual)
  - robustness: top/bottom 20/30/40/50% sweep
  - sub-period split (first half vs second half by entry_time)
  - direction split (Long-only vs Short-only)

Read-only on existing files. Writes only under tools/.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/Users/hyoungwookwon/Documents/09_개발/DEV/TradingSystem_PropCentered")
LOG_PATH = PROJECT_ROOT / "logs_kenny" / "ml_monitor_log.json"
OUT_PATH = PROJECT_ROOT / "tools" / "results_invert.json"

TRAIN_THRESHOLD = 0.6454      # original "high probability" cut (top 30% in training)
INVERTED_FIXED = 1 - TRAIN_THRESHOLD  # 0.3546 mirror

ASSETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
N_PERM = 1000
SEED = 42


# ---------------------------------------------------------------------------
# IO + filtering
# ---------------------------------------------------------------------------
def load_results():
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    results = [r for r in raw if r.get("type") == "result"]
    # keep only records with the fields we need
    cleaned = []
    for r in results:
        if r.get("proba") is None or r.get("actual_r") is None:
            continue
        cleaned.append(r)
    return cleaned


def split_by_asset(records):
    by_asset = defaultdict(list)
    for r in records:
        by_asset[r["asset"]].append(r)
    return by_asset


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def metrics(selected):
    """Return n, win_rate, total_R, avg_R, profit_factor."""
    n = len(selected)
    if n == 0:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "total_R": 0.0,
            "avg_R": float("nan"),
            "profit_factor": float("nan"),
        }
    rs = np.array([r["actual_r"] for r in selected], dtype=float)
    wins = int((rs > 0).sum())
    gross_profit = float(rs[rs > 0].sum())
    gross_loss = float(-rs[rs < 0].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    return {
        "n": n,
        "win_rate": wins / n,
        "total_R": float(rs.sum()),
        "avg_R": float(rs.mean()),
        "profit_factor": pf,
    }


def select(records, mode, p30_value=None):
    if mode == "original":
        return [r for r in records if r["proba"] >= TRAIN_THRESHOLD]
    if mode == "inverted":
        if p30_value is None:
            return []
        return [r for r in records if r["proba"] <= p30_value]
    if mode == "inverted_fixed":
        return [r for r in records if r["proba"] <= INVERTED_FIXED]
    raise ValueError(mode)


def p30(records):
    if not records:
        return None
    return float(np.percentile([r["proba"] for r in records], 30))


# ---------------------------------------------------------------------------
# Permutation test
# ---------------------------------------------------------------------------
def perm_test_inverted(records, rng, n_perm=N_PERM):
    """
    Null: proba carries no information about actual_r.
    Procedure: hold actual_r fixed, shuffle proba, recompute total_R for the
    inverted (bottom-30%) selection. p = fraction with shuffled total_R >=
    actual total_R.
    """
    if len(records) < 5:
        return {
            "actual_total_R": 0.0,
            "p_value_one_sided": float("nan"),
            "shuffle_mean": float("nan"),
            "shuffle_std": float("nan"),
            "percentile": float("nan"),
        }
    probas = np.array([r["proba"] for r in records], dtype=float)
    rs = np.array([r["actual_r"] for r in records], dtype=float)
    cutoff = float(np.percentile(probas, 30))

    actual_mask = probas <= cutoff
    actual_total = float(rs[actual_mask].sum())

    shuffled_totals = np.empty(n_perm, dtype=float)
    for i in range(n_perm):
        perm = rng.permutation(probas)
        cut = float(np.percentile(perm, 30))
        mask = perm <= cut
        shuffled_totals[i] = rs[mask].sum()

    # one-sided p: how often shuffled equals or exceeds actual
    p_val = float((shuffled_totals >= actual_total).sum() + 1) / float(n_perm + 1)
    pct = float((shuffled_totals < actual_total).sum()) / float(n_perm)
    return {
        "actual_total_R": actual_total,
        "p_value_one_sided": p_val,
        "shuffle_mean": float(shuffled_totals.mean()),
        "shuffle_std": float(shuffled_totals.std()),
        "percentile": pct,
    }


# ---------------------------------------------------------------------------
# Robustness sweeps
# ---------------------------------------------------------------------------
def threshold_sweep(records, percentiles=(20, 30, 40, 50)):
    """Compare top vs bottom slice of proba at multiple cutoffs."""
    if not records:
        return {}
    probas = np.array([r["proba"] for r in records], dtype=float)
    out = {}
    for pct in percentiles:
        lo = float(np.percentile(probas, pct))
        hi = float(np.percentile(probas, 100 - pct))
        bot = [r for r in records if r["proba"] <= lo]
        top = [r for r in records if r["proba"] >= hi]
        out[f"{pct}pct"] = {
            "lo_cut": lo,
            "hi_cut": hi,
            "top": metrics(top),
            "bottom": metrics(bot),
            "diff_total_R_bot_minus_top": metrics(bot)["total_R"] - metrics(top)["total_R"],
        }
    return out


def subperiod_split(records):
    """Split by entry_time median into first / second half."""
    if not records:
        return {}
    rs = sorted(records, key=lambda r: r.get("entry_time", ""))
    half = len(rs) // 2
    first, second = rs[:half], rs[half:]
    out = {}
    for label, sub in [("first_half", first), ("second_half", second)]:
        cut = p30(sub)
        out[label] = {
            "n_total": len(sub),
            "p30_cut": cut,
            "inverted": metrics(select(sub, "inverted", cut)),
            "original": metrics(select(sub, "original")),
        }
    return out


def direction_split(records):
    out = {}
    for d in ("Long", "Short"):
        sub = [r for r in records if r.get("direction") == d]
        cut = p30(sub)
        out[d] = {
            "n_total": len(sub),
            "p30_cut": cut,
            "inverted": metrics(select(sub, "inverted", cut)),
            "original": metrics(select(sub, "original")),
        }
    return out


# ---------------------------------------------------------------------------
# Spearman sanity check
# ---------------------------------------------------------------------------
def spearman_check(records):
    if len(records) < 3:
        return {"rho": float("nan"), "p": float("nan"), "n": len(records)}
    probas = [r["proba"] for r in records]
    rs = [r["actual_r"] for r in records]
    rho, p = stats.spearmanr(probas, rs)
    return {"rho": float(rho), "p": float(p), "n": len(records)}


# ---------------------------------------------------------------------------
# Pretty-print helpers (ASCII)
# ---------------------------------------------------------------------------
def fmt_row(cells, widths):
    return "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"


def fmt(v, kind="f"):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if np.isnan(v):
            return "nan"
        if np.isinf(v):
            return "inf"
        if kind == "pct":
            return f"{v*100:.1f}%"
        if kind == "p":
            return f"{v:.4f}"
        return f"{v:+.3f}"
    return str(v)


def print_strategy_table(per_asset_summary):
    print("\n=== Strategy comparison (by asset) ===")
    headers = ["Asset", "Strategy", "n", "Win%", "Total R", "Avg R", "PF"]
    widths = [8, 16, 4, 6, 9, 8, 7]
    print(fmt_row(headers, widths))
    print("|-" + "-|-".join("-" * w for w in widths) + "-|")
    for asset, row in per_asset_summary.items():
        for strat in ("original", "inverted", "inverted_fixed"):
            m = row[strat]
            print(fmt_row([
                asset,
                strat,
                m["n"],
                fmt(m["win_rate"], "pct"),
                fmt(m["total_R"]),
                fmt(m["avg_R"]),
                fmt(m["profit_factor"]),
            ], widths))


def print_perm_table(perm_summary):
    print("\n=== Permutation test (inverted strategy, n_perm=1000, seed=42) ===")
    headers = ["Asset", "Actual R", "Shuf Mean", "Shuf Std", "Pctile", "p (1-sided)"]
    widths = [8, 9, 10, 9, 7, 12]
    print(fmt_row(headers, widths))
    print("|-" + "-|-".join("-" * w for w in widths) + "-|")
    for asset, p in perm_summary.items():
        print(fmt_row([
            asset,
            fmt(p["actual_total_R"]),
            fmt(p["shuffle_mean"]),
            fmt(p["shuffle_std"]),
            f"{p['percentile']*100:.1f}%" if not np.isnan(p["percentile"]) else "nan",
            fmt(p["p_value_one_sided"], "p"),
        ], widths))


def print_threshold_sweep(sweeps):
    print("\n=== Threshold sweep: bottom slice TotalR  -  top slice TotalR ===")
    headers = ["Asset", "Pct", "n_bot", "Bot R", "n_top", "Top R", "Bot-Top"]
    widths = [8, 5, 6, 8, 6, 8, 9]
    print(fmt_row(headers, widths))
    print("|-" + "-|-".join("-" * w for w in widths) + "-|")
    for asset, by_pct in sweeps.items():
        for pct_label, d in by_pct.items():
            print(fmt_row([
                asset,
                pct_label,
                d["bottom"]["n"],
                fmt(d["bottom"]["total_R"]),
                d["top"]["n"],
                fmt(d["top"]["total_R"]),
                fmt(d["diff_total_R_bot_minus_top"]),
            ], widths))


def print_subperiod(subs):
    print("\n=== Sub-period (split by entry_time median) ===")
    headers = ["Asset", "Period", "n_inv", "Inv R", "Inv Win%", "n_orig", "Orig R"]
    widths = [8, 12, 6, 8, 9, 7, 8]
    print(fmt_row(headers, widths))
    print("|-" + "-|-".join("-" * w for w in widths) + "-|")
    for asset, sd in subs.items():
        for period, d in sd.items():
            inv, orig = d["inverted"], d["original"]
            print(fmt_row([
                asset,
                period,
                inv["n"],
                fmt(inv["total_R"]),
                fmt(inv["win_rate"], "pct"),
                orig["n"],
                fmt(orig["total_R"]),
            ], widths))


def print_direction(dsplit):
    print("\n=== Direction split (Long vs Short) ===")
    headers = ["Asset", "Dir", "n_inv", "Inv R", "Inv Win%", "n_orig", "Orig R"]
    widths = [8, 6, 6, 8, 9, 7, 8]
    print(fmt_row(headers, widths))
    print("|-" + "-|-".join("-" * w for w in widths) + "-|")
    for asset, dd in dsplit.items():
        for d, m in dd.items():
            inv, orig = m["inverted"], m["original"]
            print(fmt_row([
                asset,
                d,
                inv["n"],
                fmt(inv["total_R"]),
                fmt(inv["win_rate"], "pct"),
                orig["n"],
                fmt(orig["total_R"]),
            ], widths))


def print_spearman(sp):
    print("\n=== Spearman(proba, actual_r) sanity check ===")
    headers = ["Asset", "n", "rho", "p"]
    widths = [8, 4, 8, 9]
    print(fmt_row(headers, widths))
    print("|-" + "-|-".join("-" * w for w in widths) + "-|")
    for asset, s in sp.items():
        print(fmt_row([asset, s["n"], fmt(s["rho"]), fmt(s["p"], "p")], widths))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    rng = np.random.default_rng(SEED)
    records = load_results()
    print(f"Loaded {len(records)} closed result records from {LOG_PATH}")

    by_asset = split_by_asset(records)
    groups = {a: by_asset.get(a, []) for a in ASSETS}
    groups["ALL"] = records

    # 1. Spearman sanity check
    spearman = {a: spearman_check(g) for a, g in groups.items()}

    # 2. Strategy comparison
    strategy_summary = {}
    for a, g in groups.items():
        cut = p30(g)
        strategy_summary[a] = {
            "p30_cut": cut,
            "train_threshold": TRAIN_THRESHOLD,
            "inverted_fixed_threshold": INVERTED_FIXED,
            "original": metrics(select(g, "original")),
            "inverted": metrics(select(g, "inverted", cut)),
            "inverted_fixed": metrics(select(g, "inverted_fixed")),
        }

    # 3. Permutation test
    perm_summary = {a: perm_test_inverted(g, rng) for a, g in groups.items()}

    # 4. Robustness — threshold sweep
    sweep_summary = {a: threshold_sweep(g) for a, g in groups.items()}

    # 5. Robustness — sub-period
    subperiod_summary = {a: subperiod_split(g) for a, g in groups.items()}

    # 6. Robustness — direction split
    direction_summary = {a: direction_split(g) for a, g in groups.items()}

    # ---------- print ----------
    print_spearman(spearman)
    print_strategy_table(strategy_summary)
    print_perm_table(perm_summary)
    print_threshold_sweep(sweep_summary)
    print_subperiod(subperiod_summary)
    print_direction(direction_summary)

    # ---------- persist ----------
    out = {
        "n_records_total": len(records),
        "train_threshold": TRAIN_THRESHOLD,
        "inverted_fixed_threshold": INVERTED_FIXED,
        "n_perm": N_PERM,
        "seed": SEED,
        "spearman": spearman,
        "strategy_summary": strategy_summary,
        "permutation_test": perm_summary,
        "threshold_sweep": sweep_summary,
        "subperiod": subperiod_summary,
        "direction_split": direction_summary,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=lambda o: None if isinstance(o, float) and np.isnan(o) else o)
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
