"""Strategy #10 stock diagnostic helpers. Run: python tests/test_strategy10_scalp_diag.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.engine import Trade
from src.backtest.strategy10_scalp_diag import (_level_family, _top_bottom_symbols,
                                                _trade_breakdown, bootstrap_ci)


def _mk(sym, date, r, exit_reason, signal_reason):
    return Trade(symbol=sym, strategy="s10", date=date, entry_time="", exit_time="",
                 entry=1.0, exit=1.0, shares=1, stop=1.0, target=0.0, pnl=r,
                 r_multiple=r, exit_reason=exit_reason, signal_reason=signal_reason,
                 side="long" if "long" in signal_reason else "short")


TR = [
    _mk("NVDA", "2025-01-06", 1.5, "trail_stop", "orh_break_retest_long"),
    _mk("AAPL", "2025-02-10", -1.0, "stop", "pdl_break_retest_short"),
    _mk("NVDA", "2025-05-12", 0.4, "trail_stop", "pdh_break_retest_long"),
    _mk("SPY", "2025-08-18", -1.0, "stop", "orl_break_retest_short"),
]


def test_level_family():
    assert _level_family("orh_break_retest_long") == "opening_range"
    assert _level_family("pdl_break_retest_short") == "prev_day_level"
    assert _level_family("") == "other"


def test_trade_breakdown_covers_all_cuts():
    lines, pos_q, tot_q = _trade_breakdown(TR, "## TRAIN")
    joined = "\n".join(lines)
    for cut in ["by symbol:", "by quarter:", "by exit reason:", "by level family:", "by direction:"]:
        assert cut in joined
    assert "long:" in joined and "short:" in joined      # the str.contains path
    assert tot_q == 3 and 0 <= pos_q <= 3
    assert _trade_breakdown([], "## X")[0] == ["## X: (no trades)"]


def test_bootstrap_is_seeded_and_sane():
    rs = [1.5, -1.0, 0.4, -1.0, 0.9, -1.0, 2.0, -1.0]
    a = bootstrap_ci(rs, n=500, seed=0)
    b = bootstrap_ci(rs, n=500, seed=0)
    assert a == b                        # deterministic under fixed seed
    lo, hi, frac, pt = a
    assert lo <= pt <= hi and 0.0 <= frac <= 1.0
    assert bootstrap_ci([], n=10) == (0.0, 0.0, 0.0, 0.0)


def test_top_bottom_symbols():
    s = _top_bottom_symbols(TR, k=1)
    assert "NVDA" in s and "best[" in s and "worst[" in s


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
