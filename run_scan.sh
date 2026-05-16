#!/bin/bash
# Structural Edge - Scan runner for launchd (bash entrypoint).
# 권장: launchd plist는 python3 run_scan.py 를 직접 호출. 이 스크립트는 수동 실행용.
#
# Usage:
#   ./run_scan.sh             # crypto-only scan (24/7)
#   ./run_scan.sh etf-stock   # ETF/stock 스캔 (ET 개장/마감 window일 때만)
#   ./run_scan.sh summary     # 일일 요약

cd "$(dirname "$0")"
PYTHON="/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/bin/python3"

$PYTHON run_scan.py "$@"
