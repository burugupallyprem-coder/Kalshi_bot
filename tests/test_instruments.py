"""Futures instrument metadata + cost-model tests. Offline, deterministic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import instruments as I


def test_tick_value_consistency():
    for sym, c in I.REGISTRY.items():
        assert abs(I.tick_value(sym) - c.multiplier * c.tick_size) < 1e-9, sym
    assert abs(I.tick_value("ES") - 12.50) < 1e-9
    assert abs(I.tick_value("MES") - 1.25) < 1e-9


def test_round_to_tick():
    assert I.round_to_tick(4512.30, "ES") == 4512.25
    assert I.round_to_tick(4512.40, "ES") == 4512.50
    assert I.round_to_tick(1987.34, "MGC") == 1987.30


def test_contracts_for_risk_floors():
    assert I.contracts_for_risk(5000, 4990, "MES", 50000, 0.5) == 5      # $50/contract, $250 budget
    assert I.contracts_for_risk(2000, 1996, "GC", 50000, 0.5) == 0       # $400/contract > budget
    assert I.contracts_for_risk(5000, 5000, "MES", 50000, 0.5) == 0      # zero stop distance


def test_dow_contracts_present():
    assert I.get_contract("MYM").multiplier == 0.5
    assert I.get_contract("YM").multiplier == 5.0


def test_effective_slippage_cents_units():
    # MES: half-tick 0.125pt + $0.50/5=0.10pt = 0.225pt/side -> *100 = 22.5
    assert abs(I.effective_slippage_cents("MES") - 22.5) < 1e-6
    # cheaper commission -> lower cost; wider spread -> higher cost
    assert I.effective_slippage_cents("MES", commission_per_side=0.25) < 22.5
    assert I.effective_slippage_cents("MES", ticks_spread_per_side=1.0) > 22.5


def test_unknown_symbol_raises():
    try:
        I.get_contract("AAPL"); raise AssertionError("should raise")
    except KeyError as e:
        assert "unknown futures symbol" in str(e)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
