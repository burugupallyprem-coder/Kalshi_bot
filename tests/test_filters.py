"""Tests for opt-in research filters (offline, synthetic bars)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.strategies import filters

ET = ZoneInfo("America/New_York")


def make_day(prices):
    t0 = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
    return pd.DataFrame([
        {"symbol": "T", "open": o, "high": h, "low": l, "close": c,
         "volume": 10000, "et": t0 + timedelta(minutes=5 * k)}
        for k, (o, h, l, c) in enumerate(prices)])


def test_vol_floor_blocks_narrow_range():
    # 3-bar OR high 100.2 low 100.0 -> width ~0.2% ; floor 0.5% blocks it
    day = make_day([(100, 100.2, 100.0, 100.1)] * 3 + [(100.1, 100.3, 100.0, 100.25)])
    assert filters.or_width_frac(day, 3) < 0.005
    assert not filters.passes_vol_floor(day, 3, 0.005)
    assert filters.passes_vol_floor(day, 3, 0.0)  # disabled -> always pass


def test_vol_floor_allows_wide_range():
    day = make_day([(100, 101.0, 99.0, 100.5)] * 3 + [(100.5, 102, 100.4, 101.5)])
    assert filters.passes_vol_floor(day, 3, 0.005)


def test_spy_regime_true_when_spy_breaks_up_before_cutoff():
    # OR high ~100.7; a later bar (still before 10:30) closes 101.0 -> breaks up
    spy = make_day([(100, 100.5, 99.8, 100.2), (100.2, 100.6, 100.0, 100.4),
                    (100.4, 100.7, 100.1, 100.3), (100.3, 101.2, 100.2, 101.0)])
    assert filters.spy_long_ok(spy, 3, "10:30")


def test_spy_regime_false_when_spy_stays_in_range():
    spy = make_day([(100, 100.5, 99.8, 100.2), (100.2, 100.6, 100.0, 100.4),
                    (100.4, 100.7, 100.1, 100.3), (100.3, 100.65, 100.2, 100.5)])
    assert not filters.spy_long_ok(spy, 3, "10:30")


def test_top_k_selection():
    scores = {"NVDA": 0.03, "AAPL": 0.01, "SPY": 0.0, "XOM": -0.02}
    assert filters.top_k_symbols(scores, 2) == {"NVDA", "AAPL"}
    assert filters.top_k_symbols(scores, None) == set(scores)  # disabled -> all


def test_early_return_sign():
    up = make_day([(100, 101, 99.9, 100.0), (100, 101, 100, 100.5), (100.5, 101, 100.4, 101.0)])
    assert filters.early_return(up, 3) > 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
