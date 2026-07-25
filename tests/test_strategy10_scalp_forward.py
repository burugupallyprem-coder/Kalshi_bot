"""Strategy #10 forward-trial window logic. Run: python tests/test_strategy10_scalp_forward.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.backtest.engine import Trade
from src.backtest.strategy10_scalp_forward import forward_only


def _mk(date):
    return Trade("SPY", "s10", date, "", "", 1, 1, 1, 1, 0, 0.1, 0.1, "trail_stop",
                 "orh_break_retest_long", "long")


def test_forward_only_excludes_warmup():
    lock = pd.to_datetime("2026-07-23").date()
    trades = [_mk("2026-07-10"), _mk("2026-07-22"), _mk("2026-07-23"), _mk("2026-08-01")]
    kept = forward_only(trades, lock)
    dates = {t.date for t in kept}
    assert dates == {"2026-07-23", "2026-08-01"}          # lock date inclusive, warmup dropped
    assert forward_only([], lock) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
