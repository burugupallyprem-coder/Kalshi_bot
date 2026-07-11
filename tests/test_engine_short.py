"""Short-side engine tests. Run: python tests/test_engine_short.py"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.backtest.engine import simulate_day
from src.strategies import orb, vwap_revert, momentum

ET = ZoneInfo("America/New_York")
CFG = {"costs": {"slippage_cents": 1},
       "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 100,
                "flat_by_et": "15:50"}}


def make_day(prices):
    t0 = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
    return pd.DataFrame([
        {"symbol": "TEST", "open": o, "high": h, "low": l, "close": c,
         "volume": 10000, "et": t0 + timedelta(minutes=5 * k)}
        for k, (o, h, l, c) in enumerate(prices)])


def test_short_entry_and_target():
    # short signal at bar 2: entry at open 100.00 MINUS 1c slip = 99.99
    # stop 101.01 above -> risk 1.02/share; rr 2 -> target 99.99 - 2.04 = 97.95
    day = make_day([
        (100.5, 100.6, 100.2, 100.3),
        (100.3, 100.4, 100.0, 100.1),
        (100.0, 100.2, 99.8, 99.9),    # entry bar (open 100.0)
        (99.9, 100.0, 99.0, 99.1),
        (99.1, 99.2, 97.5, 97.7),      # low 97.5 <= target -> cover
    ])
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 101.01, "rr": 2.0,
                                 "side": "short"}], CFG, "t")
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "short"
    assert abs(t.entry - 99.99) < 1e-9          # slip AGAINST short entry
    assert t.exit_reason == "target"
    assert t.pnl > 0                            # price fell, short profits
    assert t.r_multiple > 1.9


def test_short_stop_above():
    day = make_day([
        (100.5, 100.6, 100.2, 100.3),
        (100.3, 100.4, 100.0, 100.1),
        (100.0, 100.2, 99.8, 99.9),     # entry at 100.0 - slip
        (100.0, 102.0, 99.9, 101.8),    # high 102 >= stop 101 -> stopped
    ])
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 101.0, "rr": 2.0,
                                 "side": "short"}], CFG, "t")
    assert trades[0].exit_reason == "stop"
    assert trades[0].pnl < 0
    assert abs(trades[0].exit - (101.0 + 0.01)) < 1e-9   # cover at stop PLUS slip


def test_short_gap_through_stop_fills_at_open():
    day = make_day([
        (100.5, 100.6, 100.2, 100.3),
        (100.3, 100.4, 100.0, 100.1),
        (100.0, 100.2, 99.8, 99.9),
        (103.0, 103.5, 102.8, 103.2),   # gaps ABOVE stop -> cover at open (worse)
    ])
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 101.0, "rr": 2.0,
                                 "side": "short"}], CFG, "t")
    assert trades[0].exit_reason == "stop"
    assert abs(trades[0].exit - (103.0 + 0.01)) < 1e-9


def test_invalid_short_stop_below_entry_rejected():
    day = make_day([(100.0, 100.2, 99.8, 100.1)] * 5)
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 99.0, "rr": 2.0,
                                 "side": "short"}], CFG, "t")
    assert trades == []   # stop on the profit side makes no sense - rejected


def _upday():
    # steady uptrend day, 40 bars
    prices = []
    p = 100.0
    for k in range(40):
        o = p; c = p + 0.15; h = c + 0.05; l = o - 0.05
        prices.append((o, h, l, c)); p = c
    return make_day(prices)


def _downday():
    prices = []
    p = 100.0
    for k in range(40):
        o = p; c = p - 0.15; h = o + 0.05; l = c - 0.05
        prices.append((o, h, l, c)); p = c
    return make_day(prices)


def test_orb_short_fires_on_downside_break():
    sigs = orb.generate(_downday(), {"side": "short", "open_bars": 3, "rr": 1.5,
                                     "max_risk_frac": 0.05})
    assert sigs and sigs[0]["side"] == "short"
    assert sigs[0]["stop"] > 100.0 - 3 * 0.15   # stop at range high side


def test_momentum_short_needs_downtrend():
    assert momentum.generate(_upday(), {"side": "short", "confirm_bar": 12}) == []
    # vwap short fade needs an above-vwap stretch - a straight downtrend gives none
    assert vwap_revert.generate(_downday(), {"side": "short", "z_entry": 9.9}) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
