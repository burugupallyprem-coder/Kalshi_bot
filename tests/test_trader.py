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
    def __init__(self, is_open=True, positions=None, open_orders=None):
        self._is_open = is_open
        self.cancelled = False
        self.closed = False
        self._positions = [{"symbol": "AAPL"}] if positions is None else positions
        self._open_orders = [] if open_orders is None else open_orders

    def clock(self):
        return {"is_open": self._is_open}

    def positions(self):
        return self._positions

    def open_orders(self):
        return self._open_orders

    def cancel_all_orders(self):
        self.cancelled = True

    def close_all_positions(self):
        self.closed = True

    def account(self):
        return {"equity": "100100.00", "last_equity": "100000.00"}


# --- EOD tests run against a throwaway ROOT so real data files are never touched.
import tempfile  # noqa: E402


def _isolated_root():
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir(exist_ok=True)
    return d


def test_eod_flatten_closed_market_carries_and_warns(monkey_posts=None):
    """Market closed at run time WITH an open position: cannot flatten, but must
    NOT silently skip - cancel stale orders, log the day, and loudly warn that
    the position carried overnight unprotected."""
    monkey_posts = [] if monkey_posts is None else monkey_posts
    real_root, real_post = trader_mod.ROOT, trader_mod.slackbot.post
    trader_mod.ROOT = _isolated_root()
    trader_mod.slackbot.post = lambda text, **kw: monkey_posts.append(text)
    try:
        c = MockClient(is_open=False, positions=[{"symbol": "AAPL"}])
        run_eod_flatten({"live": {}}, client=c)
        assert c.cancelled and not c.closed  # cannot market-close when closed
        assert monkey_posts and "WARNING" in monkey_posts[-1] and "carried" in monkey_posts[-1]
        rows = (trader_mod.ROOT / "data" / "paper_days.csv").read_text().splitlines()
        assert rows[-1].split(",")[-1] == "1"  # positions_carried = 1, logged not hidden
    finally:
        trader_mod.ROOT, trader_mod.slackbot.post = real_root, real_post


def test_eod_flatten_closed_and_flat_skips():
    # Market closed and account already flat: nothing to do, no speculative row.
    real_root = trader_mod.ROOT
    trader_mod.ROOT = _isolated_root()
    try:
        c = MockClient(is_open=False, positions=[], open_orders=[])
        run_eod_flatten({"live": {}}, client=c)
        assert not c.cancelled and not c.closed
        assert not (trader_mod.ROOT / "data" / "paper_days.csv").exists()
    finally:
        trader_mod.ROOT = real_root


def test_eod_flatten_flattens(monkey_posts=None):
    monkey_posts = [] if monkey_posts is None else monkey_posts
    real_root, real_post, real_now = (trader_mod.ROOT, trader_mod.slackbot.post,
                                      trader_mod.now_et)
    trader_mod.ROOT = _isolated_root()
    trader_mod.slackbot.post = lambda text, **kw: monkey_posts.append(text)
    trader_mod.now_et = lambda: real_now().replace(hour=15, minute=46)
    try:
        c = MockClient(is_open=True)
        run_eod_flatten({"live": {}}, client=c)
        assert c.cancelled and c.closed
        assert monkey_posts and "[EOD]" in monkey_posts[-1]
        assert "+100.00" in monkey_posts[-1]
    finally:
        trader_mod.ROOT, trader_mod.slackbot.post, trader_mod.now_et = (
            real_root, real_post, real_now)


def test_eod_dedupe_skips_second_tick():
    import csv
    real_root = trader_mod.ROOT
    trader_mod.ROOT = _isolated_root()
    log = trader_mod.ROOT / "data" / "paper_days.csv"
    today = trader_mod.now_et().strftime("%Y-%m-%d")
    with open(log, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "equity", "day_pnl", "positions_flattened", "orders_cancelled"])
        w.writerow([today, "100000.00", "0.00", "0", "0"])
    try:
        c = MockClient(is_open=True)
        run_eod_flatten({"live": {}}, client=c)
        assert not c.cancelled and not c.closed  # second tick must not double-flatten
    finally:
        trader_mod.ROOT = real_root


def test_arming_manual_always_armed():
    armed, why = trader_mod.load_arming({"arming": {"mode": "manual"}})
    assert armed and "manual" in why


def test_arming_auto_missing_file_failsafe():
    import tempfile
    real_root = trader_mod.ROOT
    trader_mod.ROOT = Path(tempfile.mkdtemp())
    try:
        armed, why = trader_mod.load_arming({"arming": {"mode": "auto"}})
        assert not armed and "missing" in why  # fail-safe: no file -> do not trade
    finally:
        trader_mod.ROOT = real_root


def test_arming_auto_reads_flag():
    import tempfile, json
    real_root = trader_mod.ROOT
    trader_mod.ROOT = Path(tempfile.mkdtemp())
    (trader_mod.ROOT / "data").mkdir()
    try:
        (trader_mod.ROOT / "data" / "arming.json").write_text(json.dumps(
            {"armed": True, "reason": "cleared gate"}))
        assert trader_mod.load_arming({"arming": {"mode": "auto"}})[0] is True
        (trader_mod.ROOT / "data" / "arming.json").write_text(json.dumps(
            {"armed": False, "reason": "no edge"}))
        assert trader_mod.load_arming({"arming": {"mode": "auto"}})[0] is False
    finally:
        trader_mod.ROOT = real_root


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
