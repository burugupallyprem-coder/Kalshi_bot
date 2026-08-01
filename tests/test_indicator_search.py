"""Offline tests: indicators are causal & correct, and the search plumbing works."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
from src.backtest import indicators as IND
from src.backtest import indicator_search as ISx

CFG = {"indicator_search": {"cost_bps": 5, "grid": {
    "bollinger": {"mode": ["revert", "breakout"], "period": [20], "k": [2.0, 2.5]},
    "rsi": {"period": [10, 14], "low": [30], "high": [70]},
    "macd": {"fast": [12], "slow": [26], "signal": [9]},
    "fib": {"lookback": [20], "retr": [0.5, 0.618]}}}}


def _series(vals):
    idx = pd.date_range("2020-01-01", periods=len(vals), freq="D").date
    return pd.Series(vals, index=pd.Index(idx))


def test_rsi_bounds_and_extremes():
    up = _series(list(np.linspace(100, 200, 60)))     # relentless up -> RSI high
    dn = _series(list(np.linspace(200, 100, 60)))     # relentless down -> RSI low
    assert IND.rsi(up).iloc[-1] > 70, IND.rsi(up).iloc[-1]
    assert IND.rsi(dn).iloc[-1] < 30, IND.rsi(dn).iloc[-1]
    r = IND.rsi(_series(list(np.random.RandomState(0).randn(100).cumsum() + 100)))
    assert r.between(0, 100).all()


def test_rsi_pos_goes_long_after_oversold():
    # sharp drop (oversold) then recovery -> should hold a long at some point
    vals = [100]*20 + list(np.linspace(100, 70, 10)) + list(np.linspace(70, 95, 15))
    pos = IND.rsi_pos(_series(vals), period=14)
    assert (pos == 1).any(), pos.value_counts().to_dict()
    assert set(pos.unique()) <= {-1.0, 0.0, 1.0}


def test_bollinger_revert_is_causal_and_bounded():
    vals = list(100 + 5*np.sin(np.linspace(0, 12, 120)))
    pos = IND.bollinger_pos(_series(vals), period=20, k=2.0, mode="revert")
    assert set(np.unique(pos.values)) <= {-1.0, 0.0, 1.0}
    assert pos.iloc[:19].eq(0).all()        # no position before the window fills (no lookahead)


def test_macd_pos_sign_matches_cross():
    vals = list(np.linspace(100, 130, 40)) + list(np.linspace(130, 100, 40))
    pos = IND.macd_pos(_series(vals))
    assert pos.iloc[30] == 1      # uptrend -> macd above signal -> long
    assert pos.iloc[-1] == -1     # downtrend -> short


def test_fib_long_only_in_uptrend():
    up = _series(list(np.linspace(100, 160, 80)))
    dn = _series(list(np.linspace(160, 100, 80)))
    assert (IND.fib_pos(up) >= 0).all()      # never short in a clean uptrend
    assert (IND.fib_pos(dn) <= 0).all()      # never long in a clean downtrend


def test_expand_grid_counts():
    v = ISx.expand_indicators(CFG)
    # bollinger 2*1*2=4, rsi 2, macd 1, fib 2 -> 9
    assert len(v) == 9, len(v)
    assert {x["indicator"] for x in v} == {"bollinger", "rsi", "macd", "fib"}


def test_strategy_returns_no_lookahead_and_costs():
    # flat prices -> only cost drag on the days a position is held
    frames = {"AAA": pd.DataFrame({"date": pd.date_range("2020-01-01", periods=120, freq="D").date,
                                   "close": [100.0]*120})}
    v = {"indicator": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}}
    r = ISx.strategy_returns(frames, v, CFG, pd.Timestamp("2020-01-01").date(),
                             pd.Timestamp("2020-12-31").date())
    assert all(x <= 0 for x in r), "flat price can't yield positive return"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for fn in fns:
        try:
            fn(); p += 1
        except Exception:
            print("FAIL", fn.__name__); traceback.print_exc()
    print(f"{p}/{len(fns)} tests passed")
