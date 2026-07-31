"""Tests for the new mean-reversion signal families (offline, synthetic days)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
try:
    from src.strategies import or_fade, intraday_reversal
except Exception:
    import or_fade, intraday_reversal

ET = ZoneInfo("America/New_York")


def mkday(prices):
    t0 = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
    return pd.DataFrame([{"symbol": "T", "open": o, "high": h, "low": l, "close": c,
                          "volume": 10000, "et": t0 + timedelta(minutes=5 * k)}
                         for k, (o, h, l, c) in enumerate(prices)])


def test_or_fade_short_on_up_extension():
    # OR (first 3): high 100.7, low 99.8; then a bar extends to 101.5 -> fade SHORT
    p = [(100, 100.5, 99.8, 100.2), (100.2, 100.6, 100.0, 100.4),
         (100.4, 100.7, 100.1, 100.3), (100.3, 101.6, 100.2, 101.5), (101.5, 101.6, 101.0, 101.2)]
    sig = or_fade.generate(mkday(p), {"side": "short", "open_bars": 3, "ext_frac": 0.002, "rr": 1.0})
    assert sig and sig[0]["side"] == "short" and sig[0]["stop"] > 101.5


def test_or_fade_long_on_down_extension():
    p = [(100, 100.2, 99.5, 100.0), (100.0, 100.1, 99.6, 99.9),
         (99.9, 100.0, 99.5, 99.7), (99.7, 99.8, 98.4, 98.5), (98.5, 99.0, 98.3, 98.8)]
    sig = or_fade.generate(mkday(p), {"side": "long", "open_bars": 3, "ext_frac": 0.002, "rr": 1.0})
    assert sig and sig[0]["side"] == "long" and sig[0]["stop"] < 98.5


def test_intraday_reversal_shorts_a_strong_up_morning():
    # up ~1% from open by the decide bar -> fade SHORT
    p = [(100 + i * 0.15, 100 + i * 0.15 + 0.1, 100 + i * 0.15 - 0.1, 100 + i * 0.15 + 0.05)
         for i in range(10)]
    sig = intraday_reversal.generate(mkday(p), {"side": "short", "decide_bar": 6,
                                                "move_frac": 0.005, "rr": 1.0})
    assert sig and sig[0]["side"] == "short" and sig[0]["entry_bar"] == 7


def test_no_signal_when_flat():
    p = [(100, 100.1, 99.9, 100.0)] * 10
    assert or_fade.generate(mkday(p), {"side": "short", "open_bars": 3, "ext_frac": 0.003}) == []
    assert intraday_reversal.generate(mkday(p), {"side": "short", "decide_bar": 6, "move_frac": 0.005}) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
