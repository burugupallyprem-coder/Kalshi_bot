"""Premarket flag/briefing tests. Run: python tests/test_premarket.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live.premarket import compute_flags, rule_based_briefing

PM = {"halt_spy_gap_pct": 1.5, "skip_symbol_gap_pct": 4.0}
UNI = ["SPY", "AAPL", "TSLA", "NVDA"]


def test_quiet_night_no_flags():
    gaps = {"SPY": 0.2, "AAPL": -0.5, "TSLA": 1.1, "NVDA": 0.9}
    f = compute_flags(gaps, UNI, PM, "2026-07-10")
    assert not f["halt_today"] and f["skip_symbols"] == []


def test_spy_gap_halts():
    gaps = {"SPY": -1.8, "AAPL": -1.2}
    f = compute_flags(gaps, UNI, PM, "2026-07-10")
    assert f["halt_today"]


def test_symbol_gap_skipped():
    gaps = {"SPY": 0.3, "TSLA": -6.5, "NVDA": 4.2}
    f = compute_flags(gaps, UNI, PM, "2026-07-10")
    assert not f["halt_today"]
    assert f["skip_symbols"] == ["NVDA", "TSLA"]


def test_briefing_contains_movers_and_headlines():
    gaps = {"SPY": 0.3, "TSLA": -6.5}
    f = compute_flags(gaps, UNI, PM, "2026-07-10")
    text = rule_based_briefing(gaps, [{"symbols": ["TSLA"], "headline": "Tesla recalls things"}], f)
    assert "TSLA -6.5%" in text and "Tesla recalls" in text and "[PREMARKET]" in text


def test_flags_loader_date_check():
    import json
    from src.live import trader
    p = trader.ROOT / "data" / "premarket_flags.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"date": "1999-01-01", "halt_today": True, "skip_symbols": []}))
    assert trader.load_premarket_flags({}) is None  # stale date rejected
    p.write_text(json.dumps({"date": trader.now_et().strftime("%Y-%m-%d"),
                             "halt_today": False, "skip_symbols": ["TSLA"]}))
    f = trader.load_premarket_flags({})
    assert f and f["skip_symbols"] == ["TSLA"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
