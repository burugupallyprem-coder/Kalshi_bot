"""Trader decision-logic tests with a mock client. Run: python tests/test_trader.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live.trader import compute_orb_signal, size_shares, run_eod_flatten
from src.live import trader as trader_mod

CFG_RISK = {"risk": {"risk_pct": 0.5, "max_position_pct": 20, "equity": 0,
                     "flat_by_et": "15:50"}}


def bar(o, h, l, c, v=10000):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


PARAMS = {"open_bars": 3, "rr": 1.5, "vol_confirm": False, "max_risk_frac": 0.02}


def test_signal_fires_on_breakout():
    bars = [bar(100, 100.5, 99.8, 100.2), bar(100.2, 100.6, 100.0, 100.4),
            bar(100.4, 100.7, 100.1, 100.3), bar(100.3, 101.2, 100.2, 101.0)]
    sig = compute_orb_signal(bars, PARAMS)
    assert sig and abs(sig["stop"] - 99.8) < 1e-9 and sig["entry_est"] == 101.0


def test_no_signal_inside_range():
    bars = [bar(100, 100.5, 99.8, 100.2), bar(100.2, 100.6, 100.0, 100.4),
            bar(100.4, 100.7, 100.1, 100.3), bar(100.3, 100.6, 100.2, 100.5)]
    assert compute_orb_signal(bars, PARAMS) is None


def test_vol_confirm_blocks_weak_breakout():
    p = {**PARAMS, "vol_confirm": True}
    bars = [bar(100, 100.5, 99.8, 100.2, 10000), bar(100.2, 100.6, 100.0, 100.4, 10000),
            bar(100.4, 100.7, 100.1, 100.3, 10000), bar(100.3, 101.2, 100.2, 101.0, 5000)]
    assert compute_orb_signal(bars, p) is None


def test_wide_range_skipped():
    bars = [bar(100, 105, 95, 100.2), bar(100.2, 100.6, 100.0, 100.4),
            bar(100.4, 100.7, 100.1, 100.3), bar(100.3, 106, 100.2, 105.5)]
    assert compute_orb_signal(bars, PARAMS) is None  # risk/price > 2%


def test_sizing():
    # equity 100k, risk 0.5% = $500; entry 101, stop 99.8 -> 1.2/share -> 416
    # value cap 20% = 20k -> 20k/101 = 198 -> capped
    assert size_shares(101.0, 99.8, 100000, CFG_RISK) == 198


class MockClient:
    def __init__(self, is_open=True):
        self._is_open = is_open
        self.cancelled = False
        self.closed = False

    def clock(self):
        return {"is_open": self._is_open}

    def positions(self):
        return [{"symbol": "AAPL"}]

    def open_orders(self):
        return []

    def cancel_all_orders(self):
        self.cancelled = True

    def close_all_positions(self):
        self.closed = True

    def account(self):
        return {"equity": "100100.00", "last_equity": "100000.00"}


def test_eod_flatten_closed_market_skips():
    c = MockClient(is_open=False)
    run_eod_flatten({"live": {}}, client=c)
    assert not c.cancelled and not c.closed


def test_eod_flatten_flattens(monkey_posts=[]):
    trader_mod.slackbot.post = lambda text, **kw: monkey_posts.append(text)
    real_now = trader_mod.now_et
    trader_mod.now_et = lambda: real_now().replace(hour=15, minute=46)
    try:
        c = MockClient(is_open=True)
        run_eod_flatten({"live": {}}, client=c)
        assert c.cancelled and c.closed
        assert monkey_posts and "[EOD]" in monkey_posts[-1]
        assert "+100.00" in monkey_posts[-1]
    finally:
        trader_mod.now_et = real_now


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
