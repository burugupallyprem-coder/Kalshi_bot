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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
