"""Walk-forward + market-context/filter wiring tests (offline, synthetic)."""
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.backtest import research

ET = ZoneInfo("America/New_York")
CFG = {"costs": {"slippage_cents": 1},
       "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 100, "flat_by_et": "15:50"},
       "research": {"regime_open_bars": 3, "regime_cutoff_et": "10:30"}}


def day_df(symbol, d, prices):
    t0 = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    rows = []
    for k, (o, h, l, c) in enumerate(prices):
        et = t0 + timedelta(minutes=5 * k)
        rows.append({"symbol": symbol, "open": o, "high": h, "low": l, "close": c,
                     "volume": 10000, "et": et, "date": et.date()})
    return pd.DataFrame(rows)


def test_walk_forward_folds_split():
    dates = [date(2026, 1, d) for d in range(1, 13)]  # 12 unique dates
    folds = research.walk_forward_folds(dates, 4)
    assert len(folds) == 4
    assert folds[0][0] == date(2026, 1, 1)
    assert folds[-1][1] == date(2026, 1, 12)  # last fold covers the tail


def test_build_context_regime_and_rs():
    d = date(2026, 7, 6)
    spy_up = [(100, 100.5, 99.8, 100.2), (100.2, 100.6, 100.0, 100.4),
              (100.4, 100.7, 100.1, 100.3), (100.3, 101.2, 100.2, 101.0)]  # breaks up
    strong = [(50, 51, 49.9, 50.0), (50, 51, 50, 50.5), (50.5, 51, 50.4, 51.0), (51, 52, 51, 51.8)]
    weak = [(50, 50.1, 49, 49.5), (49.5, 49.6, 49, 49.2), (49.2, 49.3, 48.5, 48.8), (48.8, 49, 48, 48.2)]
    groups = [("SPY", day_df("SPY", d, spy_up)),
              ("NVDA", day_df("NVDA", d, strong)),
              ("XOM", day_df("XOM", d, weak))]
    ctx = research.build_context(groups, CFG)
    assert ctx["spy_long_ok"][d] is True
    # NVDA rose vs SPY, XOM fell vs SPY
    assert ctx["rs"][d]["NVDA"] > ctx["rs"][d]["XOM"]


def test_run_config_rs_topk_limits_symbols():
    d = date(2026, 7, 6)
    flat = [(50, 50.1, 49.9, 50.0)] * 4
    groups = [("SPY", day_df("SPY", d, flat)),
              ("NVDA", day_df("NVDA", d, flat)),
              ("XOM", day_df("XOM", d, flat))]
    ctx = research.build_context(groups, CFG)
    ctx["rs"][d] = {"SPY": 0.0, "NVDA": 0.05, "XOM": -0.05}  # NVDA strongest

    seen = []

    class FakeStrat:
        @staticmethod
        def generate(day, params, ctx=None):
            seen.append(day["symbol"].iloc[0])
            return []

    research.run_config(groups, FakeStrat, {"rs_topk": 1}, CFG, "fake", ctx)
    assert seen == ["NVDA"]  # only the single strongest name was evaluated


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
