#!/usr/bin/env python3
"""
Stock Analyzer Dashboard — Professional live trading dashboard.
Single-click launch: python dashboard.py
Opens browser at http://localhost:8899 — everything live, everything in one view.

Project folder: D:/OpenCode/Stock/Stock Analyzer/
New files: dashboard.py (this file), dashboard.html (served UI)
Reuses: config.yaml. Writes: data/dashboard/, signals/dashboard/, signal_states/dashboard/
"""

import os, sys, json, time, threading, logging, subprocess, urllib.request, urllib.error, gzip
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, date, timedelta
from pathlib import Path
import calendar

PROJECT = Path(r"D:\OpenCode\Stock\Stock Analyzer")
PORT = 8899
LOG_FILE = PROJECT / "logs" / f"dashboard_{date.today().strftime('%Y%m%d')}.log"
DATA_DIR = PROJECT / "data" / "dashboard"
SIGNALS_DIR = PROJECT / "signals" / "dashboard"
STATES_DIR = PROJECT / "signal_states" / "dashboard"
CONFIG_PATH = PROJECT / "config.yaml"
HTML_PATH = PROJECT / "dashboard.html"

# Retention for captured data/signal/state files
RETENTION_DAYS = 30

for d in [DATA_DIR, SIGNALS_DIR, STATES_DIR, LOG_FILE.parent]:
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dashboard")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logger.addHandler(console)

