"""
Structural Edge Trading System - Web Dashboard
================================================
Python built-in http.server based dashboard. No Flask needed.

Usage:
  python dashboard.py
  Open http://localhost:8050
"""

import json
import os
import sys
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime
import uuid

PORT = 8050
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def read_json(filename):
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def write_json(filename, data):
    path = os.path.join(BASE_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_performance_stats(trades):
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if not closed:
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": "0%", "total_pnl": 0, "avg_r": 0}
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) <= 0]
    r_vals = [t["r_multiple"] for t in closed if t.get("r_multiple") is not None]
    return {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": f"{len(wins)/len(closed)*100:.1f}%" if closed else "0%",
        "total_pnl": round(sum(t.get("pnl", 0) for t in closed), 4),
        "avg_r": round(sum(r_vals) / len(r_vals), 2) if r_vals else 0,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif path == "/api/signals":
            data = read_json("signal_log.json")
            self._json_response(data)

        elif path == "/api/trades":
            data = read_json("trade_log.json")
            self._json_response(data)

        elif path == "/api/stats":
            trades = read_json("trade_log.json")
            stats = get_performance_stats(trades)
            self._json_response(stats)

        elif path == "/api/scan":
            try:
                result = subprocess.run(
                    [sys.executable, os.path.join(BASE_DIR, "signal_engine.py")],
                    capture_output=True, text=True, timeout=300, cwd=BASE_DIR
                )
                signals = read_json("signal_log.json")
                self._json_response({
                    "status": "ok",
                    "signal_count": len(signals),
                    "output": result.stdout[-2000:] if result.stdout else "",
                    "errors": result.stderr[-500:] if result.stderr else ""
                })
            except Exception as e:
                self._json_response({"status": "error", "message": str(e)}, code=500)

        elif path == "/api/config":
            data = {}
            config_path = os.path.join(BASE_DIR, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    data = json.load(f)
            self._json_response(data)

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        data = json.loads(body)

        if path == "/api/trades":
            # Create new trade
            trades = read_json("trade_log.json")
            trade = {
                "id": data.get("id", str(uuid.uuid4())[:8]),
                "timestamp": datetime.now().isoformat(),
                "asset": data.get("asset", ""),
                "asset_type": data.get("asset_type", ""),
                "direction": data.get("direction", "Long"),
                "entry_price": float(data.get("entry_price", 0)),
                "stop_loss": float(data.get("stop_loss", 0)),
                "take_profit": float(data.get("take_profit", 0)),
                "size": float(data.get("size", 0)),
                "leverage": float(data.get("leverage", 1)),
                "reason": data.get("reason", ""),
                "psychology": data.get("psychology", ""),
                "status": "OPEN",
                "exit_price": None,
                "pnl": None,
                "r_multiple": None,
                "closed_at": None,
            }
            trades.append(trade)
            write_json("trade_log.json", trades)
            self._json_response({"status": "ok", "trade": trade})

        elif path == "/api/trades/close":
            # Close a trade
            trades = read_json("trade_log.json")
            trade_id = data.get("id")
            exit_price = float(data.get("exit_price", 0))
            fee = float(data.get("fee", 0))
            for t in trades:
                if t["id"] == trade_id and t["status"] == "OPEN":
                    entry = t["entry_price"]
                    sl = t["stop_loss"]
                    size = t.get("size", 0)
                    # P&L = (% price change * betting amount) - fee
                    if entry > 0:
                        pct_change = (exit_price - entry) / entry
                        if t["direction"] != "Long":
                            pct_change = -pct_change
                        pnl = round(pct_change * size - fee, 2)
                    else:
                        pnl = 0
                    risk = abs(entry - sl) / entry * size if entry > 0 else 0
                    r_multiple = pnl / risk if risk > 0 else 0
                    t["status"] = "CLOSED"
                    t["exit_price"] = exit_price
                    t["fee"] = fee
                    t["pnl"] = pnl
                    t["r_multiple"] = round(r_multiple, 2)
                    t["closed_at"] = datetime.now().isoformat()
                    break
            write_json("trade_log.json", trades)
            self._json_response({"status": "ok"})

        else:
            self.send_error(404)

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ════════════════════════════════════════════════════════════
# HTML Dashboard (single embedded page)
# ════════════════════════════════════════════════════════════

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Structural Edge | Trading Terminal</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%2300e676'/><text x='50%25' y='54%25' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-weight='800' font-size='16' fill='%23070a0a'>SE</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root {
  --bg-void: #07080a;
  --bg-primary: #0c0e12;
  --bg-card: #13161c;
  --bg-card-hover: #1a1e26;
  --bg-elevated: #1e222c;
  --border: #252a36;
  --border-active: #353d50;
  --text-primary: #f0f2f5;
  --text-secondary: #b0b8c8;
  --text-muted: #707a8e;
  --accent-green: #00e676;
  --accent-green-dim: #00e67633;
  --accent-red: #ff3d57;
  --accent-red-dim: #ff3d5733;
  --accent-amber: #ffc400;
  --accent-amber-dim: #ffc40033;
  --accent-blue: #448aff;
  --accent-blue-dim: #448aff33;
  --accent-cyan: #18ffff;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --font-display: 'Outfit', sans-serif;
  --radius: 6px;
  --radius-lg: 10px;
}
html { font-size: 15px; }
body {
  background: var(--bg-void);
  color: var(--text-primary);
  font-family: var(--font-mono);
  line-height: 1.7;
  min-height: 100vh;
  overflow-x: hidden;
}
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse 80% 60% at 10% 0%, #00e67608 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 90% 100%, #448aff06 0%, transparent 60%);
  pointer-events: none;
  z-index: 0;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-active); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* Header */
