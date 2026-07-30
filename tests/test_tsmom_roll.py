"""Roll-rule + artifact-scan tests (offline, synthetic contract data)."""
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
try:
    from src.backtest import futures_daily as FD, tsmom_diag as TD
except Exception:
    import futures_daily as FD, tsmom_diag as TD


def raw_two_contracts():
    """Contract A active days 1-7, a 1-day volume spike to B on day 6 (jitter),
    then B genuinely takes over days 8-14. B priced ~10% above A (a roll gap)."""
    d0 = date(2020, 1, 1)
    rows = []
    for i in range(14):
        d = d0 + timedelta(days=i)
        # A: price ~100 drifting; volume high early, low late
        rows.append({"date": d, "close": 100 + i*0.1, "instrument_id": "A",
                     "volume": (1000 if i < 8 else 50)})
        # B: price ~110; volume low early, one spike on day 6 (i==5), high late
        vol_b = 50
        if i == 5: vol_b = 5000      # single-day jitter spike
        if i >= 7: vol_b = 2000      # genuine takeover
        rows.append({"date": d, "close": 110 + i*0.1, "instrument_id": "B", "volume": vol_b})
    return pd.DataFrame(rows)


def test_naive_jitters_smooth_does_not():
    dfm = raw_two_contracts()
    naive = FD.active_series(dfm, "naive").set_index("date")["instrument_id"]
    smooth = FD.active_series(dfm, "smooth", min_roll_days=3).set_index("date")["instrument_id"]
    d6 = date(2020, 1, 6)
    assert naive.loc[d6] == "B"      # naive flips on the 1-day volume spike
    assert smooth.loc[d6] == "A"     # smooth ignores the un-sustained spike
    assert smooth.iloc[-1] == "B"    # but does roll once B sustains


def test_roll_gap_not_counted_as_return():
    dfm = raw_two_contracts()
    prices = FD._roll_adjusted_prices(FD.active_series(dfm, "smooth", 3))
    daily = prices.pct_change().abs().max()
    # the ~10% A->B price gap must NOT appear as a ~10% one-day return
    assert daily < 0.02, daily


def test_artifact_scan_flags_big_move():
    idx = pd.bdate_range("2020-01-01", periods=100)
    p = pd.Series(100.0, index=idx); p.iloc[50] = 130.0   # a fake 30% jump (bad roll)
    panel = pd.DataFrame({"BAD": p, "OK": pd.Series(np.linspace(100, 105, 100), index=idx)})
    scan = TD.artifact_scan(panel)
    assert scan["BAD"]["max_abs_day"] > 0.2 and scan["OK"]["max_abs_day"] < 0.05


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