# ── Default config (used if config.yaml missing or key missing) ──────────
DEFAULT_CONFIG = {
    "market": {"nifty_symbol": "NIFTY", "tv_symbols": ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY", "SBIN", "HINDUNILVR", "ITC", "BHARTIARTL", "KOTAKBANK"]},
    "strategies": ["short_20d_low_breakdown", "long_bb_reclaim", "orb"],
    "short_20d_low_breakdown": {"enabled": True, "target_pct": 1.5, "sl_pct": 3.5, "rsi_max": 50, "gap_min_pct": 0.5, "breakdown_min_pct": 0.5, "market_confirm": True, "nifty_min_pct_behind": 0.5},
    "long_bb_reclaim": {"enabled": True, "target_pct": 1.5, "sl_pct": 3.0, "rsi_min": 35, "market_confirm": False, "bb_threshold": 1.8},
    "orb": {"enabled": True, "target_pct": 1.5, "sl_pct": 2.0, "or_span": 15, "cross_min_pct": 0.3, "market_confirm": False},
}

CFG = DEFAULT_CONFIG.copy()

def load_config():
    import yaml
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        for section in DEFAULT_CONFIG:
            if section not in loaded:
                loaded[section] = DEFAULT_CONFIG[section]
            elif isinstance(DEFAULT_CONFIG[section], dict):
                for k, v in DEFAULT_CONFIG[section].items():
                    if loaded[section].get(k) is None:
                        loaded[section][k] = v
        return loaded
    except Exception as e:
        logger.warning(f"Could not load config.yaml: {e}. Using defaults.")
        return DEFAULT_CONFIG.copy()

CFG = load_config()

# ── Map config.yaml structure to dashboard expected structure ────────────────
def _map_config(loaded):
    """Transform raw config.yaml dict into the structure dashboard.py expects."""
    out = DEFAULT_CONFIG.copy()

    # Symbols from watchlist.stocks (matches config.yaml structure)
    wl = loaded.get("watchlist", {})
    stocks = wl.get("stocks", [])
    if stocks:
        out["market"]["tv_symbols"] = [s.upper() for s in stocks]

    # nifty symbol
    mkt = loaded.get("market", {})
    out["market"]["nifty_symbol"] = mkt.get("nifty_symbol", "NIFTY")

    # Strategy config mapping: config name → dashboard name
    strat_map = {
        "breakdown_20d_low": "short_20d_low_breakdown",
        "bb_reclaim_long": "long_bb_reclaim",
    }
    cfg_strats = loaded.get("strategies", {})

    # Capital
    risk = loaded.get("risk", {})
    cap = risk.get("capital")
    if cap:
        out["capital"] = float(cap)

    # Map each strategy's intraday config into dashboard expected shape
    for cfg_name, dash_name in strat_map.items():
        if cfg_name not in cfg_strats:
            continue
        sc = cfg_strats[cfg_name]
        intraday = sc.get("intraday", sc.get("intraday_long", sc))
        d = out.get(dash_name, {}).copy()
        d["enabled"] = sc.get("enabled", d.get("enabled", True))
        tgt = intraday.get("target_pct")
        if tgt is not None:
            d["target_pct"] = float(tgt)
        slp = intraday.get("sl_pct")
        if slp is not None:
            d["sl_pct"] = float(slp)
        f = d.get("filters", {}).copy()
        for k in ("rsi_min", "rsi_max", "gap_min_pct", "breakdown_min_pct",
                  "cross_min_pct", "or_span"):
            if k in intraday:
                f[k] = float(intraday[k])
        d["filters"] = f
        if "nifty_confirmation" in intraday:
            d["market_confirm"] = bool(intraday["nifty_confirmation"])
        out[dash_name] = d

    return out

CFG = _map_config(CFG)

# ── Strategy definitions ────────────────────────────────────────────────────

STRATEGY_DEFS = {
    "short_20d_low_breakdown": {
        "name": "20D Low Breakdown (SHORT)",
        "short": True,
        "target_pct": CFG.get("short_20d_low_breakdown", {}).get("target_pct", 1.5),
        "sl_pct": CFG.get("short_20d_low_breakdown", {}).get("sl_pct", 3.5),
        "filters": {
            "rsi_max": CFG.get("short_20d_low_breakdown", {}).get("rsi_max", 50),
            "gap_min_pct": CFG.get("short_20d_low_breakdown", {}).get("gap_min_pct", 0.5),
            "breakdown_min_pct": CFG.get("short_20d_low_breakdown", {}).get("breakdown_min_pct", 0.5),
        },
        "market_confirm": CFG.get("short_20d_low_breakdown", {}).get("market_confirm", True),
        "nifty_min_pct_behind": CFG.get("short_20d_low_breakdown", {}).get("nifty_min_pct_behind", 0.5),
        "enabled": CFG.get("short_20d_low_breakdown", {}).get("enabled", True),
    },
    "long_bb_reclaim": {
        "name": "BB Mid Reclaim (LONG)",
        "short": False,
        "target_pct": CFG.get("long_bb_reclaim", {}).get("target_pct", 1.5),
        "sl_pct": CFG.get("long_bb_reclaim", {}).get("sl_pct", 3.0),
        "filters": {
            "rsi_min": CFG.get("long_bb_reclaim", {}).get("rsi_min", 35),
            "bb_threshold": CFG.get("long_bb_reclaim", {}).get("bb_threshold", 1.8),
        },
        "market_confirm": CFG.get("long_bb_reclaim", {}).get("market_confirm", False),
        "enabled": CFG.get("long_bb_reclaim", {}).get("enabled", True),
    },
    "orb": {
        "name": "ORB (Both)",
        "short": False,
        "target_pct": CFG.get("orb", {}).get("target_pct", 1.5),
        "sl_pct": CFG.get("orb", {}).get("sl_pct", 2.0),
        "filters": {
            "or_span": CFG.get("orb", {}).get("or_span", 15),
            "cross_min_pct": CFG.get("orb", {}).get("cross_min_pct", 0.3),
        },
        "market_confirm": CFG.get("orb", {}).get("market_confirm", False),
        "enabled": CFG.get("orb", {}).get("enabled", True),
    },
}

# ── Shared state (thread-safe with lock) ──────────────────────────────────
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.last_update = None
        self.nifty_price = None
        self.nifty_sma20 = None
        self.regime = "UNKNOWN"
        self.symbols = CFG.get("market", {}).get("tv_symbols", [])
        self.nifty_symbol = CFG.get("market", {}).get("nifty_symbol", "NIFTY")
        # Data capture status
        self.collector_running = False
        self.collector_last_cycle_time = None
        self.collector_last_cycle_duration = None
        self.collector_cycle_errors = 0
        self.nse_ltp_status = "unknown"  # "working", "failing", "unknown"
        self.data_samples_today = 0
        self.price_history_counts = {}  # sym -> count
        self.strategy_states = {}
        for name, defn in STRATEGY_DEFS.items():
            self.strategy_states[name] = {
                "enabled": defn.get("enabled", True),
                "last_signal": None,
                "signal_count": 0,
                "filters": defn.get("filters", {}),
            }
        self.stock_data = {}
        self.price_history = {}
        self.active_signals = []
        self.uptime_seconds = 0
        self.ltp_cache = {}
        self.nifty_source = "live"  # "live" or "delayed"

    @staticmethod
    def _safe_float(val, default=None):
        """Return float(val) only if it is a valid, non-NaN number; else default."""
        if val is None:
            return default
        try:
            f = float(val)
            if f != f:  # NaN check: NaN != NaN
                return default
            return f
        except (TypeError, ValueError):
            return default

    def update(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def to_dict(self):
        with self.lock:
            # Count price history entries per symbol
            ph_counts = {}
            total_samples = 0
            for sym, hist in self.price_history.items():
                cnt = len(hist) if hist else 0
                ph_counts[sym] = cnt
                total_samples += cnt
            return {
                "running": self.running,
                "collector_running": self.collector_running,
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "nifty": {
                    "symbol": self.nifty_symbol,
                    "price": self._safe_float(self.nifty_price),
                    "sma20": self._safe_float(self.nifty_sma20),
                    "regime": self.regime,
                    "source": self.nifty_source or "live",
                },
                "symbols": self.symbols,
                "strategies": {name: {"enabled": st["enabled"], "last_signal": st["last_signal"], "signal_count": st["signal_count"], "filters": st["filters"]} for name, st in self.strategy_states.items()},
                "stock_data": {sym: dict(d) for sym, d in self.stock_data.items()},
                "price_history": {sym: list(h) for sym, h in self.price_history.items()},
                # Data capture status
                "collector_last_cycle_time": self.collector_last_cycle_time.isoformat() if self.collector_last_cycle_time else None,
                "collector_last_cycle_duration": self.collector_last_cycle_duration,
                "collector_cycle_errors": self.collector_cycle_errors,
                "nse_ltp_status": self.nse_ltp_status,
                "data_samples_today": self.data_samples_today,
                "price_history_counts": ph_counts,
                "price_history_total": total_samples,
                "active_signals": list(self.active_signals),
                "uptime_seconds": self.uptime_seconds,
                "ltp_cache": dict(self.ltp_cache),
            }

STATE = SharedState()

# ── NSE data helpers ─────────────────────────────────────────────────────

DEBUG_MODE = True  # development: always on; switch to False / env-based when production

def log_debug(msg):
    if DEBUG_MODE:
        logger.debug(msg)

def fetch_json(url, headers=None):
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "gzip",
            "Referer": "https://www.nseindia.com/",
            "X-Requested-With": "XMLHttpRequest",
        }
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    logger.info(f"FETCH_START url={url} symbol=N/A")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            if "gzip" in (resp.headers.get("Content-Encoding") or "").lower():
                raw = gzip.decompress(raw)
            body = raw.decode("utf-8")
            data = json.loads(body)
            elapsed = time.time() - t0
            logger.info(f"FETCH_OK url={url} len={len(body)} elapsed_ms={int(elapsed*1000)} keys={list(data.keys())[:5]} debug={DEBUG_MODE}")
            return data
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"FETCH_FAIL url={url} error={e} elapsed_ms={int(elapsed*1000)}")
        return None

