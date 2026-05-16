"""Temporal proba->R correlation analysis.

Determines whether the ML model was broken from day 1 or whether the
proba->actual_r relationship degraded over the 52-day live span.

Inputs:
    logs_kenny/ml_monitor_log.json  (records with type=='result')

Outputs:
    stdout: ASCII tables for the 4 analyses
    tools/results_temporal.json: rolling series, bucket stats, cum trajectory
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs_kenny" / "ml_monitor_log.json"
OUT_PATH = ROOT / "tools" / "results_temporal.json"

ASSETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
ASSET_SHORT = {"BTC-USDT": "BTC", "ETH-USDT": "ETH", "SOL-USDT": "SOL"}
SPLIT_DATE = datetime(2026, 4, 1, tzinfo=timezone.utc)


def load_results(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    rs = [r for r in raw if r.get("type") == "result"]
    for r in rs:
        r["_t"] = datetime.fromisoformat(r["entry_time"])
    rs.sort(key=lambda r: r["_t"])
    return rs


def safe_spearman(probas: list[float], rs: list[float]):
    if len(probas) < 3:
        return float("nan"), float("nan")
    rho, p = spearmanr(probas, rs)
    return float(rho), float(p)


def by_asset(trades: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {a: [] for a in ASSETS}
    for t in trades:
        if t["asset"] in out:
            out[t["asset"]].append(t)
    return out


# ---------- 1. Rolling correlation ----------

def rolling_spearman(trades: list[dict], window: int) -> list[dict]:
    series = []
    for i in range(window - 1, len(trades)):
        win = trades[i - window + 1 : i + 1]
        rho, p = safe_spearman([t["proba"] for t in win], [t["actual_r"] for t in win])
        series.append(
            {
                "i": i + 1,
                "entry_time": trades[i]["entry_time"],
                "rho": rho,
                "p": p,
                "n": len(win),
            }
        )
    return series


def rolling_all(trades: list[dict], window: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"ALL": rolling_spearman(trades, window)}
    for a, ts in by_asset(trades).items():
        out[ASSET_SHORT[a]] = rolling_spearman(ts, window)
    return out


# ---------- 2. Time buckets ----------

def time_buckets(trades: list[dict], n_buckets: int = 4) -> list[list[dict]]:
    n = len(trades)
    buckets: list[list[dict]] = []
    for b in range(n_buckets):
        lo = (n * b) // n_buckets
        hi = (n * (b + 1)) // n_buckets
        buckets.append(trades[lo:hi])
    return buckets


def bucket_stats(bucket: list[dict]) -> dict:
    if not bucket:
        return {"n": 0}
    rho, p = safe_spearman([t["proba"] for t in bucket], [t["actual_r"] for t in bucket])
    rs = [t["actual_r"] for t in bucket]
    wins = sum(1 for t in bucket if t["result"] == "WIN")
    return {
        "n": len(bucket),
        "rho": rho,
        "p": p,
        "mean_r": sum(rs) / len(rs),
        "win_rate": wins / len(bucket),
        "start": bucket[0]["entry_time"][:10],
        "end": bucket[-1]["entry_time"][:10],
    }


# ---------- 3. Cumulative correlation ----------

def cumulative_spearman(trades: list[dict]) -> list[dict]:
    series = []
    for i in range(2, len(trades)):
        sub = trades[: i + 1]
        rho, p = safe_spearman([t["proba"] for t in sub], [t["actual_r"] for t in sub])
        series.append(
            {
                "i": i + 1,
                "entry_time": trades[i]["entry_time"],
                "rho": rho,
                "p": p,
            }
        )
    return series


# ---------- 4. First-month vs Later ----------

def split_by_date(trades: list[dict], cutoff: datetime) -> tuple[list[dict], list[dict]]:
    early = [t for t in trades if t["_t"] < cutoff]
    later = [t for t in trades if t["_t"] >= cutoff]
    return early, later


# ---------- ASCII formatting ----------

def fmt_rho(rho: float) -> str:
    if rho != rho:  # NaN
        return "  nan "
    return f"{rho:+.3f}"


def fmt_p(p: float) -> str:
    if p != p:
        return "  nan "
    return f"{p:.3f}"


def print_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print()
    print(title)
    print(sep)
    print("|" + "|".join(f" {h:<{widths[i]}} " for i, h in enumerate(headers)) + "|")
    print(sep)
    for r in rows:
        print("|" + "|".join(f" {str(c):<{widths[i]}} " for i, c in enumerate(r)) + "|")
    print(sep)


# ---------- Main ----------

def main() -> None:
    trades = load_results(LOG_PATH)
    print(f"Loaded {len(trades)} closed trades.")
    print(f"Span: {trades[0]['entry_time'][:19]}  ->  {trades[-1]['entry_time'][:19]}")

    asset_trades = by_asset(trades)
    for a in ASSETS:
        print(f"  {ASSET_SHORT[a]}: n={len(asset_trades[a])}")

    # ---- 1. Rolling Spearman ----
    rolling_15 = rolling_all(trades, 15)
    rolling_30 = rolling_all(trades, 30)

    print("\n" + "=" * 72)
    print("1. ROLLING SPEARMAN  (samples: first / mid / last)")
    print("=" * 72)
    for label, rs in [("window=15", rolling_15), ("window=30", rolling_30)]:
        rows = []
        for k in ["ALL", "BTC", "ETH", "SOL"]:
            s = rs[k]
            if not s:
                rows.append([k, "0", "-", "-", "-"])
                continue
            mid = s[len(s) // 2]
            rows.append(
                [
                    k,
                    str(len(s)),
                    f"{s[0]['entry_time'][:10]} {fmt_rho(s[0]['rho'])}",
                    f"{mid['entry_time'][:10]} {fmt_rho(mid['rho'])}",
                    f"{s[-1]['entry_time'][:10]} {fmt_rho(s[-1]['rho'])}",
                ]
            )
        print_table(
            f"  {label}",
            ["asset", "pts", "first window", "mid window", "last window"],
            rows,
        )

    # ---- 2. Time-bucket comparison (4 buckets) ----
    print("\n" + "=" * 72)
    print("2. TIME-BUCKET COMPARISON (4 equal buckets by entry_time)")
    print("=" * 72)
    overall_buckets = time_buckets(trades, 4)
    rows = []
    for b_idx, b in enumerate(overall_buckets, 1):
        s = bucket_stats(b)
        rows.append(
            [
                f"B{b_idx}",
                f"{s['start']}..{s['end']}",
                str(s["n"]),
                fmt_rho(s["rho"]),
                fmt_p(s["p"]),
                f"{s['mean_r']:+.3f}",
                f"{s['win_rate']:.1%}",
            ]
        )
    print_table(
        "  ALL assets",
        ["bucket", "date range", "n", "rho", "p", "mean_R", "win%"],
        rows,
    )

    bucket_data: dict[str, list[dict]] = {"ALL": [bucket_stats(b) for b in overall_buckets]}
    for a in ASSETS:
        a_buckets = time_buckets(asset_trades[a], 4)
        rows = []
        stats_list = []
        for b_idx, b in enumerate(a_buckets, 1):
            s = bucket_stats(b)
            stats_list.append(s)
            if not b:
                rows.append([f"B{b_idx}", "-", "0", "-", "-", "-", "-"])
                continue
            rows.append(
                [
                    f"B{b_idx}",
                    f"{s['start']}..{s['end']}",
                    str(s["n"]),
                    fmt_rho(s["rho"]),
                    fmt_p(s["p"]),
                    f"{s['mean_r']:+.3f}",
                    f"{s['win_rate']:.1%}",
                ]
            )
        bucket_data[ASSET_SHORT[a]] = stats_list
        print_table(
            f"  {ASSET_SHORT[a]}",
            ["bucket", "date range", "n", "rho", "p", "mean_R", "win%"],
            rows,
        )

    # B1 vs B4 delta
    print("\n  B1 vs B4 delta in rho (negative delta = correlation got more negative):")
    for k in ["ALL", "BTC", "ETH", "SOL"]:
        b1, b4 = bucket_data[k][0], bucket_data[k][3]
        if b1.get("n", 0) and b4.get("n", 0):
            d = b4["rho"] - b1["rho"]
            print(f"    {k}: B1 rho={fmt_rho(b1['rho'])}  B4 rho={fmt_rho(b4['rho'])}  delta={d:+.3f}")

    # ---- 3. Cumulative correlation ----
    cum_all = cumulative_spearman(trades)
    cum_asset = {ASSET_SHORT[a]: cumulative_spearman(asset_trades[a]) for a in ASSETS}

    def trajectory_summary(series: list[dict]) -> dict:
        if not series:
            return {}
        rhos = [s["rho"] for s in series if s["rho"] == s["rho"]]
        if not rhos:
            return {}
        # find first time it becomes negative & stays negative-ish
        first_neg_i = next((s["i"] for s in series if s["rho"] < 0), None)
        first_neg_t = next((s["entry_time"][:10] for s in series if s["rho"] < 0), None)
        return {
            "first_rho": series[0]["rho"],
            "first_t": series[0]["entry_time"][:10],
            "min_rho": min(rhos),
            "min_at": next(s["entry_time"][:10] for s in series if s["rho"] == min(rhos)),
            "max_rho": max(rhos),
            "max_at": next(s["entry_time"][:10] for s in series if s["rho"] == max(rhos)),
            "final_rho": series[-1]["rho"],
            "final_t": series[-1]["entry_time"][:10],
            "first_neg_i": first_neg_i,
            "first_neg_t": first_neg_t,
        }

    print("\n" + "=" * 72)
    print("3. CUMULATIVE SPEARMAN TRAJECTORY (rho computed on trades 1..i)")
    print("=" * 72)
    rows = []
    cum_summaries = {"ALL": trajectory_summary(cum_all)}
    for k, s in [("ALL", cum_all)] + [(ASSET_SHORT[a], cum_asset[ASSET_SHORT[a]]) for a in ASSETS]:
        sm = trajectory_summary(s)
        if k != "ALL":
            cum_summaries[k] = sm
        if not sm:
            rows.append([k, "-", "-", "-", "-", "-"])
            continue
        rows.append(
            [
                k,
                f"{fmt_rho(sm['first_rho'])} @ {sm['first_t']}",
                f"{fmt_rho(sm['max_rho'])} @ {sm['max_at']}",
                f"{fmt_rho(sm['min_rho'])} @ {sm['min_at']}",
                f"{fmt_rho(sm['final_rho'])} @ {sm['final_t']}",
                f"{sm['first_neg_t']} (i={sm['first_neg_i']})" if sm["first_neg_t"] else "never",
            ]
        )
    print_table(
        "  Cumulative trajectory key points",
        ["asset", "start rho", "peak rho", "trough rho", "final rho", "first turned negative"],
        rows,
    )

    # Print a coarse trajectory (10 evenly spaced points) for ALL
    print("\n  ALL cumulative rho at ~10 checkpoints:")
    if cum_all:
        idxs = [int(round(i * (len(cum_all) - 1) / 9)) for i in range(10)]
        for i in idxs:
            s = cum_all[i]
            print(f"    n={s['i']:>3}  {s['entry_time'][:10]}  rho={fmt_rho(s['rho'])}  p={fmt_p(s['p'])}")

    # ---- 4. First-month vs Later split ----
    print("\n" + "=" * 72)
    print("4. FIRST-MONTH (< 2026-04-01) vs LATER (>= 2026-04-01)")
    print("=" * 72)
    early_all, later_all = split_by_date(trades, SPLIT_DATE)
    rows = []
    split_data: dict[str, dict] = {}
    for k, sub in [
        ("ALL", trades),
        ("BTC", asset_trades["BTC-USDT"]),
        ("ETH", asset_trades["ETH-USDT"]),
        ("SOL", asset_trades["SOL-USDT"]),
    ]:
        e, l = split_by_date(sub, SPLIT_DATE)
        rho_e, p_e = safe_spearman([t["proba"] for t in e], [t["actual_r"] for t in e])
        rho_l, p_l = safe_spearman([t["proba"] for t in l], [t["actual_r"] for t in l])
        rows.append(
            [
                k,
                str(len(e)),
                fmt_rho(rho_e),
                fmt_p(p_e),
                str(len(l)),
                fmt_rho(rho_l),
                fmt_p(p_l),
                fmt_rho(rho_l - rho_e) if (rho_e == rho_e and rho_l == rho_l) else "-",
            ]
        )
        split_data[k] = {
            "early": {"n": len(e), "rho": rho_e, "p": p_e},
            "later": {"n": len(l), "rho": rho_l, "p": p_l},
        }
    print_table(
        "  Split by 2026-04-01",
        ["asset", "n_early", "rho_E", "p_E", "n_later", "rho_L", "p_L", "delta"],
        rows,
    )

    # ---- Side analysis: is_signal=True only ----
    print("\n" + "=" * 72)
    print("SIDE ANALYSIS: is_signal=True only (for comparison)")
    print("=" * 72)
    sig_trades = [t for t in trades if t.get("is_signal")]
    print(f"  is_signal=True n={len(sig_trades)}")
    rows = []
    side_data: dict[str, dict] = {}
    for k, sub in [
        ("ALL", sig_trades),
        ("BTC", [t for t in sig_trades if t["asset"] == "BTC-USDT"]),
        ("ETH", [t for t in sig_trades if t["asset"] == "ETH-USDT"]),
        ("SOL", [t for t in sig_trades if t["asset"] == "SOL-USDT"]),
    ]:
        rho, p = safe_spearman([t["proba"] for t in sub], [t["actual_r"] for t in sub])
        e, l = split_by_date(sub, SPLIT_DATE)
        rho_e, _ = safe_spearman([t["proba"] for t in e], [t["actual_r"] for t in e])
        rho_l, _ = safe_spearman([t["proba"] for t in l], [t["actual_r"] for t in l])
        rows.append(
            [
                k,
                str(len(sub)),
                fmt_rho(rho),
                fmt_p(p),
                f"{len(e)}|{fmt_rho(rho_e)}",
                f"{len(l)}|{fmt_rho(rho_l)}",
            ]
        )
        side_data[k] = {
            "n": len(sub),
            "rho": rho,
            "p": p,
            "early": {"n": len(e), "rho": rho_e},
            "later": {"n": len(l), "rho": rho_l},
        }
    print_table(
        "  is_signal=True overall + early/later",
        ["asset", "n", "rho_overall", "p", "early n|rho", "later n|rho"],
        rows,
    )

    # ---- Save JSON ----
    out = {
        "meta": {
            "n_trades": len(trades),
            "span_start": trades[0]["entry_time"],
            "span_end": trades[-1]["entry_time"],
            "split_date": SPLIT_DATE.isoformat(),
        },
        "rolling": {
            "window_15": rolling_15,
            "window_30": rolling_30,
        },
        "time_buckets": bucket_data,
        "cumulative": {
            "ALL": cum_all,
            **cum_asset,
            "summaries": cum_summaries,
        },
        "first_month_vs_later": split_data,
        "is_signal_only": side_data,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
