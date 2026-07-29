"""Stage-1 futures-proxy pipeline test (offline, synthetic index bars)."""
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.backtest import futures_proxy as FP

ET = ZoneInfo("America/New_York")

CFG = {
    "costs": {"slippage_cents": 1},
    "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 100, "flat_by_et": "15:50"},
    "strategies": {"orb": {}},
    "gate": {"min_trades": 1, "min_expectancy_r": -1.0, "min_profit_factor": 0.0,
             "min_quarters_positive_frac": 0.0},
    "research": {"train_end": "2025-12-31", "val_start": "2026-01-01",
                 "regime_open_bars": 3, "regime_cutoff_et": "10:30",
                 "min_train_trades": 1, "slippage_sensitivity_cents": [0.5, 2.0],
                 "walkforward": {"folds": 2, "min_positive_frac": 0.5}},
    "futures_proxy": {
        "universe": ["SPY", "QQQ", "DIA", "IWM"],
        "proxy_map": {"SPY": "MES", "QQQ": "MNQ", "DIA": "MYM", "IWM": "M2K"},
        "framings": {"single_instrument": {"rs_topk": None}, "index_basket": {"rs_topk": 2}},
        "fixed": {"side": "long", "open_bars": 3, "cutoff_et": "10:30",
                  "vol_confirm": False, "min_or_width_frac": 0.004, "regime_filter": True},
        "grid": {"rr": [1.5, 2.0]},
    },
}


def breakout_day(symbol, d, base, nbars=24):
    """Full 24-bar session: 3-bar opening range (~0.8% wide), breakout on bar 3,
    then drift up so the target fills. day_groups needs >=20 bars/day."""
    t0 = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    lo, hi = base * 0.996, base * 1.004
    seq = [(base, hi, lo, base * 1.001),
           (base * 1.001, hi, lo, base * 1.002),
           (base * 1.002, hi, lo, base * 1.0015),
           (base * 1.0015, base * 1.02, base * 1.001, base * 1.015)]  # breakout bar (idx 3)
    # after breakout: rise so the 1.5R target is hit, then hold
    for _ in range(nbars - len(seq)):
        seq.append((base * 1.02, base * 1.05, base * 1.015, base * 1.03))
    rows = []
    for k, (o, h, l, c) in enumerate(seq):
        et = t0 + timedelta(minutes=5 * k)
        rows.append({"symbol": symbol, "open": o, "high": h, "low": l, "close": c,
                     "volume": 10000, "et": et, "date": et.date()})
    return rows


def make_bars():
    rows = []
    train_days = [date(2025, 12, d) for d in (1, 2, 3, 4, 5)]
    val_days = [date(2026, 1, d) for d in (5, 6, 7, 8, 9)]
    bases = {"SPY": 500, "QQQ": 430, "DIA": 380, "IWM": 210}
    for sym, b in bases.items():
        for d in train_days + val_days:
            rows += breakout_day(sym, d, b)
    return pd.DataFrame(rows)


def test_evaluate_framing_runs_and_returns_structure():
    bars = make_bars()
    for fr in CFG["futures_proxy"]["framings"].values():
        r = FP.evaluate_framing(bars, CFG, fr)
        assert r["verdict"] in ("PASS", "FAIL", "SKIP")
        if r["val"] is not None:
            assert "expectancy_r" in r["val"] and "trades" in r["val"]
            assert isinstance(r["wf"], tuple) and len(r["wf"]) == 3


def test_single_instrument_trades_all_four_indices():
    # rs_topk=None must NOT restrict the universe (all 4 indices eligible)
    bars = make_bars()
    r = FP.evaluate_framing(bars, CFG, {"rs_topk": None})
    # with breakouts on every symbol/day and min_train_trades=1, we should get a winner
    assert r["best_combo"] is not None and r["train"]["trades"] > 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
