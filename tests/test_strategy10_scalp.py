"""Strategy #10 stock scalp correctness. Run: python tests/test_strategy10_scalp.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.backtest.strategy10_scalp import (daily_ema_dir, _size, opening_ranges,
                                           prev_day_levels, simulate_symbol)

CFG = {
    "strategy10": {"open_bars": 5, "ema_fast": 9, "ema_slow": 21,
                   "zone_frac": 0.05, "stop_buf_frac": 0.10, "min_stop_cost_mult": 2.0},
    "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 20, "flat_by_et": "15:50"},
    "costs": {"slippage_cents": 1},
}
OFF = {"trail_lookback": 3, "trend_filter": False, "max_trades_day": 2}


def _bar(et, o, h, l, c):
    return {"symbol": "TEST", "et": et, "date": et.date(),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000}


def _df(rows):
    return pd.DataFrame(rows)


def _prev_day():
    # PDH=105 / PDL=95 (range 10, zone 0.5, buf 1.0), far from day-2 price ~100
    d1 = pd.Timestamp("2026-03-02 09:30", tz="America/New_York")
    return [_bar(d1, 100, 105, 95, 100), _bar(d1 + pd.Timedelta(minutes=1), 100, 104, 96, 100)]


def _day2(extra):
    d2 = pd.Timestamp("2026-03-03 09:30", tz="America/New_York")
    base = [
        (0, 100.0, 100.2, 99.8, 100.0), (1, 100.0, 100.1, 99.9, 100.0),
        (2, 100.0, 100.1, 99.9, 100.0), (3, 100.0, 100.1, 99.9, 100.0),
        (4, 100.0, 100.1, 99.9, 100.0),               # OR high 100.2 / low 99.8 -> band 100.7
        (5, 100.3, 101.0, 100.3, 100.9),              # breakout
        (6, 100.8, 100.9, 100.5, 100.7),              # retest into band
        (7, 100.7, 101.2, 100.7, 101.1),              # trigger
        (8, 101.2, 101.3, 101.0, 101.1),              # fill
    ] + extra
    return [_bar(d2 + pd.Timedelta(minutes=m), o, h, l, c) for (m, o, h, l, c) in base]


def test_levels_and_or():
    df = _df(_prev_day() + _day2([]))
    pd_lv = prev_day_levels(df)
    key = pd.Timestamp("2026-03-03").date()
    assert abs(pd_lv[key][0] - 105) < 1e-9 and abs(pd_lv[key][1] - 95) < 1e-9
    orl = opening_ranges(df, 5)
    assert abs(orl[key][0] - 100.2) < 1e-9 and abs(orl[key][1] - 99.8) < 1e-9


def test_or_long_break_retest_then_stop():
    rows = _prev_day() + _day2([(9, 101.1, 101.2, 98.0, 98.5)])   # slam the initial stop
    trades = simulate_symbol(_df(rows), "TEST", OFF, CFG)
    assert len(trades) == 1
    t = trades[0]
    assert t.signal_reason == "orh_break_retest_long"
    assert t.side == "long"
    assert t.exit_reason == "stop"
    assert abs(t.stop - 99.2) < 1e-6      # OR_high(100.2) - buf(1.0)
    assert t.r_multiple < 0 and t.pnl < 0


def test_trend_filter_blocks_when_flat():
    rows = _prev_day() + _day2([(9, 101.1, 101.2, 98.0, 98.5)])
    on = {"trail_lookback": 3, "trend_filter": True, "max_trades_day": 2}
    assert len(simulate_symbol(_df(rows), "TEST", OFF, CFG)) == 1
    assert simulate_symbol(_df(rows), "TEST", on, CFG) == []


def test_ema_dir_up_down():
    up = [_bar(pd.Timestamp("2026-01-01 09:30", tz="America/New_York") + pd.Timedelta(days=k),
               100 + k, 100 + k, 100 + k, 100 + k) for k in range(30)]
    dn = [_bar(pd.Timestamp("2026-01-01 09:30", tz="America/New_York") + pd.Timedelta(days=k),
               200 - k, 200 - k, 200 - k, 200 - k) for k in range(30)]
    du = daily_ema_dir(_df(up), 9, 21)
    dd = daily_ema_dir(_df(dn), 9, 21)
    last_u = pd.Timestamp("2026-01-30").date()
    assert du[last_u] == 1 and dd[last_u] == -1


def test_size_notional_cap():
    # 20% of $100k / $100 entry = 200 shares cap; risk-based would be far more
    assert _size(100.0, 99.99, CFG) == 200


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
