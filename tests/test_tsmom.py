"""TSMOM engine tests on synthetic returns (offline, deterministic)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
try:
    from src.backtest import tsmom
except Exception:
    import tsmom


def _trending_prices(n_markets=5, days=1400, seg=300, drift=0.0006, noise=0.01, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-01", periods=days)
    cols = {}
    for m in range(n_markets):
        phase = m * 60   # stagger each market's trend regime
        rets = []
        for i in range(days):
            up = ((i + phase) // seg) % 2 == 0
            rets.append((drift if up else -drift) + rng.normal(0, noise))
        cols[f"MKT{m}"] = 100 * np.cumprod(1 + np.array(rets))
    return pd.DataFrame(cols, index=idx)


def test_trending_markets_give_positive_sharpe():
    prices = _trending_prices()
    net, w = tsmom.backtest(prices, lookback=252, vol_window=60, target_vol=0.10)
    m = tsmom.metrics(net)
    # a trend follower on genuinely trending, diversified markets must be clearly positive
    assert m["sharpe"] > 0.5, m
    assert m["ann_return"] > 0, m


def test_costs_reduce_net_returns():
    prices = _trending_prices()
    free, _ = tsmom.backtest(prices, cost_per_turnover=0.0)
    costly, _ = tsmom.backtest(prices, cost_per_turnover=0.02)
    assert tsmom.metrics(costly)["ann_return"] < tsmom.metrics(free)["ann_return"]


def test_no_lookahead_weight_is_lagged():
    prices = _trending_prices(n_markets=1)
    rets = prices.pct_change()
    w = tsmom.market_weights(prices["MKT0"], rets["MKT0"], 252, 60, 0.10)
    # weight at day t must be derivable without day t's return: it equals the
    # (unlagged) signal/vol shifted by one -> first valid weight is one day later
    unlagged = np.sign(prices["MKT0"] / prices["MKT0"].shift(252) - 1.0) * \
        (0.10 / (rets["MKT0"].rolling(60).std() * np.sqrt(252)))
    assert w.dropna().index[0] > unlagged.dropna().index[0]


def test_metrics_on_known_series():
    # constant + tiny noise: positive drift -> positive sharpe, shallow drawdown
    idx = pd.bdate_range("2020-01-01", periods=500)
    r = pd.Series(0.0004, index=idx) + pd.Series(np.random.default_rng(1).normal(0, 0.001, 500), index=idx)
    m = tsmom.metrics(r)
    assert m["sharpe"] > 1 and m["max_drawdown"] <= 0 and m["days"] == 500


def test_random_noise_not_strongly_positive():
    # pure noise, no trend -> a trend follower should NOT show a big edge
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2016-01-01", periods=1400)
    prices = pd.DataFrame({f"N{m}": 100 * np.cumprod(1 + rng.normal(0, 0.01, 1400))
                           for m in range(5)}, index=idx)
    net, _ = tsmom.backtest(prices, lookback=252, vol_window=60, target_vol=0.10)
    assert tsmom.metrics(net)["sharpe"] < 0.5


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
