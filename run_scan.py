"""
Structural Edge - LaunchAgent scan runner

Modes (sys.argv[1]):
  (none)     → crypto-only scan (24/7, fires from com.structural-edge.scan every 4h)
  etf-stock  → ETF/stock/bond scan, ET 시장 개장/마감 window일 때만 실행
  summary    → 일일 누적 성과 요약 (KST 07:00)
"""
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

mode = sys.argv[1] if len(sys.argv) > 1 else "default"

if mode == "summary":
    from scheduler import run_daily_summary
    run_daily_summary()
elif mode == "etf-stock":
    from scheduler import run_etf_stock_scan_guarded
    run_etf_stock_scan_guarded()
else:
    # crypto-only (every 4h via launchd). 주말 포함 24/7 동일 동작.
    from scheduler import run_crypto_scan
    run_crypto_scan()