.header {
  position: sticky; top: 0; z-index: 100;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  padding: 0 2rem;
  display: flex; align-items: center; justify-content: space-between;
  height: 60px;
  backdrop-filter: blur(20px);
}
.header-brand {
  display: flex; align-items: center; gap: 12px;
  font-family: var(--font-display);
}
.header-brand .logo-mark {
  width: 32px; height: 32px;
  background: linear-gradient(135deg, var(--accent-green), var(--accent-cyan));
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: 15px; color: var(--bg-void);
}
.header-brand h1 {
  font-size: 1.15rem; font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.header-brand h1 span { color: var(--text-muted); font-weight: 400; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.header-clock {
  color: var(--text-secondary); font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}
.btn {
  font-family: var(--font-mono);
  font-size: 0.85rem; font-weight: 500;
  padding: 8px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn:hover { background: var(--bg-elevated); color: var(--text-primary); border-color: var(--border-active); }
.btn-primary {
  background: var(--accent-green);
  color: var(--bg-void);
  border-color: var(--accent-green);
  font-weight: 600;
}
.btn-primary:hover { background: #00ff84; box-shadow: 0 0 20px var(--accent-green-dim); }
.btn-primary:disabled {
  opacity: 0.5; cursor: not-allowed;
  background: var(--accent-green); box-shadow: none;
}
.btn-primary .spinner {
  width: 14px; height: 14px;
  border: 2px solid var(--bg-void);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  display: none;
}
.btn-primary.loading .spinner { display: block; }
.btn-primary.loading .btn-text { display: none; }
@keyframes spin { to { transform: rotate(360deg); } }
.btn-danger {
  border-color: var(--accent-red); color: var(--accent-red);
}
.btn-danger:hover { background: var(--accent-red-dim); }

/* Stat Bar */
.stat-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin: 1.5rem 2rem 0;
}
.stat-cell {
  background: var(--bg-card);
  padding: 1.1rem 1.25rem;
  display: flex; flex-direction: column; gap: 4px;
  transition: background 0.2s;
}
.stat-cell:hover { background: var(--bg-card-hover); }
.stat-label {
  font-size: 0.75rem; font-weight: 500;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.stat-value {
  font-family: var(--font-display);
  font-size: 1.6rem; font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}
.stat-value.positive { color: var(--accent-green); }
.stat-value.negative { color: var(--accent-red); }
.stat-value.neutral { color: var(--text-primary); }
.stat-sub {
  font-size: 0.75rem; color: var(--text-muted);
}

/* Tabs */
.tab-strip {
  display: flex; gap: 0;
  margin: 1.5rem 2rem 0;
  border-bottom: 1px solid var(--border);
}
.tab-btn {
  font-family: var(--font-mono);
  font-size: 0.88rem; font-weight: 500;
  padding: 12px 22px;
  color: var(--text-muted);
  background: none; border: none;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}
.tab-btn:hover { color: var(--text-secondary); }
.tab-btn.active {
  color: var(--accent-green);
  border-bottom-color: var(--accent-green);
}
.tab-count {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 20px; height: 20px;
  font-size: 0.72rem; font-weight: 600;
  background: var(--bg-elevated);
  border-radius: 10px;
  padding: 0 6px;
  margin-left: 6px;
  color: var(--text-muted);
}
.tab-btn.active .tab-count { background: var(--accent-green-dim); color: var(--accent-green); }

/* Content */
.content { padding: 1.25rem 2rem 3rem; position: relative; z-index: 1; }
.tab-panel { display: none; }
.tab-panel.active { display: block; animation: fadeUp 0.3s ease; }
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Signal Table */
.signal-grid { display: grid; grid-template-columns: 1fr; gap: 8px; }
.signal-row {
  display: grid;
  grid-template-columns: 48px 130px 1fr 100px 120px 120px 120px 70px;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.9rem;
  transition: all 0.15s;
}
.signal-row:hover { background: var(--bg-card-hover); border-color: var(--border-active); }
.signal-row-header {
  background: transparent;
  border-color: transparent;
  color: var(--text-muted);
  font-size: 0.76rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 8px 18px;
}
.signal-row-header:hover { background: transparent; border-color: transparent; }
.dir-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 44px; height: 26px;
  font-size: 0.74rem; font-weight: 700;
  border-radius: 4px;
  letter-spacing: 0.04em;
}
.dir-badge.long { background: var(--accent-green-dim); color: var(--accent-green); }
.dir-badge.short { background: var(--accent-red-dim); color: var(--accent-red); }
.asset-name { font-weight: 600; color: var(--text-primary); font-size: 0.95rem; }
.asset-type { font-size: 0.78rem; color: var(--text-muted); }
.signal-type-label {
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--text-secondary);
}
.confidence-bar {
  width: 100%; height: 5px;
  background: var(--bg-elevated);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 3px;
}
.confidence-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.8s ease;
}
.price-cell {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.rr-cell {
  font-weight: 600;
  color: var(--accent-amber);
}
.htf-badge {
  font-size: 0.74rem; font-weight: 500;
  padding: 3px 10px;
  border-radius: 4px;
  display: inline-block;
}
.htf-badge.bullish { background: var(--accent-green-dim); color: var(--accent-green); }
.htf-badge.bearish { background: var(--accent-red-dim); color: var(--accent-red); }
.htf-badge.neutral { background: var(--bg-elevated); color: var(--text-muted); }

/* Trade Log */
.trade-row {
  display: grid;
  grid-template-columns: 90px 48px 130px 110px 110px 110px 110px 80px 60px;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.9rem;
  transition: all 0.15s;
}
.trade-row:hover { background: var(--bg-card-hover); border-color: var(--border-active); }
.trade-row-header {
  background: transparent; border-color: transparent;
  color: var(--text-muted); font-size: 0.76rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  padding: 8px 18px;
}
.trade-row-header:hover { background: transparent; border-color: transparent; }
.status-dot {
  width: 9px; height: 9px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 6px;
}
.status-dot.open { background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green-dim); }
.status-dot.closed { background: var(--text-muted); }

/* Console Panel */
.console-panel {
  display: none;
  margin-top: 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.console-panel.visible { display: block; animation: fadeUp 0.3s ease; }
.console-header {
  padding: 10px 18px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
  font-size: 0.8rem; color: var(--text-muted);
}
.console-body {
  padding: 18px;
  max-height: 400px;
  overflow-y: auto;
  font-size: 0.82rem;
  line-height: 1.8;
  white-space: pre-wrap;
  color: var(--text-secondary);
}

/* Checklist */
.checklist-section {
  margin-bottom: 1.5rem;
}
.checklist-section h3 {
  font-family: var(--font-display);
  font-size: 1rem; font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.checklist-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 0.9rem;
  color: var(--text-secondary);
}
.checklist-item:hover { background: var(--bg-card-hover); border-color: var(--border-active); }
.checklist-item.checked {
  border-color: var(--accent-green-dim);
  color: var(--text-primary);
}
.checklist-item.checked .ck-box {
  background: var(--accent-green);
  border-color: var(--accent-green);
  color: var(--bg-void);
}
.ck-box {
  width: 22px; height: 22px;
  border: 2px solid var(--border-active);
  border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.75rem; font-weight: 700;
  flex-shrink: 0;
  transition: all 0.15s;
}
.checklist-progress {
  display: flex; align-items: center; gap: 14px;
  margin-bottom: 1.5rem;
  padding: 14px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.checklist-progress-bar {
  flex: 1; height: 8px;
  background: var(--bg-elevated);
  border-radius: 4px;
  overflow: hidden;
}
.checklist-progress-fill {
  height: 100%;
  background: var(--accent-green);
  border-radius: 4px;
  transition: width 0.4s ease;
}
.checklist-progress-text {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 70px;
  text-align: right;
}
.checklist-verdict {
  padding: 16px 18px;
  border-radius: var(--radius-lg);
  font-size: 1rem;
  font-weight: 600;
  text-align: center;
  margin-top: 16px;
}
.checklist-verdict.go { background: var(--accent-green-dim); color: var(--accent-green); border: 1px solid var(--accent-green); }
.checklist-verdict.caution { background: var(--accent-amber-dim); color: var(--accent-amber); border: 1px solid var(--accent-amber); }
.checklist-verdict.nogo { background: var(--accent-red-dim); color: var(--accent-red); border: 1px solid var(--accent-red); }

/* Forms */
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label {
  font-size: 0.78rem; font-weight: 500;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.form-group input, .form-group select, .form-group textarea {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  padding: 9px 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.2s;
}
.form-group input:focus, .form-group select:focus, .form-group textarea:focus {
  border-color: var(--accent-green);
}
.form-group textarea { resize: vertical; min-height: 60px; }

/* Close Trade Modal */
.modal-overlay {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.7);
  z-index: 200;
  align-items: center; justify-content: center;
}
.modal-overlay.visible { display: flex; }
.modal-box {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  min-width: 360px;
}
.modal-box h3 {
  font-family: var(--font-display);
  font-size: 1.1rem;
  margin-bottom: 16px;
  color: var(--text-primary);
}

/* Empty State */
.empty-state {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 4rem 2rem;
  color: var(--text-muted);
  text-align: center;
}
.empty-state .empty-icon {
  font-size: 2.5rem; margin-bottom: 12px; opacity: 0.3;
}
.empty-state p { font-size: 0.92rem; }

/* Filters */
.filter-bar {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 12px; flex-wrap: wrap;
}
.filter-chip {
  font-family: var(--font-mono);
  font-size: 0.8rem; font-weight: 500;
  padding: 6px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.filter-chip:hover { border-color: var(--border-active); color: var(--text-secondary); }
.filter-chip.active { border-color: var(--accent-green); color: var(--accent-green); background: var(--accent-green-dim); }

/* Scan Info */
.scan-info {
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 16px;
  font-size: 0.82rem; color: var(--text-muted);
}
.scan-info .scan-time { font-variant-numeric: tabular-nums; }

/* Responsive */
@media (max-width: 1100px) {
  .signal-row { grid-template-columns: 42px 110px 1fr 90px 100px 70px; }
  .signal-row > :nth-child(6), .signal-row > :nth-child(7) { display: none; }
  .signal-row-header > :nth-child(6), .signal-row-header > :nth-child(7) { display: none; }
}
@media (max-width: 768px) {
  .header { padding: 0 1rem; }
  .stat-bar { margin: 1rem; grid-template-columns: repeat(2, 1fr); }
  .tab-strip { margin: 1rem; overflow-x: auto; }
  .content { padding: 1rem; }
  .signal-row { grid-template-columns: 42px 90px 1fr 70px; font-size: 0.82rem; }
  .signal-row > :nth-child(n+5) { display: none; }
  .signal-row-header > :nth-child(n+5) { display: none; }
}
</style>
</head>
<body>

<!-- Header -->
<header class="header">
  <div class="header-brand">
    <div class="logo-mark">SE</div>
    <h1>Structural Edge <span>v0.3</span></h1>
  </div>
  <div class="header-actions">
    <span class="header-clock" id="clock"></span>
    <button class="btn" onclick="refreshData()">Refresh</button>
    <button class="btn btn-primary" id="scanBtn" onclick="runScan()">
      <span class="spinner"></span>
      <span class="btn-text">Run Scan</span>
    </button>
  </div>
</header>

<!-- Stats Bar -->
<div class="stat-bar" id="statBar">
  <div class="stat-cell">
    <span class="stat-label">Signals Detected</span>
    <span class="stat-value neutral" id="statSignals">--</span>
    <span class="stat-sub" id="statSignalsSub"></span>
  </div>
  <div class="stat-cell">
    <span class="stat-label">High Confidence</span>
    <span class="stat-value neutral" id="statHighConf">--</span>
    <span class="stat-sub">confidence &ge; 65%</span>
  </div>
  <div class="stat-cell">
    <span class="stat-label">Open Trades</span>
    <span class="stat-value neutral" id="statOpen">--</span>
    <span class="stat-sub" id="statOpenSub"></span>
  </div>
  <div class="stat-cell">
    <span class="stat-label">Win Rate</span>
    <span class="stat-value neutral" id="statWinRate">--</span>
    <span class="stat-sub" id="statWinSub"></span>
  </div>
  <div class="stat-cell">
    <span class="stat-label">Total P&L</span>
    <span class="stat-value neutral" id="statPnl">--</span>
    <span class="stat-sub" id="statPnlSub"></span>
  </div>
  <div class="stat-cell">
    <span class="stat-label">Avg R-Multiple</span>
    <span class="stat-value neutral" id="statAvgR">--</span>
    <span class="stat-sub">per closed trade</span>
  </div>
</div>

<!-- Tabs -->
<div class="tab-strip">
  <button class="tab-btn active" onclick="switchTab('signals', this)">
    Signals<span class="tab-count" id="tabSignalCount">0</span>
  </button>
  <button class="tab-btn" onclick="switchTab('checklist', this)">
    Checklist<span class="tab-count" id="tabCheckCount">0/15</span>
  </button>
  <button class="tab-btn" onclick="switchTab('trades', this)">
    Trades<span class="tab-count" id="tabTradeCount">0</span>
  </button>
  <button class="tab-btn" onclick="switchTab('console', this)">
    Console
  </button>
</div>

<!-- Content -->
<div class="content">

  <!-- Signals Panel -->
  <div class="tab-panel active" id="panel-signals">
    <div class="filter-bar" id="signalFilters"></div>
    <div class="scan-info" id="scanInfo"></div>
    <div class="signal-grid" id="signalGrid"></div>
  </div>

  <!-- Checklist Panel -->
  <div class="tab-panel" id="panel-checklist">
    <div class="checklist-progress">
      <span style="color:var(--text-muted);font-size:0.85rem;">Progress</span>
      <div class="checklist-progress-bar"><div class="checklist-progress-fill" id="ckProgressFill" style="width:0%"></div></div>
      <span class="checklist-progress-text" id="ckProgressText">0 / 15</span>
    </div>
    <div id="checklistContainer"></div>
    <div id="checklistVerdict"></div>
    <div style="margin-top:16px;display:flex;gap:10px;">
      <button class="btn" onclick="resetChecklist()">Reset Checklist</button>
    </div>
  </div>

  <!-- Trades Panel -->
  <div class="tab-panel" id="panel-trades">
    <details style="margin-bottom:20px;">
      <summary class="btn" style="cursor:pointer;list-style:none;display:inline-flex;">+ New Trade</summary>
      <div style="margin-top:12px;padding:18px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);">
        <div class="form-grid">
          <div class="form-group"><label>Asset <span style="color:var(--accent-red)">*</span></label><input id="tf-asset" placeholder="e.g. BTC-USD"></div>
          <div class="form-group"><label>Type</label><select id="tf-type"><option>crypto</option><option>etf</option><option>stock</option><option>bond</option></select></div>
          <div class="form-group"><label>Direction</label><select id="tf-dir"><option>Long</option><option>Short</option></select></div>
          <div class="form-group"><label>Entry Price <span style="color:var(--accent-red)">*</span></label><input id="tf-entry" type="number" step="any"></div>
          <div class="form-group"><label>Stop Loss</label><input id="tf-sl" type="number" step="any"></div>
          <div class="form-group"><label>Take Profit</label><input id="tf-tp" type="number" step="any"></div>
          <div class="form-group"><label>Size</label><input id="tf-size" type="number" step="any" value="0"></div>
          <div class="form-group"><label>Leverage</label><input id="tf-lev" type="number" step="any" value="1"></div>
        </div>
        <div class="form-grid" style="grid-template-columns:1fr 1fr;">
          <div class="form-group"><label>Reason</label><textarea id="tf-reason" rows="2"></textarea></div>
          <div class="form-group"><label>Psychology</label><textarea id="tf-psych" rows="2"></textarea></div>
        </div>
        <button class="btn btn-primary" onclick="submitTrade()" style="margin-top:8px;">Record Trade</button>
      </div>
    </details>
    <div class="signal-grid" id="tradeGrid"></div>
  </div>

  <!-- Console Panel -->
  <div class="tab-panel" id="panel-console">
    <div class="console-panel visible" id="consolePanel">
      <div class="console-header">
        <span>scan output</span>
        <span id="consoleTime"></span>
      </div>
      <div class="console-body" id="consoleBody">No scan output yet. Click "Run Scan" to start.</div>
    </div>
  </div>

</div>

<!-- Close Trade Modal -->
<div class="modal-overlay" id="closeModal">
  <div class="modal-box">
    <h3>Close Trade</h3>
    <input type="hidden" id="cm-id">
    <div class="form-group" style="margin-bottom:12px;">
      <label>Exit Price <span style="color:var(--accent-red)">*</span></label>
      <input id="cm-exit" type="number" step="any">
    </div>
    <div class="form-group" style="margin-bottom:16px;">
      <label>Trading Fee (KRW/USD)</label>
      <input id="cm-fee" type="number" step="any" value="0" placeholder="0">
    </div>
    <div style="display:flex;gap:10px;">
      <button class="btn btn-primary" onclick="confirmClose()">Close Trade</button>
      <button class="btn" onclick="hideCloseModal()">Cancel</button>
    </div>
  </div>
</div>

<script>
// State
let signalsData = [];
let tradesData = [];
let activeFilter = 'all';
let checklistState = JSON.parse(localStorage.getItem('se_checklist') || '{}');

// Clock
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleDateString('ko-KR') + ' ' +
    now.toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
setInterval(updateClock, 1000);
updateClock();

// Tab Switching
function switchTab(tabId, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-' + tabId).classList.add('active');
}

// Data Fetching
async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

async function refreshData() {
  try {
    const [signals, trades, stats] = await Promise.all([
      fetchJSON('/api/signals'),
      fetchJSON('/api/trades'),
      fetchJSON('/api/stats'),
    ]);
    signalsData = signals;
    tradesData = trades;
    renderStats(signals, trades, stats);
    renderFilters(signals);
    renderSignals(signals);
    renderTrades(trades);
  } catch (e) {
    console.error('Fetch error:', e);
  }
}

// Run Scan
async function runScan() {
  const btn = document.getElementById('scanBtn');
  btn.classList.add('loading');
  btn.disabled = true;
  try {
    const res = await fetch('/api/scan');
    const data = await res.json();
    if (data.output) {
      document.getElementById('consoleBody').textContent = data.output;
      document.getElementById('consoleTime').textContent = new Date().toLocaleTimeString('ko-KR');
    }
    await refreshData();
  } catch (e) {
    document.getElementById('consoleBody').textContent = 'Scan error: ' + e.message;
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

// Render Stats
function renderStats(signals, trades, stats) {
  const latestBatch = getLatestBatch(signals);
  const highConf = latestBatch.filter(s => s.confidence >= 65);
  const openTrades = trades.filter(t => t.status === 'OPEN');

  setStatCell('statSignals', latestBatch.length, 'neutral');
  document.getElementById('statSignalsSub').textContent = `${signals.length} total logged`;
  setStatCell('statHighConf', highConf.length, highConf.length > 0 ? 'positive' : 'neutral');
  setStatCell('statOpen', openTrades.length, openTrades.length > 0 ? 'positive' : 'neutral');
  document.getElementById('statOpenSub').textContent = `${trades.length} total trades`;
  setStatCell('statWinRate', stats.win_rate || '0%', 'neutral');
  document.getElementById('statWinSub').textContent = `${stats.wins || 0}W / ${stats.losses || 0}L`;

  const pnl = stats.total_pnl || 0;
  setStatCell('statPnl', pnl === 0 ? '--' : (pnl > 0 ? '+' : '') + pnl.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}), pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : 'neutral');
  const avgR = stats.avg_r || 0;
  setStatCell('statAvgR', avgR === 0 ? '--' : avgR.toFixed(2) + 'R', avgR > 0 ? 'positive' : avgR < 0 ? 'negative' : 'neutral');

  document.getElementById('tabSignalCount').textContent = latestBatch.length;
  document.getElementById('tabTradeCount').textContent = trades.length;
}

function setStatCell(id, value, cls) {
  const el = document.getElementById(id);
  el.textContent = value;
  el.className = 'stat-value ' + cls;
}

// Get Latest Batch
function getLatestBatch(signals) {
  if (!signals.length) return [];
  const latest = signals[signals.length - 1];
  if (!latest) return [];
  const latestTime = new Date(latest.timestamp).getTime();
  return signals.filter(s => Math.abs(new Date(s.timestamp).getTime() - latestTime) < 600000);
}

// Render Filters
function renderFilters(signals) {
  const latest = getLatestBatch(signals);
  const types = ['all', ...new Set(latest.map(s => s.asset_type))];
  const bar = document.getElementById('signalFilters');
  bar.innerHTML = types.map(t =>
    `<button class="filter-chip ${t === activeFilter ? 'active' : ''}" onclick="setFilter('${t}')">${t === 'all' ? 'All' : t}</button>`
  ).join('');

  if (latest.length > 0) {
    const ts = new Date(latest[0].timestamp);
    document.getElementById('scanInfo').innerHTML =
      `<span>Latest scan: <span class="scan-time">${ts.toLocaleString('ko-KR')}</span></span>` +
      `<span>${latest.length} signals detected</span>`;
  }
}

function setFilter(type) {
  activeFilter = type;
  renderFilters(signalsData);
  renderSignals(signalsData);
}

// Render Signals
function renderSignals(signals) {
  const grid = document.getElementById('signalGrid');
  let latest = getLatestBatch(signals);
  if (activeFilter !== 'all') latest = latest.filter(s => s.asset_type === activeFilter);

  if (!latest.length) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">&#x1f50d;</div><p>No signals detected. Run a scan to get started.</p></div>`;
    return;
  }

  latest.sort((a, b) => b.confidence - a.confidence);

  let html = `<div class="signal-row signal-row-header">
    <span></span><span>Asset</span><span>Signal</span><span>Confidence</span>
    <span>Entry</span><span>SL</span><span>TP</span><span>R:R</span>
  </div>`;

  for (const s of latest) {
    const dirCls = s.direction === 'Long' ? 'long' : 'short';
    const confColor = s.confidence >= 75 ? 'var(--accent-green)' : s.confidence >= 60 ? 'var(--accent-amber)' : 'var(--accent-red)';
    const htfCls = s.htf_bias.includes('Bull') ? 'bullish' : s.htf_bias.includes('Bear') ? 'bearish' : 'neutral';
    const fmtPrice = (p) => typeof p === 'number' ? (p >= 1000 ? p.toLocaleString('en-US', {maximumFractionDigits:2}) : p.toFixed(2)) : p;

    html += `<div class="signal-row">
      <span><span class="dir-badge ${dirCls}">${s.direction === 'Long' ? 'BUY' : 'SELL'}</span></span>
      <span><span class="asset-name">${s.asset}</span><br><span class="asset-type">${s.asset_type} &middot; ${s.timeframe}</span></span>
      <span class="signal-type-label"><span class="htf-badge ${htfCls}">${s.htf_bias}</span> ${s.signal_type}<br><span class="asset-type">${s.reason}</span></span>
      <span>
        <span style="color:${confColor};font-weight:600">${s.confidence}%</span>
        <div class="confidence-bar"><div class="confidence-fill" style="width:${s.confidence}%;background:${confColor}"></div></div>
      </span>
      <span class="price-cell">${fmtPrice(s.entry_price)}</span>
      <span class="price-cell">${fmtPrice(s.stop_loss)}</span>
      <span class="price-cell">${fmtPrice(s.take_profit)}</span>
      <span class="rr-cell">1:${s.rr_ratio}</span>
    </div>`;
  }
  grid.innerHTML = html;
}

// Render Trades
function renderTrades(trades) {
  const grid = document.getElementById('tradeGrid');
  if (!trades.length) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">&#x1f4cb;</div><p>No trade records yet. Use "+ New Trade" to record one.</p></div>`;
    return;
  }

  let html = `<div class="trade-row trade-row-header">
    <span>Status</span><span></span><span>Asset</span><span>Entry</span>
    <span>SL</span><span>TP</span><span>P&L</span><span>R-Mult</span><span></span>
  </div>`;

  for (const t of trades.slice().reverse()) {
    const dirCls = t.direction === 'Long' ? 'long' : 'short';
    const statusCls = t.status === 'OPEN' ? 'open' : 'closed';
    const pnl = t.pnl;
    const fmtPnl = (v) => v == null ? '--' : (v > 0 ? '+' : '') + v.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    const pnlStr = fmtPnl(pnl);
    const pnlColor = pnl != null ? (pnl > 0 ? 'var(--accent-green)' : 'var(--accent-red)') : 'var(--text-muted)';
    const rStr = t.r_multiple != null ? t.r_multiple.toFixed(2) + 'R' : '--';
    const fmtPrice = (p) => typeof p === 'number' ? (p >= 1000 ? p.toLocaleString('en-US', {maximumFractionDigits:2}) : p.toFixed(2)) : '--';
    const closeBtn = t.status === 'OPEN' ? `<button class="btn btn-danger" style="font-size:0.75rem;padding:4px 10px;" onclick="event.stopPropagation();showCloseModal('${t.id}')">Close</button>` : '';
    const detailId = 'td-' + t.id;
    const hasDetail = t.reason || t.psychology;

    html += `<div class="trade-row" style="cursor:${hasDetail ? 'pointer' : 'default'}" onclick="toggleTradeDetail('${detailId}')">
      <span><span class="status-dot ${statusCls}"></span>${t.status}</span>
      <span><span class="dir-badge ${dirCls}">${t.direction === 'Long' ? 'BUY' : 'SELL'}</span></span>
      <span><span class="asset-name">${t.asset}</span><br><span class="asset-type">${t.asset_type}</span></span>
      <span class="price-cell">${fmtPrice(t.entry_price)}</span>
      <span class="price-cell">${fmtPrice(t.stop_loss)}</span>
      <span class="price-cell">${fmtPrice(t.take_profit)}</span>
      <span style="color:${pnlColor};font-weight:600">${pnlStr}</span>
      <span class="rr-cell">${rStr}</span>
      <span>${closeBtn}</span>
    </div>
    ${hasDetail ? `<div id="${detailId}" style="display:none;padding:12px 18px;background:var(--bg-card);border:1px solid var(--border);border-top:none;border-radius:0 0 var(--radius) var(--radius);margin-top:-8px;margin-bottom:0;">
      ${t.reason ? `<div style="margin-bottom:${t.psychology ? '10px' : '0'}"><span style="font-size:0.74rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;">Reason</span><div style="font-size:0.88rem;color:var(--text-secondary);margin-top:4px;white-space:pre-wrap">${t.reason}</div></div>` : ''}
      ${t.psychology ? `<div><span style="font-size:0.74rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;">Psychology</span><div style="font-size:0.88rem;color:var(--text-secondary);margin-top:4px;white-space:pre-wrap">${t.psychology}</div></div>` : ''}
    </div>` : ''}`;
  }
  grid.innerHTML = html;
}

function toggleTradeDetail(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

// Submit New Trade
async function submitTrade() {
  const body = {
    asset: document.getElementById('tf-asset').value,
    asset_type: document.getElementById('tf-type').value,
    direction: document.getElementById('tf-dir').value,
    entry_price: document.getElementById('tf-entry').value,
    stop_loss: document.getElementById('tf-sl').value,
    take_profit: document.getElementById('tf-tp').value,
    size: document.getElementById('tf-size').value,
    leverage: document.getElementById('tf-lev').value,
    reason: document.getElementById('tf-reason').value,
    psychology: document.getElementById('tf-psych').value,
  };
  const missing = [];
  if (!body.asset.trim()) { missing.push('Asset'); document.getElementById('tf-asset').focus(); }
  if (!body.entry_price) { missing.push('Entry Price'); }
  if (missing.length) { alert(missing.join(' and ') + ' ' + (missing.length > 1 ? 'are' : 'is') + ' required.'); if (!body.asset.trim()) document.getElementById('tf-asset').focus(); return; }
  await fetch('/api/trades', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  // Clear form
  ['tf-asset','tf-entry','tf-sl','tf-tp','tf-size','tf-lev','tf-reason','tf-psych'].forEach(id => {
    const el = document.getElementById(id);
    if (el.tagName === 'INPUT') el.value = el.type === 'number' ? (id === 'tf-lev' ? '1' : '0') : '';
    else el.value = '';
  });
  await refreshData();
}

// Close Trade Modal
function showCloseModal(id) {
  document.getElementById('cm-id').value = id;
  document.getElementById('cm-exit').value = '';
  document.getElementById('cm-fee').value = '0';
  document.getElementById('closeModal').classList.add('visible');
}
function hideCloseModal() {
  document.getElementById('closeModal').classList.remove('visible');
}
async function confirmClose() {
  const id = document.getElementById('cm-id').value;
  const exit_price = parseFloat(document.getElementById('cm-exit').value);
  const fee = parseFloat(document.getElementById('cm-fee').value) || 0;
  if (!exit_price) { alert('Exit price is required.'); return; }
  await fetch('/api/trades/close', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id, exit_price, fee}) });
  hideCloseModal();
  await refreshData();
}

// ========== Checklist ==========
const CHECKLIST = [
  { cat: 'HTF Bias (Higher Timeframe)', items: [
    'Weekly bias direction confirmed (Bull/Bear)',
    'HTF bias matches trade direction',
    'No major news/events within 24h',
  ]},
  { cat: 'Market Structure', items: [
    'Structure Shift or BOS confirmed',
    'Liquidity sweep completed',
    'FVG or Order Block identified',
  ]},
  { cat: 'Entry Criteria', items: [
    'Entry timeframe confirmation (15m/1H)',
    'R:R ratio >= 1:2',
    'Entry at discount/premium zone',
  ]},
  { cat: 'Risk Management', items: [
    'Position size within 4.5% max loss',
    'Stop loss placed at invalidation level',
    'No overlapping correlated positions',
  ]},
  { cat: 'Psychology & Discipline', items: [
    'Not revenge trading or FOMO',
    'Emotionally neutral state',
    'Trade journal entry prepared',
  ]},
];

function renderChecklist() {
  const container = document.getElementById('checklistContainer');
  let html = '';
  let total = 0, checked = 0;

  CHECKLIST.forEach((section, si) => {
    html += `<div class="checklist-section"><h3>${section.cat}</h3>`;
    section.items.forEach((item, ii) => {
      const key = `${si}-${ii}`;
      const isChecked = checklistState[key];
      total++;
      if (isChecked) checked++;
      html += `<div class="checklist-item ${isChecked ? 'checked' : ''}" onclick="toggleCheck('${key}')">
        <div class="ck-box">${isChecked ? '&#10003;' : ''}</div>
        <span>${item}</span>
      </div>`;
    });
    html += `</div>`;
  });

  container.innerHTML = html;

  // Progress
  const pct = total > 0 ? Math.round(checked / total * 100) : 0;
  document.getElementById('ckProgressFill').style.width = pct + '%';
  document.getElementById('ckProgressText').textContent = `${checked} / ${total}`;
  document.getElementById('tabCheckCount').textContent = `${checked}/${total}`;

  // Verdict
  const verdict = document.getElementById('checklistVerdict');
  if (checked >= 13) {
    verdict.innerHTML = `<div class="checklist-verdict go">GO - ${checked}/${total} conditions met. Proceed with trade.</div>`;
  } else if (checked >= 9) {
    verdict.innerHTML = `<div class="checklist-verdict caution">CAUTION - ${checked}/${total} conditions met. Review missing items.</div>`;
  } else {
    verdict.innerHTML = `<div class="checklist-verdict nogo">NO GO - ${checked}/${total} conditions met. Do not enter trade.</div>`;
  }
}

function toggleCheck(key) {
  checklistState[key] = !checklistState[key];
  localStorage.setItem('se_checklist', JSON.stringify(checklistState));
  renderChecklist();
}

function resetChecklist() {
  checklistState = {};
  localStorage.setItem('se_checklist', '{}');
  renderChecklist();
}

// Init
renderChecklist();
refreshData();
setInterval(refreshData, 60000);
</script>
</body>
</html>
"""


def main():
    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║  Structural Edge Trading Dashboard                      ║
    ║  http://localhost:{PORT}                                  ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    print(f"  Server running on http://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop\n")

    import webbrowser
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
