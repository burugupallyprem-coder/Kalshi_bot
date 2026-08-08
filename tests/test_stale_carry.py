"""Safety test: a day-trading bot must START FLAT. If a prior EOD flatten failed and
positions carried overnight, the entry session must cancel + close them at open and alert -
never trade on top of a stale carry, never let it linger into a new day."""
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.live.trader as tm

ET = ZoneInfo("America/New_York")


class _StaleClient:
    def __init__(self):
        self._pos = [{"symbol": "TSLA", "qty": "10"}, {"symbol": "NVDA", "qty": "5"}]
        self._ord = [{"symbol": "TSLA"}]
        self.cancelled = 0
        self.closed = 0
    def clock(self): return {"is_open": True}
    def account(self): return {"equity": "100000", "last_equity": "100000"}
    def positions(self): return list(self._pos)
    def open_orders(self): return list(self._ord)
    def cancel_all_orders(self): self.cancelled += 1; self._ord = []
    def close_all_positions(self): self.closed += 1; self._pos = []
    def today_bars(self, symbols, start_iso, feed="iex"): return {s: [] for s in symbols}
    def place_bracket_order(self, *a, **k): return {"id": "x"}


def _cfg():
    return {"universe": ["TSLA", "NVDA", "SPY"],
            "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 20},
            "costs": {"slippage_cents": 1}, "arming": {"mode": "manual"},
            "live": {"strategy": "orb", "feed": "iex", "poll_seconds": 1,
                     "session_start_et": "09:35", "max_positions": 5,
                     "params": {"open_bars": 3, "rr": 1.5, "min_or_width_frac": 0.004},
                     "premarket": {"guard_mode": "log_only"}}}


def test_entry_session_flattens_stale_carry_at_open():
    c = _StaleClient(); posts = []
    st = {"now": datetime(2026, 7, 6, 10, 0, tzinfo=ET)}
    real_now, real_post = tm.now_et, tm.slackbot.post
    tm.now_et = lambda: st["now"]
    tm.slackbot.post = lambda *a, **k: posts.append(a[0] if a else "")

    def advance(_secs):
        st["now"] = datetime(2026, 7, 6, 10, 31, tzinfo=ET)   # past cutoff -> loop ends
    try:
        tm.run_entry_session(_cfg(), client=c, sleep_fn=advance)
    finally:
        tm.now_et, tm.slackbot.post = real_now, real_post

    assert c.cancelled >= 1, "stale open orders were not cancelled"
    assert c.closed >= 1, "stale positions were not closed"
    assert c.positions() == [], "account not flat after stale-carry cleanup"
    assert any("STALE" in p or "cleaned up" in p for p in posts), \
        f"no stale-carry Slack alert posted: {posts}"


if __name__ == "__main__":
    test_entry_session_flattens_stale_carry_at_open()
    print("PASS")
