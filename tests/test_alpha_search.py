"""Alpha-search tests: batch expansion, deflated-Sharpe survivor logic, forward gate."""
import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from src.backtest import alpha_search as A
except Exception:
    import alpha_search as A


def noise(n, seed):
    r = random.Random(seed); return [r.gauss(0.0, 1.0) for _ in range(n)]


def edge(n, seed, mu=0.15, sd=0.4):
    r = random.Random(seed); return [r.gauss(mu, sd) for _ in range(n)]


def test_expand_hypotheses_counts():
    cfg = {"alpha_search": {"search_space": {
        "orb": {"side": ["long", "short"], "rr": [1.5, 2.0, 3.0]},   # 2 x 3 = 6
        "momentum": {"rr": [2.0, 3.0], "stop_lookback": [6, 12]}}}}  # 2 x 2 = 4
    hyps = A.expand_hypotheses(cfg)
    assert len(hyps) == 10
    assert all("strategy" in h and "params" in h and "name" in h for h in hyps)


def test_pure_noise_never_survives():
    trials = [{"name": f"n{i}", "r_multiples": noise(150, i)} for i in range(40)]
    assert A.evaluate_search(trials)["survivor"] is False


def test_genuine_edge_among_few_survives():
    trials = [{"name": "nA", "r_multiples": noise(200, 1)},
              {"name": "nB", "r_multiples": noise(200, 2)},
              {"name": "real", "r_multiples": edge(400, 3)}]
    res = A.evaluate_search(trials)
    assert res["survivor"] is True and res["best"]["name"] == "real"


def test_forward_verdict_confirms_positive_fresh_data():
    good = A.forward_verdict(edge(120, 9), min_trades=20)
    assert good["confirmed"] is True and good["sharpe"] > 0
    bad = A.forward_verdict(noise(120, 9), min_trades=20)   # random fresh data
    assert bad["confirmed"] is False or bad["sharpe"] <= 0
    few = A.forward_verdict(edge(10, 9), min_trades=20)     # too few trades
    assert few["confirmed"] is False


def test_min_trades_and_empty():
    assert A.evaluate_search([{"name": "t", "r_multiples": edge(12, 5)}], min_trades=30)["survivor"] is False
    assert A.evaluate_search([])["survivor"] is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
