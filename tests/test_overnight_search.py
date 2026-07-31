"""Offline tests for the overnight close->open search harness (synthetic daily bars)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.backtest import overnight_search as ON

CFG = {"overnight_search": {"cost_bps": 5, "regime_sma": 3,
                            "grid": {"side": ["long", "short"],
                                     "cond": ["always", "after_down", "after_up", "spy_up"]}}}


def _frame(sym, rows):
    # rows: list of (date_str, open, close); high/low/volume synthesized
    d = [pd.Timestamp(x[0]).date() for x in rows]
    o = [x[1] for x in rows]; c = [x[2] for x in rows]
    return pd.DataFrame({"symbol": sym, "date": d, "open": o, "close": c,
                         "high": [max(a, b) + 1 for a, b in zip(o, c)],
                         "low": [min(a, b) - 1 for a, b in zip(o, c)],
                         "volume": [1000] * len(rows)})


def test_expand_grid_is_side_x_cond():
    v = ON.expand_overnight(CFG)
    assert len(v) == 8, v
    assert {x["side"] for x in v} == {"long", "short"}
    assert {x["cond"] for x in v} == {"always", "after_down", "after_up", "spy_up"}


def test_long_captures_positive_overnight_drift():
    # each night the open gaps UP ~1% vs prior close -> long/always must be positive
    rows = [("2024-01-02", 100, 100), ("2024-01-03", 101, 101),
            ("2024-01-04", 102, 102), ("2024-01-05", 103, 103)]
    frames = {"AAA": _frame("AAA", rows)}
    v = {"side": "long", "cond": "always"}
    r = ON.overnight_returns(frames, v, CFG, pd.Timestamp("2024-01-01").date(),
                             pd.Timestamp("2024-12-31").date(), {})
    assert len(r) == 2, r                       # t in {1,2} (need t-? no: t=1,2 with t+1 existing)
    assert sum(r) / len(r) > 0, r               # net of cost still positive


def test_short_is_mirror_of_long_minus_double_cost():
    rows = [("2024-01-02", 100, 100), ("2024-01-03", 101, 101), ("2024-01-04", 102, 102)]
    frames = {"AAA": _frame("AAA", rows)}
    lo = ON.overnight_returns(frames, {"side": "long", "cond": "always"}, CFG,
                              pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-12-31").date(), {})
    sh = ON.overnight_returns(frames, {"side": "short", "cond": "always"}, CFG,
                              pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-12-31").date(), {})
    # long gross + short gross == 0, so long+short == -2*cost per night
    for a, b in zip(lo, sh):
        assert abs((a + b) - (-2 * 5 / 10000.0)) < 1e-9, (a, b)


def test_after_down_condition_filters_sessions():
    # only the middle session is a DOWN day (close<open); after_down keeps just that night
    rows = [("2024-01-02", 100, 101),   # up
            ("2024-01-03", 105, 100),   # DOWN (close<open)  <- t=1 qualifies
            ("2024-01-04", 100, 101),   # up
            ("2024-01-05", 101, 102)]
    frames = {"AAA": _frame("AAA", rows)}
    r = ON.overnight_returns(frames, {"side": "long", "cond": "after_down"}, CFG,
                             pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-12-31").date(), {})
    assert len(r) == 1, r


def test_cost_reduces_return():
    rows = [("2024-01-02", 100, 100), ("2024-01-03", 100, 100), ("2024-01-04", 100, 100)]
    frames = {"AAA": _frame("AAA", rows)}
    r = ON.overnight_returns(frames, {"side": "long", "cond": "always"}, CFG,
                             pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-12-31").date(), {})
    # flat prices -> every night returns exactly -cost
    assert all(abs(x - (-5 / 10000.0)) < 1e-9 for x in r), r


def test_spy_regime_up_flags_dates_above_sma():
    rows = [("2024-01-02", 10, 10), ("2024-01-03", 10, 11), ("2024-01-04", 10, 12),
            ("2024-01-05", 10, 20)]   # last close 20 >> sma of prior 3 -> up
    up = ON.spy_regime_up({"SPY": _frame("SPY", rows)}, 3)
    assert up.get(pd.Timestamp("2024-01-05").date()) is True, up



def test_cost_sensitivity_monotone_and_counts():
    rows = [("2024-01-02", 100, 100), ("2024-01-03", 101, 101),
            ("2024-01-04", 102, 102), ("2024-01-05", 103, 103)]
    frames = {"AAA": _frame("AAA", rows)}
    v = {"side": "long", "cond": "always"}
    out = ON.cost_sensitivity(frames, v, CFG, pd.Timestamp("2024-01-01").date(),
                              pd.Timestamp("2024-12-31").date(), {}, bps_levels=(0, 2, 5))
    assert [r["bps"] for r in out] == [0, 2, 5], out
    assert all(r["nights"] == 2 for r in out), out          # same nights regardless of cost
    assert out[0]["mean_bps"] > out[1]["mean_bps"] > out[2]["mean_bps"], out  # higher cost -> lower


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
