import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from src.strategies import gap


def _day(opens):
    n = len(opens)
    return pd.DataFrame({
        "open": opens, "high": [o + 0.5 for o in opens], "low": [o - 0.5 for o in opens],
        "close": opens, "volume": [1000] * n,
        "date": [pd.Timestamp("2025-01-02").date()] * n})


def test_fade_shorts_a_gap_up():
    d = _day([102.0, 102.1, 101.5, 101.0])
    sig = gap.generate(d, {"mode": "fade", "min_gap": 0.005, "rr": 1.5, "stop_frac": 0.004},
                       ctx={"prev_close": 100.0})
    assert sig and sig[0]["side"] == "short", sig


def test_fade_longs_a_gap_down():
    d = _day([98.0, 97.9, 98.4, 99.0])
    sig = gap.generate(d, {"mode": "fade", "min_gap": 0.005}, ctx={"prev_close": 100.0})
    assert sig and sig[0]["side"] == "long", sig


def test_go_longs_a_gap_up():
    d = _day([102.0, 102.1, 102.6, 103.0])
    sig = gap.generate(d, {"mode": "go", "min_gap": 0.005}, ctx={"prev_close": 100.0})
    assert sig and sig[0]["side"] == "long", sig


def test_no_signal_when_gap_too_small():
    d = _day([100.1, 100.2, 100.0, 99.9])
    sig = gap.generate(d, {"mode": "fade", "min_gap": 0.005}, ctx={"prev_close": 100.0})
    assert sig == [], sig


def test_no_signal_without_prev_close():
    d = _day([102.0, 102.1, 101.5, 101.0])
    assert gap.generate(d, {"mode": "fade"}, ctx={}) == []
    assert gap.generate(d, {"mode": "fade"}, ctx=None) == []


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for fn in fns:
        try:
            fn(); p += 1
        except Exception:
            print("FAIL", fn.__name__); traceback.print_exc()
    print(f"{p}/{len(fns)} tests passed")
