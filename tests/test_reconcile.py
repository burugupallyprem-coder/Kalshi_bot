"""Reconcile ledger rebuild tests (mock Alpaca portfolio history). Offline."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live import reconcile


class MockClient:
    def portfolio_history(self, period="3M", timeframe="1D"):
        # 2025-07-13 and 2025-07-14 (unix midnight UTC), one gap-free rebuild
        return {"timestamp": [1752364800, 1752451200],
                "equity": [100095.0, 100050.0],
                "profit_loss": [-55.0, -45.0]}


def test_rebuild_maps_history_to_rows():
    rows = reconcile.rebuild(client=MockClient())
    assert len(rows) == 2
    assert rows[0][0] == "2025-07-13" and abs(rows[0][1] - 100095.0) < 1e-9
    assert abs(rows[1][2] - (-45.0)) < 1e-9


def test_write_ledger_has_six_col_header_and_no_gaps():
    rows = reconcile.rebuild(client=MockClient())
    out = Path(tempfile.mkdtemp()) / "paper_days.csv"
    reconcile.write_ledger(rows, out=out)
    lines = out.read_text().splitlines()
    assert lines[0] == "date,equity,day_pnl,positions_flattened,orders_cancelled,positions_carried"
    assert lines[1].startswith("2025-07-13,100095.00,-55.00")
    assert len(lines) == 3  # header + 2 authoritative days


def test_sanity_rejects_flat_baseline():
    # the exact 2026-07-21 failure: flat 100000 line while account is at 99793
    rows = [("2026-07-16", 100000.0, 0.0), ("2026-07-17", 100000.0, 0.0)]
    ok, why = reconcile.sanity_check(rows, 99793.43)
    assert not ok and "disagrees" in why


def test_sanity_rejects_all_identical_equity():
    rows = [("2026-07-16", 100000.0, 0.0), ("2026-07-17", 100000.0, 0.0)]
    ok, why = reconcile.sanity_check(rows, 100000.0)
    assert not ok and "flat line" in why


def test_sanity_accepts_history_matching_account():
    rows = [("2026-07-16", 100000.0, 0.0), ("2026-07-17", 99793.22, -206.78)]
    ok, why = reconcile.sanity_check(rows, 99793.22)
    assert ok


def test_sanity_rejects_empty():
    assert reconcile.sanity_check([], 100000.0)[0] is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
