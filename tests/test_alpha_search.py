"""Alpha-search decision-core tests (offline, synthetic trade streams)."""
import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from src.backtest import alpha_search as A
except Exception:
    import alpha_search as A


def noise(n, seed):
    r = random.Random(seed)
    return [r.gauss(0.0, 1.0) for _ in range(n)]


def edge(n, seed, mu=0.15, sd=0.4):
    r = random.Random(seed)
    return [r.gauss(mu, sd) for _ in range(n)]


def test_pure_noise_never_survives():
    # 40 random strategies; the luckiest will look positive, but DSR must reject it
    trials = [{"name": f"noise{i}", "r_multiples": noise(150, i)} for i in range(40)]
    res = A.evaluate_search(trials)
    assert res["survivor"] is False, (res["dsr"], res["best"])
    assert res["n_trials"] == 40


def test_genuine_edge_among_few_survives():
    trials = [{"name": "noiseA", "r_multiples": noise(200, 1)},
              {"name": "noiseB", "r_multiples": noise(200, 2)},
              {"name": "real_edge", "r_multiples": edge(400, 3)}]
    res = A.evaluate_search(trials)
    assert res["survivor"] is True, (res["dsr"], res["best"])
    assert res["best"]["name"] == "real_edge"


def test_min_trades_gate():
    # a strong Sharpe but too few trades is not trustworthy
    trials = [{"name": "tiny", "r_multiples": edge(12, 5)}]
    res = A.evaluate_search(trials, min_trades=30)
    assert res["survivor"] is False


def test_empty_is_safe():
    res = A.evaluate_search([])
    assert res["survivor"] is False and res["n_trials"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
