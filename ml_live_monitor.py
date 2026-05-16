"""
⚡ ML Phase 3: Live Paper Trading Monitor
==========================================
4H FVG 감지 → XGBoost 예측 → Telegram 발송 → 가상매매 추적

동작:
  - 15분마다 루프 실행
  - 4H 경계(00,04,08,12,16,20 UTC) 시 FVG 스캔
  - 모든 FVG 이벤트 로그 기록 (100%)
  - threshold 이상만 Telegram 발송 (상위 30%)
  - 오픈 포지션 SL/TP 터치 체크 (15분마다)
  - rolling 30건 calibration 모니터링

상태 파일: ml_monitor_state.json (재시작 시 자동 복구)
로그 파일: ml_monitor_log.json (전체 이벤트 기록)

사용법:
  python ml_live_monitor.py              # foreground
  nohup python ml_live_monitor.py &      # background (macOS)
  # Linux: systemd service 권장

설정:
  ml_monitor_config.json  — threshold, features, model path
  credentials.env         — TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import json
import os
import pickle
import signal
import sys
import time as _time
from datetime import datetime, timezone

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import requests

from ml_data_pipeline import (
    fetch_15m_data, resample_to_4h, detect_4h_fvg_events,
    build_features, build_labels, _calc_atr, _calc_rsi,
    FEE_TAKER_ONE_WAY, FUNDING_RATE_PER_8H, HORIZON_BARS,
)

# ═══════════════════════════════════════
# Config & State
# ═══════════════════════════════════════

CONFIG_FILE = "ml_monitor_config.json"
STATE_FILE = "ml_monitor_state.json"
LOG_FILE = "ml_monitor_log.json"

SCAN_INTERVAL_SEC = 15 * 60  # 15분
# 800 × 15m = 200h = 50 4H bars → cutoff_4h_idx ≈ 48 ≫ MA_PERIOD_4H(20)
# 300으로 운영하면 df_4h 19봉으로 잘려 higher_tf_trend가 0.5 fallback에 고정됨.
LOOKBACK_15M = 800           # feature 계산용 15분봉 수
LOOKBACK_4H = 50             # FVG 감지용 4H 봉 수

# Calibration
CALIBRATION_WINDOW = 30      # rolling 30건 통합
DRIFT_CONSECUTIVE = 10       # 상위30% 신호 중 연속 N건 LOSS → 경고

# Exit criteria (Phase 3 종료 기준)
# - 통합 상위30% 승률 ≥ 60% → 소액 실전
# - 50-60% → feature 재설계
# - < 50% → FVG ML 재검토


def load_env(filepath="credentials.env"):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> dict:
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def load_model(config: dict):
    with open(config["model_file"], "rb") as f:
        return pickle.load(f)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "last_scan_4h": {},        # {asset: "2026-03-18T04:00:00"}
        "open_positions": [],       # virtual trades
        "seen_events": [],          # [timestamp+asset] dedup
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)


def load_log() -> list:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return []


def save_log(log: list):
    # 최근 2000건만 유지
    with open(LOG_FILE, "w") as f:
        json.dump(log[-2000:], f, indent=2, ensure_ascii=False, default=str)


# ═══════════════════════════════════════
# Telegram
# ═══════════════════════════════════════

class Telegram:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)

    def send(self, message: str):
        if not self.enabled:
            print(f"  [TG OFF] {message[:80]}...")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(url, json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }, timeout=10)
        except Exception as e:
            print(f"  [TG ERROR] {e}")

    def send_signal(self, event: dict, proba: float, percentile: str,
                    threshold_30: float, threshold_20: float):
        """FVG 신호 발송 (threshold 이상만)"""
        direction = "🟢 Long" if event["type"] == "bullish" else "🔴 Short"
        entry = event.get("entry_price", 0)
        sl = event.get("sl_price", 0)
        tp_15 = event.get("tp_rr15", 0)
        tp_20 = event.get("tp_rr20", 0)

        msg = (
            f"<b>⚡ ML FVG Signal</b>\n"
            f"\n"
            f"자산: <b>{event['asset']}</b>\n"
            f"방향: {direction}\n"
            f"모델 확률: <b>{proba:.1%}</b> ({percentile})\n"
            f"\n"
            f"Entry: {entry:,.2f}\n"
            f"SL: {sl:,.2f}\n"
            f"TP (1.5R): {tp_15:,.2f}\n"
            f"TP (2.0R): {tp_20:,.2f}\n"
            f"Gap: {event.get('gap_pct', 0):.2%}\n"
            f"\n"
            f"Threshold: top30%≥{threshold_30:.4f} | top20%≥{threshold_20:.4f}\n"
            f"시간: {event['timestamp']}"
        )
        self.send(msg)

    def send_result(self, position: dict):
        """포지션 결과 발송"""
        pnl_emoji = "✅" if position["result"] == "WIN" else "❌"
        msg = (
            f"{pnl_emoji} <b>결과: {position['result']}</b>\n"
            f"\n"
            f"자산: {position['asset']}\n"
            f"방향: {position['direction']}\n"
            f"Entry: {position['entry_price']:,.2f}\n"
            f"Exit: {position['exit_price']:,.2f}\n"
            f"R: {position['actual_r']:.2f}\n"
            f"보유: {position['hold_bars']}봉 ({position['hold_bars']*15/60:.1f}h)\n"
            f"모델 확률: {position['proba']:.1%}\n"
            f"Exit 사유: {position['exit_reason']}"
        )
        self.send(msg)

    def send_drift_alert(self, stats: dict):
        """Calibration drift 경고"""
        msg = (
            f"🚨 <b>Drift Alert</b>\n"
            f"\n"
            f"최근 {stats['window']}건 상위30% 승률: {stats['top30_wr']:.1%}\n"
            f"연속 LOSS: {stats['consecutive_losses']}건\n"
            f"\n"
            f"모델 신뢰도 재검토 필요\n"
            f"기준: 상위30% 승률 50% 미만 + 10건 연속 LOSS"
        )
        self.send(msg)


# ═══════════════════════════════════════
# Data Fetch (경량 — 최근 N봉만)
# ═══════════════════════════════════════

def fetch_recent_15m(inst_id: str, limit: int = 800) -> pd.DataFrame:
    """OKX 15분봉 최근 N개 수집.

    OKX `/market/candles`는 호출당 최대 300봉이므로 N>300이면
    `/market/history-candles`로 페이징하여 부족분을 채운다.
    """
    rows: list = []

    # 1) 최신 봉
    first_limit = min(max(limit, 1), 300)
    r = requests.get(
        "https://www.okx.com/api/v5/market/candles",
        params={"instId": inst_id, "bar": "15m", "limit": str(first_limit)},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "0" or not body.get("data"):
        return pd.DataFrame()
    rows.extend(body["data"])

    # 2) 부족하면 history-candles로 과거 방향 페이징
    max_pages = max(0, (limit - len(rows) + 99) // 100) + 2
    pages = 0
    while len(rows) < limit and pages < max_pages:
        after = rows[-1][0]
        r = requests.get(
            "https://www.okx.com/api/v5/market/history-candles",
            params={"instId": inst_id, "bar": "15m", "limit": "100", "after": after},
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != "0" or not body.get("data"):
            break
        rows.extend(body["data"])
        pages += 1
        _time.sleep(0.05)

    df = pd.DataFrame(rows, columns=[
        "timestamp", "open", "high", "low", "close",
        "volume", "volCcy", "volCcyQuote", "confirm"
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df = df.sort_values("timestamp").set_index("timestamp")
    df = df[~df.index.duplicated(keep="first")]
    return df.tail(limit)


# ═══════════════════════════════════════
# Scanner: FVG 감지 + 예측
# ═══════════════════════════════════════

def scan_asset(inst_id: str, model, config: dict,
               state: dict) -> list[dict]:
    """단일 자산 4H FVG 스캔 → 예측"""
    df_15m = fetch_recent_15m(inst_id, limit=LOOKBACK_15M)
    if len(df_15m) < 100:
        return []

    df_4h = resample_to_4h(df_15m)
    if len(df_4h) < 5:
        return []

    # FVG 감지
    events = detect_4h_fvg_events(df_4h, df_15m)
    if not events:
        return []

    # 최근 이벤트만 (마지막 2개 4H 봉)
    recent_events = [e for e in events if e["cutoff_4h_idx"] >= len(df_4h) - 2]
    if not recent_events:
        return []

    features = config["features"]
    threshold_30 = config["threshold_top30"]
    threshold_20 = config["threshold_top20"]
    results = []

    for event in recent_events:
        # Dedup: 이미 본 이벤트인지
        event_key = f"{inst_id}_{event['timestamp']}"
        if event_key in state.get("seen_events", []):
            continue

        # Entry가 아직 가능한지 (entry_15m_idx가 미래여야 함)
        if event["entry_15m_idx"] >= len(df_15m):
            continue

        # Feature 계산
        feat = build_features(df_15m, df_4h, event, events)
        if feat is None:
            continue

        # Label 계산 (실제 결과 — 이미 데이터가 있으면)
        label_data = build_labels(df_15m, event)
        if label_data is None:
            continue

        # 모델 예측
        feat_df = pd.DataFrame([{f: feat.get(f, 0) for f in features}])
        proba = float(model.predict_proba(feat_df)[:, 1][0])

        # Percentile 분류
        if proba >= threshold_20:
            percentile = "상위 20%"
        elif proba >= threshold_30:
            percentile = "상위 30%"
        else:
            percentile = f"하위 ({proba:.1%})"

        is_signal = proba >= threshold_30

        record = {
            "timestamp": event["timestamp"],
            "asset": inst_id,
            "type": event["type"],
            "direction": "Long" if event["type"] == "bullish" else "Short",
            "proba": round(proba, 4),
            "percentile": percentile,
            "is_signal": is_signal,
            "entry_price": label_data["entry_price"],
            "sl_price": label_data["sl_price"],
            "risk": label_data["risk"],
            "tp_rr15": label_data.get("tp_rr15", 0),
            "tp_rr20": label_data.get("tp_rr20", 0),
            "gap_pct": event["gap_pct"],
            "gap_size": event["gap_size"],
            "features": feat,
            "event_key": event_key,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(record)

    return results


# ═══════════════════════════════════════
# Position Tracker
# ═══════════════════════════════════════

def check_open_positions(state: dict, telegram: Telegram, log: list):
    """오픈 포지션 SL/TP 터치 체크"""
    if not state["open_positions"]:
        return

    closed = []
    for pos in state["open_positions"]:
        df = fetch_recent_15m(pos["asset"], limit=10)
        if df.empty:
            continue

        latest = df.iloc[-1]
        bar_high = float(latest["high"])
        bar_low = float(latest["low"])
        bar_close = float(latest["close"])
        is_long = pos["direction"] == "Long"

        entry_time = pd.Timestamp(pos["entry_time"])
        now = pd.Timestamp.now(tz=timezone.utc)
        elapsed_bars = int((now - entry_time).total_seconds() / (15 * 60))

        sl = pos["sl_price"]
        tp = pos["tp_rr15"]  # RR 1.5 기준

        hit_sl = (bar_low <= sl) if is_long else (bar_high >= sl)
        hit_tp = (bar_high >= tp) if is_long else (bar_low <= tp)
        timeout = elapsed_bars >= HORIZON_BARS

        exit_price = None
        exit_reason = None
        result = None

        if hit_sl and hit_tp:
            exit_price = sl  # SL 우선
            exit_reason = "SL (ambiguous)"
        elif hit_sl:
            exit_price = sl
            exit_reason = "SL"
        elif hit_tp:
            exit_price = tp
            exit_reason = "TP"
        elif timeout:
            exit_price = bar_close
            exit_reason = "TIMEOUT"

        if exit_price is not None:
            raw_pnl = (exit_price - pos["entry_price"]) if is_long else (pos["entry_price"] - exit_price)
            fee = pos["entry_price"] * FEE_TAKER_ONE_WAY + exit_price * FEE_TAKER_ONE_WAY
            funding_periods = elapsed_bars // 32
            funding = pos["entry_price"] * FUNDING_RATE_PER_8H * funding_periods
            net_pnl = raw_pnl - fee - funding
            actual_r = net_pnl / pos["risk"] if pos["risk"] > 0 else 0

            if exit_reason == "TIMEOUT":
                result = "TIMEOUT"
            else:
                result = "WIN" if net_pnl > 0 else "LOSS"

            pos.update({
                "exit_price": round(exit_price, 2),
                "exit_reason": exit_reason,
                "result": result,
                "actual_r": round(actual_r, 4),
                "hold_bars": elapsed_bars,
                "fee": round(fee, 2),
                "funding": round(funding, 2),
                "net_pnl": round(net_pnl, 4),
                "closed_at": now.isoformat(),
            })

            # Log + Telegram
            log.append({"type": "result", **pos})
            telegram.send_result(pos)
            closed.append(pos)

            print(f"  {'✅' if result == 'WIN' else '❌'} {pos['asset']} {result} "
                  f"R={actual_r:.2f} ({exit_reason})")

    # 청산된 포지션 제거
    for c in closed:
        state["open_positions"].remove(c)


# ═══════════════════════════════════════
# Calibration Check
# ═══════════════════════════════════════

def check_calibration(log: list, telegram: Telegram):
    """Rolling 30건 통합 calibration 체크"""
    # 결과가 있는 signal 건만 추출
    resolved = [e for e in log
                if e.get("type") == "result"
                and e.get("result") in ("WIN", "LOSS")
                and e.get("is_signal", False)]

    if len(resolved) < CALIBRATION_WINDOW:
        return

    recent = resolved[-CALIBRATION_WINDOW:]
    wins = sum(1 for r in recent if r["result"] == "WIN")
    wr = wins / len(recent)

    # 연속 LOSS 카운트
    consecutive_losses = 0
    for r in reversed(resolved):
        if r["result"] == "LOSS":
            consecutive_losses += 1
        else:
            break

    print(f"  📊 Calibration: 최근 {len(recent)}건 승률={wr:.1%}, 연속LOSS={consecutive_losses}")

    # Drift 경고 트리거
    if wr < 0.50 and consecutive_losses >= DRIFT_CONSECUTIVE:
        stats = {
            "window": len(recent),
            "top30_wr": wr,
            "consecutive_losses": consecutive_losses,
        }
        telegram.send_drift_alert(stats)
        print("  🚨 DRIFT ALERT 발송!")


# ═══════════════════════════════════════
# Main Loop
# ═══════════════════════════════════════

def is_4h_boundary(dt: datetime) -> bool:
    """UTC 시간이 4H 경계인지 (분 단위 여유 ±5분)"""
    return dt.hour % 4 == 0 and dt.minute < 20


def main():
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║  ⚡ ML Phase 3: Live Paper Trading Monitor              ║
    ║  BTC/ETH/SOL 4H FVG → XGBoost → Telegram               ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    load_env()
    config = load_config()
    model = load_model(config)
    state = load_state()
    log = load_log()
    telegram = Telegram()

    assets = config["assets"]
    threshold_30 = config["threshold_top30"]
    threshold_20 = config["threshold_top20"]
    # Per-asset mode (added 2026-05-16 per Codex review):
    #   normal     = scan + Telegram + paper-track  (default for any asset not listed)
    #   paper_only = scan + paper-track, NO Telegram
    #   disabled   = skip the asset entirely
    asset_modes = {k: v for k, v in config.get("asset_modes", {}).items()
                   if not k.startswith("_")}

    print(f"  Assets: {', '.join(assets)}")
    print(f"  Modes: {asset_modes if asset_modes else '(all normal)'}")
    print(f"  Threshold top30%: {threshold_30:.4f}")
    print(f"  Threshold top20%: {threshold_20:.4f}")
    print(f"  Telegram: {'ON' if telegram.enabled else 'OFF'}")
    print(f"  State: {len(state.get('open_positions', []))} open, "
          f"{len(state.get('seen_events', []))} seen")
    print(f"  Log: {len(log)} entries")
    print(f"\n  루프 시작 (15분 간격)...\n")

    # Startup Telegram 알림
    resolved_signals = [e for e in log
                        if e.get("type") == "result"
                        and e.get("result") in ("WIN", "LOSS")
                        and e.get("is_signal", False)]
    telegram.send(
        f"⚡ ML Monitor 시작\n"
        f"자산: {', '.join(assets)}\n"
        f"오픈 포지션: {len(state.get('open_positions', []))}개\n"
        f"누적 신호 결과: {len(resolved_signals)}건\n"
        f"Threshold: {threshold_30:.4f}"
    )

    # Graceful shutdown
    running = True
    def handle_signal(signum, frame):
        nonlocal running
        print("\n  🛑 종료 신호 수신, 상태 저장 중...")
        save_state(state)
        save_log(log)
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    last_scan_hour = -1

    while running:
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            print(f"[{now.strftime('%Y-%m-%d %H:%M UTC')}]", end="")

            # ── 1. 오픈 포지션 체크 (매 15분) ──
            if state["open_positions"]:
                print(f" checking {len(state['open_positions'])} positions...", end="")
                check_open_positions(state, telegram, log)
                save_state(state)
                save_log(log)

            # ── 2. 4H 경계에서 FVG 스캔 ──
            if is_4h_boundary(now) and current_hour != last_scan_hour:
                last_scan_hour = current_hour
                print(f" 🔍 4H scan...", end="")

                for asset in assets:
                    mode = asset_modes.get(asset, "normal")
                    if mode == "disabled":
                        print(f"\n    ⏭️  {asset} disabled, skip")
                        continue
                    try:
                        new_events = scan_asset(asset, model, config, state)
                        for event in new_events:
                            # event 레코드에 mode 보존 (사후 분리 분석용)
                            event["asset_mode"] = mode
                            # 모든 이벤트 로그 기록 (100%)
                            log.append({"type": "event", **event})

                            # Dedup 등록
                            if "seen_events" not in state:
                                state["seen_events"] = []
                            state["seen_events"].append(event["event_key"])
                            # seen_events 최근 500개만 유지
                            state["seen_events"] = state["seen_events"][-500:]

                            # 신호 발송 (threshold 이상만)
                            if event["is_signal"]:
                                # paper_only면 Telegram 차단, 가상매매·로그는 유지
                                if mode == "normal":
                                    telegram.send_signal(
                                        event, event["proba"],
                                        event["percentile"],
                                        threshold_30, threshold_20,
                                    )

                                # 가상 포지션 오픈 (mode 무관, paper-track 항상)
                                position = {
                                    "asset": event["asset"],
                                    "asset_mode": mode,
                                    "direction": event["direction"],
                                    "entry_price": event["entry_price"],
                                    "sl_price": event["sl_price"],
                                    "tp_rr15": event["tp_rr15"],
                                    "tp_rr20": event["tp_rr20"],
                                    "risk": event["risk"],
                                    "proba": event["proba"],
                                    "percentile": event["percentile"],
                                    "is_signal": True,
                                    "entry_time": now.isoformat(),
                                    "event_key": event["event_key"],
                                }
                                state["open_positions"].append(position)

                                tag = "📱" if mode == "normal" else "📒 paper"
                                print(f"\n    {tag} {asset} {event['direction']} "
                                      f"p={event['proba']:.1%} ({event['percentile']})")
                            else:
                                # Threshold 미달도 가상 포지션으로 추적 (사후 분석용)
                                position = {
                                    "asset": event["asset"],
                                    "asset_mode": mode,
                                    "direction": event["direction"],
                                    "entry_price": event["entry_price"],
                                    "sl_price": event["sl_price"],
                                    "tp_rr15": event["tp_rr15"],
                                    "tp_rr20": event["tp_rr20"],
                                    "risk": event["risk"],
                                    "proba": event["proba"],
                                    "percentile": event["percentile"],
                                    "is_signal": False,
                                    "entry_time": now.isoformat(),
                                    "event_key": event["event_key"],
                                }
                                state["open_positions"].append(position)

                    except Exception as e:
                        print(f"\n    ❌ {asset} scan error: {e}")

                save_state(state)
                save_log(log)

                # Calibration 체크
                check_calibration(log, telegram)

            print()  # newline

        except Exception as e:
            print(f"\n  ❌ Loop error: {e}")

        # 15분 대기 (1분 단위로 체크하여 빠른 shutdown 가능)
        for _ in range(SCAN_INTERVAL_SEC // 60):
            if not running:
                break
            _time.sleep(60)

    print("  ✅ 종료 완료, 상태 저장됨")


if __name__ == "__main__":
    main()
