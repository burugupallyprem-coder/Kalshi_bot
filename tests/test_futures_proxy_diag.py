"""Tests for the futures-proxy diagnostic stats helpers (offline, deterministic)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.backtest import futures_proxy_diag as D


def test_bootstrap_ci_positive_edge_clears_zero():
    point, lo, hi, pgt0 = D.bootstrap_ci([0.2, 0.3, 0.25, 0.28, 0.22, 0.26] * 20)
    assert lo > 0 and pgt0 > 99 and point > 0


def test_bootstrap_ci_noisy_includes_zero():
    # symmetric-ish around zero -> CI must include zero (not distinguishable from luck)
    point, lo, hi, pgt0 = D.bootstrap_ci([1.0, -1.0, 0.9, -0.95, 1.1, -1.05] * 20)
    assert lo < 0 < hi


def test_bootstrap_ci_empty_safe():
    assert D.bootstrap_ci([]) == (0.0, 0.0, 0.0, 0.0)


def test_breakdown_format():
    df = pd.DataFrame({"symbol": ["SPY", "SPY", "QQQ"],
                       "r_multiple": [0.5, -0.3, 0.2],
                       "pnl": [50, -30, 20]})
    out = D._breakdown(df, "symbol")
    assert any("SPY: 2 trades" in line for line in out)
    assert any("QQQ: 1 trades" in line for line in out)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
