"""
Structural Edge Trading System - Auto Scheduler
===================================================
Auto scan scheduler with weekend market closure handling.

- Crypto: 24/7 scanning (4h intervals)
- Stocks/ETF/Bonds: Weekday only (Sat/Sun skip)
- Telegram notifications respect the same schedule

Usage:
  pip install schedule --break-system-packages
  python scheduler.py
"""

import time
from datetime import datetime
from signal_engine import SignalEngine, TradeManager, TelegramNotifier, DEFAULT_CONFIG, deep_merge
import json
import os

try:
    import schedule
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False
    print("  schedule install needed: pip install schedule --break-system-packages")


def load_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            config = deep_merge(config, json.load(f))
    return config


def is_weekend():
    """Saturday=5, Sunday=6 (KST local)"""
    return datetime.now().weekday() >= 5


def _is_us_market_window():
    """ET 기준 NYSE 개장 직후(09:30–10:00) 또는 마감 직후(16:00–16:30) window 여부.
    DST 자동 처리(zoneinfo). 주말(ET)은 항상 False."""
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return True  # zoneinfo 없으면 게이트 우회 (launchd 시각에 위임)
    if now_et.weekday() >= 5:
        return False
    h, m = now_et.hour, now_et.minute
    in_open = (h == 9 and m >= 30) or (h == 10 and m == 0)
    in_close = (h == 16) or (h == 17 and m == 0)
    return in_open or in_close


def run_crypto_scan():
    """Crypto-only scan (runs 24/7 including weekends)"""
    print(f"\n{'='*60}")
    print(f"  Crypto Scan: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    config = load_config()
    engine = SignalEngine(config)
    notifier = TelegramNotifier(config)

    # Override watchlist to crypto only
    crypto_config = config.copy()
    crypto_config["watchlist"] = {
        "crypto": config["watchlist"].get("crypto", []),
        "etf": [],
        "stocks": [],
        "bonds": [],
    }
    engine = SignalEngine(crypto_config)
    signals = engine.run_full_scan()

    high_confidence = [s for s in signals if s.confidence >= 65]
    if high_confidence and notifier.enabled:
        header = f"  Crypto Signal ({len(high_confidence)}) - {datetime.now().strftime('%H:%M')}\n{'_'*30}"
        notifier.send(header)
        for sig in high_confidence[:5]:
            notifier.send(notifier.format_signal(sig))

    print(f"\n  Crypto scan done: {len(signals)} signals ({len(high_confidence)} high conf)")


def run_etf_stock_scan():
    """ETF/stock/bond 전용 스캔 (crypto 제외). market window 게이트 없음 — 호출자가 책임."""
    print(f"\n{'='*60}")
    print(f"  ETF/Stock Scan: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    config = load_config()
    notifier = TelegramNotifier(config)

    cfg = config.copy()
    cfg["watchlist"] = {
        "crypto": [],
        "etf": config["watchlist"].get("etf", []),
        "stocks": config["watchlist"].get("stocks", []),
        "bonds": config["watchlist"].get("bonds", []),
    }
    engine = SignalEngine(cfg)
    signals = engine.run_full_scan()

    high_confidence = [s for s in signals if s.confidence >= 65]
    if high_confidence and notifier.enabled:
        header = f"  ETF/Stock Signal ({len(high_confidence)}) - {datetime.now().strftime('%H:%M')}\n{'_'*30}"
        notifier.send(header)
        for sig in high_confidence[:5]:
            notifier.send(notifier.format_signal(sig))

    print(f"\n  ETF/Stock scan done: {len(signals)} signals ({len(high_confidence)} high conf)")


def run_etf_stock_scan_guarded():
    """US 시장 개장/마감 window일 때만 ETF/stock 스캔 실행."""
    if not _is_us_market_window():
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
            tag = f"ET {now_et:%a %H:%M}"
        except Exception:
            tag = "ET unknown"
        print(f"[{datetime.now()}] Out of US market open/close window ({tag}) — skipping ETF/stock scan")
        return
    run_etf_stock_scan()


def run_full_scan():
    """Full scan - skips stocks/ETF/bonds on weekends"""
    config = load_config()
    notifier = TelegramNotifier(config)

    if is_weekend():
        print(f"\n  Weekend detected - running crypto-only scan")
        run_crypto_scan()
        return

    print(f"\n{'='*60}")
    print(f"  Full Scan: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    engine = SignalEngine(config)
    signals = engine.run_full_scan()

    high_confidence = [s for s in signals if s.confidence >= 65]
    if high_confidence and notifier.enabled:
        header = f"  Signal Alert ({len(high_confidence)}) - {datetime.now().strftime('%H:%M')}\n{'_'*30}"
        notifier.send(header)
        for sig in high_confidence[:5]:
            notifier.send(notifier.format_signal(sig))

    print(f"\n  Scan done: {len(signals)} signals ({len(high_confidence)} high conf)")


def run_daily_summary():
    """Daily summary report"""
    config = load_config()
    tm = TradeManager(config)
    notifier = TelegramNotifier(config)

    stats = tm.get_performance_stats()

    summary = f"  Daily Summary - {datetime.now().strftime('%Y-%m-%d')}\n{'_'*30}\n"
    for key, val in stats.items():
        summary += f"  {key}: {val}\n"

    if is_weekend():
        summary += "\n  Weekend - TradFi markets closed"

    print(summary)
    if notifier.enabled:
        notifier.send(summary)


def main():
    if not HAS_SCHEDULE:
        print("  schedule package required.")
        print("   pip install schedule --break-system-packages")
        return

    print(f"""
    ╔══════════════════════════════════════════╗
    ║  Auto Scheduler                          ║
    ║  Weekend: crypto only                    ║
    ╚══════════════════════════════════════════╝
    """)

    # Crypto: every 4 hours (24/7)
    schedule.every(4).hours.do(run_crypto_scan)

    # ETF/stock: NYSE 개장/마감 직후 1회씩. 4개 KST 시각에 fire하고
    # 스크립트가 ET 시간으로 진짜 window 여부 검증 → DST 자동 처리.
    #   EDT 개장 09:30 ET = 22:30 KST → 22:45
    #   EST 개장 09:30 ET = 23:30 KST → 23:45
    #   EDT 마감 16:00 ET = 05:00 KST → 05:15
    #   EST 마감 16:00 ET = 06:00 KST → 06:15
    for hhmm in ("22:45", "23:45", "05:15", "06:15"):
        schedule.every().day.at(hhmm).do(run_etf_stock_scan_guarded)

    # Daily summary (KST 07:00)
    schedule.every().day.at("07:00").do(run_daily_summary)

    print("  Schedule:")
    print("    - Every 4h: crypto scan (24/7)")
    print("    - 22:45/23:45/05:15/06:15: ETF/stock scan (ET window-gated, DST-aware)")
    print("    - 07:00: daily summary")
    print(f"\n  Waiting... (Ctrl+C to stop)")

    # Run once on start (crypto only)
    run_crypto_scan()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
