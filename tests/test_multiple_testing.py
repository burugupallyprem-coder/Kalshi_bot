"""Tests for the multiple-testing core (offline, deterministic)."""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from src.backtest import multiple_testing as MT
except Exception:
    import multiple_testing as MT


def test_normal_functions():
    assert abs(MT.norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(MT.norm_cdf(1.959964) - 0.975) < 1e-4
    assert abs(MT.norm_ppf(0.975) - 1.959964) < 1e-3
    assert abs(MT.norm_ppf(0.5)) < 1e-6


def test_psr_monotonic():
    # higher Sharpe and more observations -> more confidence
    assert MT.probabilistic_sharpe_ratio(0.1, 500) > MT.probabilistic_sharpe_ratio(0.05, 500)
    assert MT.probabilistic_sharpe_ratio(0.1, 1000) > MT.probabilistic_sharpe_ratio(0.1, 100)
    # a Sharpe exactly at the benchmark -> 50/50
    assert abs(MT.probabilistic_sharpe_ratio(0.1, 500, sr_benchmark=0.1) - 0.5) < 1e-9


def test_expected_max_grows_with_trials_and_variance():
    assert MT.expected_max_sharpe(1000, 0.01) > MT.expected_max_sharpe(10, 0.01)
    assert MT.expected_max_sharpe(100, 0.04) > MT.expected_max_sharpe(100, 0.01)
    assert MT.expected_max_sharpe(1, 0.01) == 0.0   # a single trial cannot be "lucky max"


def test_deflation_kills_a_lucky_best_of_many():
    # A per-trade Sharpe of 0.12 over 300 trades looks significant on its own...
    single, _ = MT.deflated_sharpe_ratio(0.12, 300, [0.12])
    # ...but as the BEST of 500 widely-varying trials, it should be heavily deflated.
    import random; random.seed(0)
    trials = [random.gauss(0, 0.08) for _ in range(499)] + [0.12]
    many, sr0 = MT.deflated_sharpe_ratio(0.12, 300, trials)
    assert single > 0.9                      # convincing as one test
    assert many < single                     # deflation reduces confidence
    assert sr0 > 0                            # a real luck-benchmark exists
    assert many < 0.95                        # would NOT clear a 0.95 survivor bar


def test_per_trade_sharpe():
    sr, n, sk, ku = MT.per_trade_sharpe([0.1, -0.05, 0.2, -0.1, 0.15] * 40)
    assert n == 200 and sr > 0
    zero = MT.per_trade_sharpe([0.05] * 50)   # zero variance -> sharpe 0, no crash
    assert zero[0] == 0.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
