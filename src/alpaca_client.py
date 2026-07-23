"""Minimal Alpaca Trading API v2 client (paper).

Auth: APCA-API-KEY-ID / APCA-API-SECRET-KEY headers.
Paper base: https://paper-api.alpaca.markets

PAPER LOCK: this client refuses the live endpoint unless ALLOW_LIVE_TRADING is
set to the exact phrase below. That env var must never be set until every gate
in the roadmap passes (3+ months positive paper, attorney/DSO sign-off,
Peter's explicit approval).
"""

import os

import requests

PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE = "https://api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"
LIVE_UNLOCK_PHRASE = "yes-i-cleared-every-gate-in-the-roadmap"


class AlpacaClient:
    def __init__(self, key_id=None, secret_key=None, base_url=None, timeout=30):
        self.base = base_url or PAPER_BASE
        if self.base != PAPER_BASE:
            if os.environ.get("ALLOW_LIVE_TRADING") != LIVE_UNLOCK_PHRASE:
                raise RuntimeError(
                    "PAPER LOCK: refusing non-paper endpoint. "
                    "All roadmap gates must pass first."
                )
        self.key_id = key_id or os.environ.get("ALPACA_API_KEY_ID")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        if not (self.key_id and self.secret_key):
            raise RuntimeError("ALPACA_API_KEY_ID / ALPACA_SECRET_KEY not set")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
        })

    # -- low level --------------------------------------------------------

    def _req(self, method, path, base=None, **kwargs):
        url = (base or self.base) + path
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        if resp.text:
            return resp.json()
        return None

    def _get(self, path, params=None):
        return self._req("GET", path, params=params)

    # -- account / market state -------------------------------------------

    def account(self):
        return self._get("/v2/account")

    def clock(self):
        return self._get("/v2/clock")

    def portfolio_history(self, period="3M", timeframe="1D"):
        """Daily equity + realized P&L series straight from the paper account.
        Authoritative source for reconstructing data/paper_days.csv."""
        return self._get("/v2/account/portfolio/history",
                         params={"period": period, "timeframe": timeframe,
                                 "extended_hours": "false"}) or {}

    def positions(self):
        return self._get("/v2/positions")

    def open_orders(self):
        return self._get("/v2/orders", params={"status": "open", "limit": 500})

    def orders_after(self, after_iso, limit=500):
        """All orders (any status) created at/after after_iso - used to detect
        whether an entry session already placed trades today (cross-run truth)."""
        return self._get("/v2/orders", params={"status": "all", "after": after_iso,
                                                "limit": limit}) or []

    # -- trading (paper) ---------------------------------------------------

    def place_bracket_order(self, symbol, qty, stop_price, target_price):
        """Market entry + server-side stop loss and take profit (day order)."""
        payload = {
            "symbol": symbol,
            "qty": str(int(qty)),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(round(target_price, 2))},
            "stop_loss": {"stop_price": str(round(stop_price, 2))},
        }
        return self._req("POST", "/v2/orders", json=payload)

    def cancel_all_orders(self):
        return self._req("DELETE", "/v2/orders")

    def close_all_positions(self):
        return self._req("DELETE", "/v2/positions", params={"cancel_orders": "true"})

    # -- market data -------------------------------------------------------

    def today_bars(self, symbols, start_iso, timeframe="5Min", feed="iex"):
        """Completed intraday bars since start_iso (IEX feed = free real-time)."""
        params = {"symbols": ",".join(symbols), "timeframe": timeframe,
                  "start": start_iso, "limit": 10000, "feed": feed, "sort": "asc"}
        data = self._req("GET", "/v2/stocks/bars", base=DATA_BASE, params=params)
        return (data or {}).get("bars") or {}

    def latest_trades(self, symbols, feed="iex"):
        params = {"symbols": ",".join(symbols), "feed": feed}
        data = self._req("GET", "/v2/stocks/trades/latest", base=DATA_BASE, params=params)
        return (data or {}).get("trades") or {}

    def daily_bars(self, symbols, start, feed="iex"):
        params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                  "limit": 10000, "feed": feed, "sort": "asc"}
        data = self._req("GET", "/v2/stocks/bars", base=DATA_BASE, params=params)
        return (data or {}).get("bars") or {}

    def news(self, symbols, start, limit=50):
        params = {"symbols": ",".join(symbols), "start": start, "limit": limit,
                  "sort": "desc", "exclude_contentless": "true"}
        data = self._req("GET", "/v1beta1/news", base=DATA_BASE, params=params)
        return (data or {}).get("news") or []
