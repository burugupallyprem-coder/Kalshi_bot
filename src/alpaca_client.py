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

    def _get(self, path, params=None):
        resp = self.session.get(self.base + path, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def account(self):
        return self._get("/v2/account")

    def clock(self):
        return self._get("/v2/clock")

    def positions(self):
        return self._get("/v2/positions")
