"""Stage 2 futures backtest harness tests (offline, synthetic bars)."""
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.backtest import futures_backtest as FB

ET = ZoneInfo("America/New_York")

CFG = {
    "costs": {"slippage_cents": 1},
    "risk": {"equity": 100000, "risk_pct": 0.5, "max_position_pct": 100, "flat_by_et": "15:50"},
    "gate": {"min_trades": 1, "min_expectancy_r": -1.0, "min_profit_factor": 0.0,
             "min_quarters_positive_frac": 0.0},
    "research": {"val_start": "2023-07-01", "walkforward": {"folds": 2, "min_positive_frac": 0.5}},
    "futures_stage2": {
        "primary": ["MES", "MNQ", "MYM"], "secondary": ["M2K"],
        "val_start": "2023-07-01", "commission_per_side": 0.50, "ticks_spread_per_side": 0.5,
        "locked_params": {"side": "long", "confirm_bar": 12, "rr": 3.0,
                          "stop_lookback": 12, "hold_above": 3, "time_stop_bars": 24,
                          "max_risk_frac": 0.015},
    },
}


def day(symbol, d, base, nbars=28):
    t0 = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    rows = []
    px = base
    for k in range(nbars):
        o = px; h = px * 1.002; l = px * 0.999; c = px * 1.0012
        rows.append({"symbol": symbol, "open": o, "high": h, "low": l, "close": c,
                     "volume": 10000, "et": t0 + timedelta(minutes=5 * k),
                     "date": (t0 + timedelta(minutes=5 * k)).date()})
        px = c
    return rows


def bars_for(symbol, base):
    rows = []
    for d in [date(2024, 1, x) for x in range(2, 12)] + [date(2024, 4, x) for x in range(1, 11)]:
        rows += day(symbol, d, base)
    return pd.DataFrame(rows)


def test_cfg_for_symbol_costs_differ_by_contract():
    _, mes = FB._cfg_for_symbol(CFG, "MES")
    _, mnq = FB._cfg_for_symbol(CFG, "MNQ")
    _, mym = FB._cfg_for_symbol(CFG, "MYM")
    assert mes == 22.5 and mnq == 37.5 and mym == 150.0   # per-contract, not uniform


def test_evaluate_structure_and_symbol_coverage():
    bars_by_symbol = {s: bars_for(s, b) for s, b in
                      [("MES", 5000), ("MNQ", 18000), ("MYM", 40000), ("M2K", 2000)]}
    res = FB.evaluate(bars_by_symbol, CFG)
    assert res["verdict"] in ("PASS", "FAIL")
    assert set(res["per_symbol"]) == {"MES", "MNQ", "MYM", "M2K"}   # secondary reported too
    assert isinstance(res["wf"], tuple) and len(res["wf"]) == 3
    assert "primary_positive" in res


def test_build_report_runs():
    bars_by_symbol = {s: bars_for(s, b) for s, b in [("MES", 5000), ("MNQ", 18000), ("MYM", 40000), ("M2K", 2000)]}
    res = FB.evaluate(bars_by_symbol, CFG)
    rep = FB.build_report(res, CFG, "2026-07-29 00:00 UTC")
    assert "Stage 2" in rep and "LOCKED" in rep and "Per-symbol" in rep


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
