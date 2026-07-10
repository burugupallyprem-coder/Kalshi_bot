"""Engine correctness tests on synthetic bars. Run: python tests/test_engine.py"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.backtest.engine import simulate_day

ET = ZoneInfo("America/New_York")
CFG = {
    "costs": {"slippage_cents": 1},
    "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 20,
             "flat_by_et": "15:50"},
}


def make_day(prices):
    """prices: list of (o,h,l,c) starting 09:30 ET, 5-min steps."""
    t0 = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
    rows = []
    for k, (o, h, l, c) in enumerate(prices):
        rows.append({"symbol": "TEST", "open": o, "high": h, "low": l,
                     "close": c, "volume": 1000,
                     "et": t0 + timedelta(minutes=5 * k)})
    return pd.DataFrame(rows)


CFG_NOCAP = {"costs": {"slippage_cents": 1},
             "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 100,
                      "flat_by_et": "15:50"}}


def test_entry_next_bar_open_and_target():
    # signal at bar 1 -> entry at bar 2 OPEN (100.00) + 1c slip = 100.01
    # stop 99.01 -> risk/share 1.00 -> shares = 500 (0.5% of 100k)
    # rr=2 -> target 102.01; bar 4 high 102.50 hits target -> exit 102.01-0.01=102.00
    day = make_day([
        (99.5, 99.9, 99.4, 99.8),
        (99.8, 100.0, 99.7, 99.9),   # signal bar
        (100.0, 100.4, 99.9, 100.3),  # entry at open 100.00
        (100.3, 101.0, 100.2, 100.9),
        (100.9, 102.5, 100.8, 102.4),  # target hit
        (102.4, 102.6, 102.3, 102.5),
    ])
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 99.01, "rr": 2.0}], CFG_NOCAP, "t")
    assert len(trades) == 1
    t = trades[0]
    assert t.entry == 100.01 and t.shares == 500
    assert t.exit_reason == "target" and abs(t.exit - 102.00) < 1e-9
    assert abs(t.pnl - (102.00 - 100.01) * 500) < 0.01


def test_stop_checked_before_target_same_bar():
    # bar hits both stop and target -> stop wins (conservative)
    day = make_day([
        (100.0, 100.2, 99.9, 100.1),
        (100.1, 100.2, 100.0, 100.1),  # signal bar
        (100.0, 100.1, 99.9, 100.0),   # entry 100.00->100.01
        (100.0, 105.0, 98.0, 104.0),   # wild bar: both sides hit
    ])
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 99.0, "rr": 2.0}], CFG, "t")
    assert len(trades) == 1 and trades[0].exit_reason == "stop"
    assert trades[0].exit == 99.0 - 0.01


def test_gap_through_stop_fills_at_open():
    day = make_day([
        (100.0, 100.2, 99.9, 100.1),
        (100.1, 100.2, 100.0, 100.1),
        (100.0, 100.1, 99.9, 100.0),   # entry
        (97.0, 97.5, 96.8, 97.2),      # gaps far below stop
    ])
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 99.0, "rr": 2.0}], CFG, "t")
    assert trades[0].exit_reason == "stop"
    assert trades[0].exit == 97.0 - 0.01  # open, not stop price


def test_eod_flat():
    # 09:30 + 76 bars = 15:50 -> position force-closed at that bar's open
    prices = [(100.0, 100.3, 99.8, 100.1)] * 78
    day = make_day(prices)
    trades = simulate_day(day, [{"entry_bar": 5, "stop": 90.0, "rr": 50.0}], CFG, "t")
    assert len(trades) == 1
    assert trades[0].exit_reason == "eod_flat"
    assert trades[0].exit_time == "15:50:00"


def test_no_size_when_stop_above_entry():
    day = make_day([(100.0, 100.2, 99.9, 100.1)] * 6)
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 101.0, "rr": 2.0}], CFG, "t")
    assert trades == []


def test_position_value_cap():
    # risk/share tiny (0.01) -> uncapped shares would be 50,000 ($5M);
    # 20% cap = $20k / $100.01 -> 199 shares
    day = make_day([
        (100.0, 100.2, 99.9, 100.1),
        (100.1, 100.2, 100.0, 100.1),
        (100.0, 100.1, 99.9, 100.0),
        (100.0, 100.1, 99.9, 100.0),
    ] + [(100.0, 100.3, 99.8, 100.1)] * 74)
    trades = simulate_day(day, [{"entry_bar": 2, "stop": 100.0, "rr": 2.0}], CFG, "t")
    if trades:
        assert trades[0].shares <= 200


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
