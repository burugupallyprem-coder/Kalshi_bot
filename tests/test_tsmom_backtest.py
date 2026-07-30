"""TSMOM orchestration/gate tests (offline, synthetic prices)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
try:
    from src.backtest import tsmom_backtest as TB
except Exception:
    import tsmom_backtest as TB


def trending_prices(n_markets=6, days=1800, seg=300, drift=0.0006, noise=0.01, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=days)
    cols = {}
    for m in range(n_markets):
        phase = m * 55
        rets = [((drift if ((i + phase)//seg) % 2 == 0 else -drift) + rng.normal(0, noise))
                for i in range(days)]
        cols[f"M{m}"] = 100 * np.cumprod(1 + np.array(rets))
    return pd.DataFrame(cols, index=idx)


CFG = {"tsmom": {
    "universe": [f"M{i}" for i in range(6)],
    "lookbacks": [63, 126, 252], "vol_window": 60, "target_vol": 0.10,
    "cost_per_turnover": 0.0005, "cost_sensitivity": [0.001, 0.003],
    "oos_start": "2019-01-01",
    "gate": {"min_sharpe": 0.5, "min_wf_frac": 0.6, "wf_folds": 4, "max_drawdown": 0.5},
}}


def test_evaluate_structure():
    res = TB.evaluate(trending_prices(), CFG)
    assert res["verdict"] in ("PASS", "FAIL")
    assert res["best_lookback"] in (63, 126, 252)
    for k in ("sharpe", "ann_return", "max_drawdown"):
        assert k in res["oos"]
    assert isinstance(res["wf"], tuple) and len(res["wf"]) == 3


def test_trending_data_passes_gate():
    res = TB.evaluate(trending_prices(), CFG)
    assert res["verdict"] == "PASS", (res["verdict"], res["why"], res["oos"])
    assert res["oos"]["sharpe"] >= 0.5


def test_noise_fails_gate_on_average():
    # A single noise draw can pass by luck (best-of-3 lookback + finite window) - that
    # is the whole reason we distrust one backtest. So check the AVERAGE over draws:
    # pure noise must not clear the gate typically.
    sharpes = []
    for seed in range(10):
        rng = np.random.default_rng(seed + 100)
        idx = pd.bdate_range("2015-01-01", periods=1800)
        prices = pd.DataFrame({f"M{m}": 100*np.cumprod(1+rng.normal(0, 0.01, 1800))
                               for m in range(6)}, index=idx)
        sharpes.append(TB.evaluate(prices, CFG)["oos"]["sharpe"])
    assert np.median(sharpes) < 0.5, sharpes           # noise ~ no durable edge
    assert np.mean([s >= 0.5 for s in sharpes]) < 0.5, sharpes


def test_report_builds():
    res = TB.evaluate(trending_prices(), CFG)
    rep = TB.build_report(res, CFG, "2026-07-29 00:00 UTC")
    assert "TSMOM" in rep and "OOS verdict" in rep and "by year" in rep


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