NSE_QUOTE_API = "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
NSE_INDEX_API = "https://www.nseindia.com/api/equity-stock-indices?index=NIFTY%2050"
_MONTH_ABBR = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}

def _parse_nse_expiry(text):
    """Parse NSE 'dd-MMM-yyyy' expiry into a date. Returns None if unparseable."""
    if not text:
        return None
    try:
        day, mon, year = str(text).strip().split("-")
        return date(int(year), _MONTH_ABBR[mon.upper()], int(day))
    except (ValueError, KeyError, TypeError):
        return None

def fetch_nse_ltp(symbol):
    """Get last traded price for a cash equity symbol (NSE NextApi), with yfinance + JSONL fallbacks."""
    logger.info(f"NSE_LTP_START symbol={symbol}")
    if symbol.upper() in ("NIFTY", "NIFTY50"):
        # Index, not an equity — the equity quote API 404s on it.
        return fetch_nifty_ltp()
    url = (f"{NSE_QUOTE_API}?functionName=getSymbolData"
           f"&marketType=N&series=EQ&symbol={symbol}")
    for attempt in range(1, 3):
        try:
            logger.info(f"NSE_EQUITY_ATTEMPT symbol={symbol} attempt={attempt} url={url}")
            data = fetch_json(url)
            if data and isinstance(data, dict):
                resp = data.get("equityResponse") or []
                if resp:
                    val = (resp[0].get("tradeInfo") or {}).get("lastPrice")
                    if val is not None:
                        logger.info(f"NSE_LTP_OK symbol={symbol} source=equity price={float(val)} attempt={attempt}")
                        return float(val)
                    logger.warning(f"NSE_LTP_NULL symbol={symbol} attempt={attempt} lastPrice=None")
                else:
                    logger.warning(f"NSE_EQUITY_BAD_DATA symbol={symbol} attempt={attempt} data_keys={list(data.keys())}")
            else:
                logger.warning(f"NSE_EQUITY_BAD_DATA symbol={symbol} attempt={attempt} data_keys=None")
        except Exception as e:
            logger.error(f"NSE_EQUITY_EXCEPTION symbol={symbol} attempt={attempt} error={e}")
        if attempt < 2:
            time.sleep(0.5)
    # Final fallback: yfinance
    logger.info(f"NSE_YFINANCE_FALLBACK symbol={symbol}")
    try:
        import yfinance as yf
        ticker_symbol = f"{symbol}.NS" if symbol != "NIFTY" else "^NSEI"
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="2d")
        if not hist.empty:
            val = float(hist["Close"].iloc[-1])
            logger.info(f"NSE_LTP_OK symbol={symbol} source=yfinance price={val}")
            return val
    except Exception as e:
        logger.error(f"NSE_YFINANCE_FAIL symbol={symbol} error={e}")
    # Last resort: today's intraday JSONL file
    try:
        today_str = date.today().strftime("%Y-%m-%d")
        snap_path = DATA_DIR / f"{today_str}.jsonl"
        if snap_path.exists():
            with open(snap_path, "r", encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
                if lines and lines[-1].strip():
                    snapshot = json.loads(lines[-1])
                    stocks = snapshot.get("stocks", {})
                    if symbol in stocks and stocks[symbol].get("price"):
                        val = float(stocks[symbol]["price"])
                        logger.info(f"NSE_LTP_OK symbol={symbol} source=jsonl price={val}")
                        return val
    except Exception as e:
        logger.error(f"NSE_JSONL_FAIL symbol={symbol} error={e}")
    logger.error(f"NSE_LTP_FAIL symbol={symbol} all_attempts_exhausted")
    return None

def fetch_nifty_ltp():
    """NIFTY 50 spot index price from NSE equity-stock-indices."""
    try:
        data = fetch_json(NSE_INDEX_API)
        if data and isinstance(data, dict):
            for row in data.get("data") or []:
                if row.get("identifier") == "NIFTY 50":
                    val = row.get("lastPrice")
                    if val is not None:
                        logger.info(f"NSE_LTP_OK symbol=NIFTY source=index price={float(val)}")
                        return float(val)
            logger.warning(f"NSE_INDEX_BAD_DATA symbol=NIFTY data_keys={list(data.keys())}")
        else:
            logger.warning(f"NSE_INDEX_BAD_DATA symbol=NIFTY data_keys=None")
    except Exception as e:
        logger.error(f"NSE_INDEX_EXCEPTION symbol=NIFTY error={e}")
    return None

def fetch_nifty_fut_ltp():
    """Front-month NIFTY futures price from NSE NextApi derivatives data."""
    url = f"{NSE_QUOTE_API}?functionName=getSymbolDerivativesData&symbol=NIFTY"
    try:
        data = fetch_json(url)
        if data and isinstance(data, dict):
            rows = data.get("data") or []
            futs = [r for r in rows if r.get("instrumentType") == "FUTIDX"]
            parsed = []
            for r in futs:
                exp = _parse_nse_expiry(r.get("expiryDate"))
                if exp is not None:
                    parsed.append((exp, r))
            parsed.sort(key=lambda x: x[0])
            today = date.today()
            for exp, r in parsed:
                if exp >= today:
                    val = r.get("lastPrice")
                    if val is not None:
                        logger.info(f"NSE_LTP_OK symbol=NIFTY_FUT source=derivative price={float(val)} expiry={exp}")
                        return float(val)
            logger.warning(f"NSE_DERIV_BAD_DATA symbol=NIFTY futidx={len(futs)}")
        else:
            logger.warning(f"NSE_DERIV_BAD_DATA symbol=NIFTY data_keys=None")
    except Exception as e:
        logger.error(f"NSE_DERIV_EXCEPTION symbol=NIFTY error={e}")
    return fetch_nifty_ltp()

def nifty_20d_low():
    try:
        import yfinance as yf
        nifty = yf.download("^NSEI", period="60d", interval="1d", progress=False)
        if nifty is None or (hasattr(nifty, 'empty') and nifty.empty):
            return None, None
        lows = nifty["Low"].dropna()
        if len(lows) < 20:
            return None, None
        return float(lows.iloc[-20:].min()), float(lows.iloc[-1])
    except Exception as e:
        logger.debug(f"yfinance Nifty 20d low failed: {e}")
    return None, None

def stock_20d_low(symbol):
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        data = ticker.history(period="60d")
        if data.empty:
            return None, None
        lows = data["Low"].dropna()
        if len(lows) < 20:
            return None, None
        return lows.iloc[-20:].min(), lows.iloc[-1]
    except Exception as e:
        logger.debug(f"yfinance {symbol} 20d low failed: {e}")
    return None, None

def stock_daily_bb(src, period=20, num_std=2.0):
    import numpy as np
    if hasattr(src, "Close"):
        prices = src["Close"].values if hasattr(src, "Close") else list(src)
    elif isinstance(src, list):
        prices = np.array(src)
    else:
        return None
    if len(prices) < period:
        return None
    recent = prices[-period:]
    ma = np.mean(recent)
    std = np.std(recent)
    return {"mid": ma, "upper": ma + num_std * std, "lower": ma - num_std * std}

def rsi_from_prices(prices, period=14):
    import numpy as np
    prices = np.array(prices)
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def chart_data_for(symbol, price_history, signal=None):
    """Build chart data dict for a stock with optional signal lines."""
    data = []
    for p in (price_history or []):
        data.append({"time": p.get("time", ""), "ltp": float(p.get("ltp", 0)),
                      "high": float(p.get("high", 0)), "low": float(p.get("low", 0))})
    lines = {}
    if signal:
        if signal.get("entry"): lines["entry"] = float(signal["entry"])
        if signal.get("sl"): lines["sl"] = float(signal["sl"])
        if signal.get("target"): lines["target"] = float(signal["target"])
    result = {"stock": symbol, "data": data, "lines": lines}
    if signal and signal.get("type"):
        result["signal_type"] = signal["type"]
    return result

def calculate_charges(broker="zerodha", qty=1, price=100.0, side="buy"):
    charges = {}
    if broker == "zerodha":
        brokerage = min(20, qty * price * 0.0003)
        charges["brokerage"] = round(brokerage, 2)
        stt = qty * price * 0.001 if side == "sell" else 0
        charges["stt"] = round(stt, 2)
        exch = qty * price * 0.0000325
        charges["exchange_transaction"] = round(exch, 2)
        stamp = qty * price * 0.00015 if side == "buy" else (qty * price * 0.00015 if side == "sell" else 0)
        charges["stamp_duty"] = round(stamp, 2)
        sebi = qty * price * 0.00000001
        charges["sebi_turnover"] = round(sebi, 2)
        gst = (brokerage + exch) * 0.18
        charges["gst"] = round(gst, 2)
        charges["total"] = round(brokerage + stt + exch + stamp + sebi + gst, 2)
    else:
        charges["total"] = 0
    return charges

def get_capital():
    try:
        if "capital" in CFG and CFG["capital"]:
            return float(CFG["capital"])
    except:
        pass
    return 100000.0

def normalize_signal(sig):
    """Normalize a signal dict from any writer to the dashboard's expected shape.

    Expected keys: symbol, entry, sl, target, timestamp, type ('long'/'short'), strategy.
    Legacy writers use stock/entry_price/sl_price/target_price/time and
    type values like 'SHORT (intraday)'.
    """
    if not isinstance(sig, dict):
        return None
    out = dict(sig)

    out["symbol"] = out.get("symbol") or out.get("stock")
    out["entry"] = out.get("entry") if out.get("entry") is not None else out.get("entry_price")
    out["sl"] = out.get("sl") if out.get("sl") is not None else out.get("sl_price")
    out["target"] = out.get("target") if out.get("target") is not None else out.get("target_price")
    out["timestamp"] = out.get("timestamp") or out.get("time") or out.get("fired_at")

    # Map legacy strategy labels to the dashboard's canonical strategy ids so the
    # same stock from either writer dedupes to one row.
    legacy_strategies = {
        "20D Low Breakdown": "short_20d_low_breakdown",
        "BB Mid Reclaim": "long_bb_reclaim",
    }
    out["strategy"] = legacy_strategies.get(out.get("strategy"), out.get("strategy"))

    raw_type = str(out.get("type") or out.get("signal_type") or "").upper()
    if "SHORT" in raw_type:
        out["type"] = "short"
    elif "LONG" in raw_type:
        out["type"] = "long"
    else:
        out["type"] = "short"

    # Legacy charges use 'estimated_total'; the frontend reads charges.total.
    charges = out.get("charges")
    if isinstance(charges, dict):
        charges = dict(charges)
        if "total" not in charges:
            charges["total"] = charges.get("estimated_total", 0)
        out["charges"] = charges

    if not out.get("symbol") or out.get("entry") is None:
        return None
    return out

# ── Signal checkers (all 3 strategies) ──────────────────────────────────

def check_short_breakdown_20d(state):
    signals = []
    nifty_20d_low_val, nifty_close = nifty_20d_low()
    if nifty_20d_low_val is None:
        return signals
    sma = state.nifty_sma20 or 0
    nifty_price = state.nifty_price or 0
    behind = ((nifty_price - sma) / sma * 100) if sma else 0
    regime = "BEARISH" if behind < -0.3 else "BULLISH"
    state.regime = regime

    if state.strategy_states["short_20d_low_breakdown"]["enabled"] is False:
        return signals
    cfg = STRATEGY_DEFS["short_20d_low_breakdown"]
    if cfg["market_confirm"] and regime != "BEARISH":
        return signals
    if cfg["market_confirm"] and (nifty_price - sma) / sma * 100 > -cfg["nifty_min_pct_behind"]:
        return signals

    for sym in state.symbols:
        stock_low, stock_close = stock_20d_low(sym)
        if stock_low is None or stock_close is None:
            continue
        ltp = fetch_nse_ltp(sym)
        if ltp is None:
            continue
        gap_pct = ((ltp - stock_close) / stock_close) * 100
        if gap_pct >= cfg["filters"]["gap_min_pct"]:
            continue
        breakdown_pct = ((stock_low - ltp) / stock_low) * 100 if ltp < stock_low else 0
        if ltp < stock_low and breakdown_pct >= cfg["filters"]["breakdown_min_pct"]:
            entry = ltp
            sl = round(entry * (1 + cfg["sl_pct"] / 100), 2)
            target = round(entry * (1 - cfg["target_pct"] / 100), 2)
            est_qty = max(10, min(200, int(get_capital() / entry * 0.4)))
            charges = calculate_charges("zerodha", est_qty, entry, "sell")
            signal = {
                "type": "short",
                "strategy": "short_20d_low_breakdown",
                "symbol": sym,
                "entry": round(entry, 2),
                "sl": sl,
                "target": target,
                "sl_pct": cfg["sl_pct"],
                "target_pct": cfg["target_pct"],
                "qty_est": est_qty,
                "gap_pct": round(gap_pct, 2),
                "breakdown_pct": round(breakdown_pct, 2),
                "stock_20d_low": round(stock_low, 2),
                "nifty_20d_low": round(nifty_20d_low_val, 2),
                "nifty_close": round(nifty_price, 2),
                "nifty_sma20": round(sma, 2),
                "regime": regime,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "charges": charges,
            }
            signals.append(signal)
            state.strategy_states["short_20d_low_breakdown"]["last_signal"] = signal
            state.strategy_states["short_20d_low_breakdown"]["signal_count"] += 1
    return signals

def check_long_bb_reclaim(state):
    signals = []
    if state.strategy_states["long_bb_reclaim"]["enabled"] is False:
        return signals
    cfg = STRATEGY_DEFS["long_bb_reclaim"]

    for sym in state.symbols:
        try:
            import yfinance as yf
            ticker = yf.Ticker(f"{sym}.NS")
            hist = ticker.history(period="30d", interval="1d")
            if hist.empty:
                continue
            prices = hist["Close"].values
            bb = stock_daily_bb(hist, 20, 2.0)
            if bb is None:
                continue
            ltp = fetch_nse_ltp(sym)
            if ltp is None:
                continue
            rsi_val = float(rsi_from_prices(prices, 14)) if rsi_from_prices(prices, 14) is not None else None
            if rsi_val is None:
                continue
            if rsi_val > cfg["filters"]["rsi_min"]:
                continue
            prev_close_val = float(hist["Close"].iat[-2])
            if ltp > bb["mid"] and prev_close_val < bb["mid"]:
                entry = ltp
                sl = round(entry * (1 - cfg["sl_pct"] / 100), 2)
                target = round(entry * (1 + cfg["target_pct"] / 100), 2)
                est_qty = max(10, min(200, int(get_capital() / entry * 0.4)))
                charges = calculate_charges("zerodha", est_qty, entry, "buy")
                signal = {
                    "type": "long",
                    "strategy": "long_bb_reclaim",
                    "symbol": sym,
                    "entry": round(entry, 2),
                    "sl": sl,
                    "target": target,
                    "sl_pct": cfg["sl_pct"],
                    "target_pct": cfg["target_pct"],
                    "qty_est": est_qty,
                    "rsi": round(rsi_val, 1),
                    "bb_mid": round(bb["mid"], 2),
                    "bb_lower": round(bb["lower"], 2),
                    "nifty_close": round(state.nifty_price or 0, 2),
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "charges": charges,
                }
                signals.append(signal)
                state.strategy_states["long_bb_reclaim"]["last_signal"] = signal
                state.strategy_states["long_bb_reclaim"]["signal_count"] += 1
        except Exception as e:
            logger.debug(f"BB reclaim check failed for {sym}: {e}")
    return signals

def check_orb(state):
    signals = []
    if state.strategy_states["orb"]["enabled"] is False:
        return signals
    cfg = STRATEGY_DEFS["orb"]
    or_span = cfg["filters"]["or_span"]

    for sym in state.symbols:
        hist = state.price_history.get(sym, [])
        if len(hist) < or_span:
            continue
        or_candles = hist[:or_span]
        or_high = max(c["high"] for c in or_candles)
        or_low = min(c["low"] for c in or_candles)
        or_mid = (or_high + or_low) / 2
        last = hist[-1]
        ltp = last["ltp"]
        if ltp > or_high:
            cross_pct = ((ltp - or_high) / or_high) * 100
            if cross_pct >= cfg["filters"]["cross_min_pct"]:
                entry = ltp
                sl = round(entry * (1 - cfg["sl_pct"] / 100), 2)
                target = round(entry * (1 + cfg["target_pct"] / 100), 2)
                est_qty = max(10, min(200, int(get_capital() / entry * 0.4)))
                charges = calculate_charges("zerodha", est_qty, entry, "buy")
                signal = {
                    "type": "long",
                    "strategy": "orb",
                    "symbol": sym,
                    "entry": round(entry, 2),
                    "sl": sl,
                    "target": target,
                    "sl_pct": cfg["sl_pct"],
                    "target_pct": cfg["target_pct"],
                    "qty_est": est_qty,
                    "or_high": round(or_high, 2),
                    "or_low": round(or_low, 2),
                    "or_mid": round(or_mid, 2),
                    "cross_pct": round(cross_pct, 2),
                    "nifty_close": round(state.nifty_price or 0, 2),
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "charges": charges,
                }
                signals.append(signal)
                state.strategy_states["orb"]["last_signal"] = signal
                state.strategy_states["orb"]["signal_count"] += 1
        elif ltp < or_low:
            cross_pct = ((or_low - ltp) / or_low) * 100
            if cross_pct >= cfg["filters"]["cross_min_pct"]:
                entry = ltp
                sl = round(entry * (1 + cfg["sl_pct"] / 100), 2)
                target = round(entry * (1 - cfg["target_pct"] / 100), 2)
                est_qty = max(10, min(200, int(get_capital() / entry * 0.4)))
                charges = calculate_charges("zerodha", est_qty, entry, "sell")
                signal = {
                    "type": "short",
                    "strategy": "orb",
                    "symbol": sym,
                    "entry": round(entry, 2),
                    "sl": sl,
                    "target": target,
                    "sl_pct": cfg["sl_pct"],
                    "target_pct": cfg["target_pct"],
                    "qty_est": est_qty,
                    "or_high": round(or_high, 2),
                    "or_low": round(or_low, 2),
                    "or_mid": round(or_mid, 2),
                    "cross_pct": round(cross_pct, 2),
                    "nifty_close": round(state.nifty_price or 0, 2),
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "charges": charges,
                }
                signals.append(signal)
                state.strategy_states["orb"]["last_signal"] = signal
                state.strategy_states["orb"]["signal_count"] += 1
    return signals

def run_strategy_checks(state):
    all_signals = []
    all_signals.extend(check_short_breakdown_20d(state))
    all_signals.extend(check_long_bb_reclaim(state))
    all_signals.extend(check_orb(state))
    return all_signals

# ── Collector thread ─────────────────────────────────────────────────────

class Collector(threading.Thread):
    def __init__(self, state):
        super().__init__(daemon=True)
        self.state = state
        self.active = False

    def run(self):
        logger.info("Collector thread started.")
        while self.active:
            try:
                cycle_start = time.time()
                now = datetime.now()
                elapsed = 0.0  # initialized early; updated at cycle end

                self._cleanup_old_files(now)

                if now.weekday() >= 5:
                    STATE.update(collector_running=False, nse_ltp_status="market_closed_weekend")
                    logger.info("Market closed: weekend.")
                    time.sleep(60)
                    continue
                if now.hour < 9 or (now.hour == 15 and now.minute > 30) or now.hour > 15:
                    STATE.update(collector_running=False, nse_ltp_status="market_closed_after_hours")
                    logger.info("Market closed: after 15:30 IST.")
                    # Auto-resume when approaching/open: if running=True and hour==9 and minute>=15, break out to collect
                    if STATE.running and now.hour == 9 and now.minute >= 15:
                        logger.info("Auto-resume at market open (9:15).")
                    else:
                        time.sleep(60)
                        continue

                nifty_price = fetch_nifty_ltp() or fetch_nifty_fut_ltp()
                nifty_source = "live" if nifty_price else "delayed"
                # Fallback: if NSE is down, use yfinance for Nifty price
                if not nifty_price:
                    try:
                        import yfinance as yf
                        nifty_yf_hist = yf.download("^NSEI", period="5d", interval="1d", progress=False)
                        if nifty_yf_hist is not None and not nifty_yf_hist.empty:
                            last_close = nifty_yf_hist["Close"].dropna().iloc[-1]
                            if hasattr(last_close, 'item'):
                                nifty_price = float(last_close.item())
                            else:
                                nifty_price = float(last_close)
                    except Exception:
                        pass
                nifty_sma20 = None
                try:
                    import yfinance as yf
                    nifty_hist = yf.download("^NSEI", period="20d", interval="1d", progress=False)
                    if nifty_hist is not None and not nifty_hist.empty:
                        sma_series = nifty_hist["Close"].rolling(20).mean()
                        last_val = sma_series.iloc[-1]
                        nifty_sma20 = float(last_val) if not hasattr(last_val, '__iter__') else float(last_val.iloc[0] if hasattr(last_val, 'iloc') else last_val.item())
                except:
                    pass

                self.state.update(
                    nifty_price=nifty_price,
                    nifty_source=nifty_source,
                    nifty_sma20=round(nifty_sma20, 2) if nifty_sma20 and nifty_sma20 == nifty_sma20 else None,
                    last_update=now,
                    collector_running=True,
                    collector_last_cycle_time=now,
                    collector_last_cycle_duration=round(elapsed, 2),
                    active_signals=list(self.state.active_signals),
                )

                # Track NSE LTP status
                nse_working = nifty_price is not None
                stocks_with_ltp = 0
                for sym in self.state.symbols:
                    ltp = fetch_nse_ltp(sym)
                    if ltp:
                        stocks_with_ltp += 1
                        self.state.stock_data[sym] = {
                            "time": now.strftime("%H:%M:%S"),
                            "price": round(ltp, 2),
                            "high": round(ltp, 2),
                            "low": round(ltp, 2),
                        }
                        if sym not in self.state.price_history:
                            self.state.price_history[sym] = []
                        self.state.price_history[sym].append({
                            "time": now.strftime("%H:%M:%S"),
                            "ltp": round(ltp, 2),
                            "high": round(ltp, 2),
                            "low": round(ltp, 2),
                        })
                        if len(self.state.price_history[sym]) > 200:
                            self.state.price_history[sym] = self.state.price_history[sym][-200:]

                state_str = now.strftime("%Y-%m-%d")
                # Update data capture status
                # Only count samples that actually have LTP data
                total_captured = stocks_with_ltp
                self.state.update(
                    nse_ltp_status="working" if (nse_working and stocks_with_ltp == len(self.state.symbols)) else ("partial" if stocks_with_ltp > 0 else "failing"),
                    data_samples_today=self.state.data_samples_today + total_captured,
                    price_history_counts={sym: max(0, len(self.state.price_history.get(sym, []))) for sym in self.state.symbols},
                )
                snapshot = {
                    "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "nifty": round(nifty_price, 2) if nifty_price else None,
                    "stocks": {sym: dict(d) for sym, d in self.state.stock_data.items()},
                }
                snap_path = DATA_DIR / f"{state_str}.jsonl"
                with open(snap_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(snapshot) + "\n")

                signals = run_strategy_checks(self.state)

                # Merge newly detected signals into active_signals so the frontend
                # (which reads state.active_signals) sees them live.
                if signals:
                    merged = {f"{s['strategy']}_{s['symbol']}": s for s in self.state.active_signals}
                    for sig in signals:
                        merged[f"{sig['strategy']}_{sig['symbol']}"] = sig
                    self.state.active_signals = list(merged.values())

                signal_file = SIGNALS_DIR / f"signals_live_{state_str}.json"
                existing = {}
                if signal_file.exists():
                    try:
                        with open(signal_file, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                    except:
                        existing = {}
                if signals:
                    for sig in signals:
                        key = f"{sig['strategy']}_{sig['symbol']}"
                        existing[key] = sig
                with open(signal_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2, ensure_ascii=False)

                state_file = STATES_DIR / f"states_{state_str}.json"
                state_data = self.state.to_dict()
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2, ensure_ascii=False)

                elapsed = time.time() - cycle_start
                logger.debug(f"Collector cycle done in {elapsed:.2f}s — {len(signals)} new signals")
                if elapsed < 60:
                    time.sleep(60 - elapsed)
            except Exception as e:
                logger.error(f"Collector cycle error: {e}")
                time.sleep(10)

    def _cleanup_old_files(self, now):
        """Delete captured data/signal/state files older than RETENTION_DAYS."""
        cutoff = now.date() - timedelta(days=RETENTION_DAYS)
        for directory, pattern in ((DATA_DIR, "*.jsonl"),
                                   (SIGNALS_DIR, "signals_live_*.json"),
                                   (STATES_DIR, "states_*.json")):
            for f in directory.glob(pattern):
                try:
                    file_date = datetime.strptime(f.stem.split("_")[-1], "%Y-%m-%d").date()
                    if file_date < cutoff:
                        f.unlink()
                        logger.info(f"Cleaned up old file: {f.name}")
                except Exception:
                    pass

    def stop(self):
        self.active = False
        logger.info("Collector stop requested.")

# ── HTTP server ──────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"HTTP: {args[0]}")

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        if not HTML_PATH.exists():
            self.send_error(404, f"dashboard.html not found at {HTML_PATH}")
            return
        with open(HTML_PATH, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send_html()
        elif self.path.startswith("/api/"):
            path = self.path.split("?")[0]
            params = {}
            if "?" in self.path:
                for p in self.path.split("?")[1].split("&"):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        params[k] = v
            if path == "/api/status":
                data = STATE.to_dict()
                # Enrich Nifty with yfinance fallback if NSE is down
                nifty_data = data.get("nifty", {})
                if not nifty_data.get("price"):
                    try:
                        import yfinance as yf
                        hist = yf.download("^NSEI", period="5d", interval="1d", progress=False)
                        if hist is not None and not hist.empty:
                            last = hist["Close"].dropna().iloc[-1]
                            price = float(last.item()) if hasattr(last, 'item') else float(last)
                            if price and price == price:  # NaN check
                                nifty_data["price"] = round(price, 2)
                                nifty_data["source"] = "delayed"
                                # Also get SMA20
                                hist20 = yf.download("^NSEI", period="20d", interval="1d", progress=False)
                                if hist20 is not None and not hist20.empty:
                                    smas = hist20["Close"].rolling(20).mean()
                                    last_sma = smas.iloc[-1]
                                    sma_val = float(last_sma.item()) if hasattr(last_sma, 'item') else float(last_sma)
                                    if sma_val and sma_val == sma_val:
                                        nifty_data["sma20"] = round(sma_val, 2)
                    except Exception:
                        pass
                data["nifty"] = nifty_data
                self._send_json(200, data)
            elif path == "/api/chart_data":
                stock = params.get("stock", "").upper()
                signal = None
                if "signal" in params:
                    try:
                        import json as _json
                        signal = _json.loads(params["signal"])
                    except:
                        signal = None
                if stock and stock in STATE.price_history:
                    data = chart_data_for(stock, STATE.price_history[stock], signal)
                    self._send_json(200, data)
                else:
                    self._send_json(200, {"stock": stock, "data": [], "lines": {}})
            elif path == "/api/strategies":
                self._send_json(200, STRATEGY_DEFS)
            else:
                self._send_json(404, {"error": "not found"})
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            data = json.loads(body) if body else {}
        except:
            data = {}

        if path == "/api/start":
            if STATE.running:
                self._send_json(200, {"status": "running", "message": "Already running"})
            else:
                STATE.running = True
                STATE.collector_running = True
                if not COLLECTOR.active:
                    COLLECTOR.active = True
                    COLLECTOR.start()
                logger.info("Collector started via /api/start")
                self._send_json(200, {"status": "started", "running": True})
            return
        elif path == "/api/reload":
            import importlib
            import dashboard as d
            importlib.reload(d)
            logger.info("Module reloaded via /api/reload")
            self._send_json(200, {"reloaded": True})
            return
        elif path == "/api/stop":
            if STATE.running:
                STATE.running = False
                STATE.collector_running = False
                COLLECTOR.active = False
                logger.info("Collector stopped via /api/stop")
                self._send_json(200, {"status": "stopped", "running": False})
            else:
                self._send_json(200, {"status": "already stopped"})
            return
        elif path == "/api/toggle_strategy":
            name = data.get("name", "").strip()
            enabled = data.get("enabled", True)
            if name in STRATEGY_DEFS:
                STRATEGY_DEFS[name]["enabled"] = enabled
                STATE.strategy_states[name]["enabled"] = enabled
                log_fn = logger.info
                logger.info(f"Strategy '{name}' toggled → {'enabled' if enabled else 'disabled'}")
                self._send_json(200, {"success": True, "name": name, "enabled": enabled})
            else:
                self._send_json(400, {"error": f"Unknown strategy: {name}"})
        elif path == "/api/configure":
            name = data.get("name", "").strip()
            updates = data.get("updates", {})
            if name in STRATEGY_DEFS:
                strat = STRATEGY_DEFS[name]
                for k, v in updates.items():
                    if k in strat:
                        strat[k] = v
                    elif k in strat.get("filters", {}):
                        strat["filters"][k] = v
                STATE.strategy_states[name]["filters"] = strat.get("filters", {})
                logger.info(f"Strategy '{name}' configured: {updates}")
                self._send_json(200, {"success": True, "name": name, "updates": updates})
            else:
                self._send_json(400, {"error": f"Unknown strategy: {name}"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

COLLECTOR = Collector(STATE)

def main():
    global COLLECTOR
    logger.info("=" * 60)
    logger.info("STOCK ANALYZER DASHBOARD — Professional Live Dashboard")
    logger.info(f"Project: {PROJECT}")
    logger.info(f"Port: http://localhost:{PORT}")
    logger.info(f"Built-in strategies: {len(STRATEGY_DEFS)}")
    logger.info("=" * 60)

    server = HTTPServer(("localhost", PORT), DashboardHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    logger.info(f"Server running on http://localhost:{PORT}")

    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")
        logger.info("Browser opened.")
    except Exception as e:
        logger.warning(f"Could not auto-open browser: {e}")
        logger.info(f"Open manually: http://localhost:{PORT}")

    STATE.running = False
    STATE.collector_running = False
    logger.info("Dashboard started. Collector not started - use Start button to begin.")

    # Load today's signals from disk into active_signals.
    # The dashboard writes to signals/dashboard/; the legacy writers (intraday.py,
    # scan_intraday.py) write to signals/ with a different schema — read both and
    # normalize, without modifying the other writer's file.
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        loaded = {}
        for directory in (SIGNALS_DIR, SIGNALS_DIR.parent):
            signal_file = directory / f"signals_live_{today_str}.json"
            if not signal_file.exists():
                continue
            try:
                with open(signal_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as e:
                logger.warning(f"Could not read {signal_file.name}: {e}")
                continue
            items = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            for item in items:
                norm = normalize_signal(item)
                if norm:
                    loaded[f"{norm['strategy']}_{norm['symbol']}"] = norm
        STATE.active_signals = list(loaded.values())
        logger.info(f"Loaded {len(STATE.active_signals)} signals from today's signal files")
    except Exception as e:
        logger.warning(f"Failed to load today's signals: {e}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
        COLLECTOR.stop()
        server.shutdown()
        sys.exit(0)

if __name__ == "__main__":
    main()
