"""Live entry-session filter tests (regime / relative-strength / vol floor)."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live import trader as tm

ET = ZoneInfo("America/New_York")


def bar(o, h, l, c, v=10000):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


PARAMS = {"open_bars": 3, "rr": 1.5, "vol_confirm": False, "max_risk_frac": 0.02,
          "min_or_width_frac": 0.004, "regime_filter": True, "rs_topk": 5,
          "cutoff_et": "10:30"}

# NVDA: OR high 100.7 / low 99.8 (width ~0.9%), then breaks to 101.2
# NVDA: strong opening drive (early return ~1%) AND breaks its OR high -> should
# rank above SPY on relative strength.
NVDA = [bar(100, 100.9, 99.9, 100.7), bar(100.7, 101.0, 100.5, 100.9),
        bar(100.9, 101.1, 100.7, 101.0), bar(101.0, 101.8, 100.9, 101.6)]
# SPY breaks its own OR up (regime = up)
SPY_UP = [bar(100, 100.5, 99.8, 100.2), bar(100.2, 100.6, 100.0, 100.4),
          bar(100.4, 100.7, 100.1, 100.3), bar(100.3, 101.2, 100.2, 101.0)]
# SPY stuck inside its OR (regime = down/neutral)
SPY_FLAT = [bar(100, 100.5, 99.8, 100.2), bar(100.2, 100.6, 100.0, 100.4),
            bar(100.4, 100.7, 100.1, 100.3), bar(100.3, 100.65, 100.2, 100.5)]
# XOM: no breakout (stays in range)
XOM = [bar(50, 50.3, 49.8, 50.1), bar(50.1, 50.3, 49.9, 50.2),
       bar(50.2, 50.35, 49.95, 50.1), bar(50.1, 50.3, 50.0, 50.2)]
# narrow-range name: breaks out but OR width < 0.4% -> vol floor should block
NARROW = [bar(200, 200.2, 199.95, 200.1), bar(200.1, 200.25, 200.0, 200.2),
          bar(200.2, 200.3, 200.05, 200.25), bar(200.25, 200.9, 200.2, 200.8)]


def test_compute_orb_signal_vol_floor_blocks_narrow():
    assert tm.compute_orb_signal(NARROW, PARAMS) is None            # width < 0.004
    assert tm.compute_orb_signal(NVDA, PARAMS) is not None          # wide enough


class EntryMock:
    def __init__(self, bars):
        self.bars = bars
        self.placed = []

    def clock(self):
        return {"is_open": True}

    def account(self):
        return {"equity": "100000"}

    def positions(self):
        return []

    def open_orders(self):
        return []

    def today_bars(self, symbols, start_iso, feed="iex"):
        return {s: self.bars.get(s, []) for s in symbols}

    def place_bracket_order(self, sym, qty, stop, target):
        self.placed.append(sym)
        return {"id": "testorder1234"}


def _cfg(universe, params):
    return {"universe": universe,
            "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 20},
            "costs": {"slippage_cents": 1},
            "arming": {"mode": "manual"},
            "live": {"strategy": "orb", "feed": "iex", "poll_seconds": 1,
                     "session_start_et": "09:35", "max_positions": 5, "params": params,
                     "premarket": {"guard_mode": "log_only"}}}


def _run(cfg, client):
    """Drive one poll then force the session clock past cutoff to exit."""
    state = {"now": datetime(2026, 7, 6, 10, 0, tzinfo=ET)}
    real_now, real_post = tm.now_et, tm.slackbot.post
    tm.now_et = lambda: state["now"]
    tm.slackbot.post = lambda *a, **k: None

    def advance(_secs):
        state["now"] = datetime(2026, 7, 6, 10, 31, tzinfo=ET)  # past cutoff -> loop ends
    try:
        tm.run_entry_session(cfg, client=client, sleep_fn=advance)
    finally:
        tm.now_et, tm.slackbot.post = real_now, real_post


def test_regime_up_breakout_places_order():
    c = EntryMock({"SPY": SPY_UP, "NVDA": NVDA, "XOM": XOM})
    _run(_cfg(["SPY", "NVDA", "XOM"], PARAMS), c)
    assert "NVDA" in c.placed and "XOM" not in c.placed


def test_regime_down_stands_down_no_orders():
    c = EntryMock({"SPY": SPY_FLAT, "NVDA": NVDA, "XOM": XOM})
    _run(_cfg(["SPY", "NVDA", "XOM"], PARAMS), c)
    assert c.placed == []   # NVDA breaks out, but SPY regime is down -> no trades


def test_rs_topk_limits_to_strongest():
    # top-k = 1; NVDA (strong) and NARROW-priced strong breakout AAPL both fire,
    # but only the single strongest name vs SPY is allowed.
    AAPL = [bar(80, 80.2, 79.9, 80.05), bar(80.05, 80.2, 79.95, 80.05),
            bar(80.1, 80.25, 80.0, 80.05), bar(80.05, 80.9, 80.0, 80.6)]
    params = {**PARAMS, "rs_topk": 1}
    c = EntryMock({"SPY": SPY_UP, "NVDA": NVDA, "AAPL": AAPL})
    _run(_cfg(["SPY", "NVDA", "AAPL"], params), c)
    assert c.placed == ["NVDA"]   # NVDA had the higher relative-strength score


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
