"""Dashboard render test. Run: python tests/test_dashboard.py"""
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live import dashboard


def test_render_with_sample_data():
    root = dashboard.ROOT
    (root / "data").mkdir(exist_ok=True)
    with open(root / "data" / "paper_days.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "equity", "day_pnl", "positions_flattened", "orders_cancelled"])
        w.writerow(["2026-07-10", "100150.00", "150.00", "2", "1"])
        w.writerow(["2026-07-13", "100095.00", "-55.00", "1", "0"])
    (root / "data" / "premarket_flags.json").write_text(json.dumps(
        {"date": "2026-07-13", "halt_today": False, "skip_symbols": ["TSLA"],
         "gaps": {"SPY": 0.3, "TSLA": -5.2, "NVDA": 1.9}}))
    os.environ["WORKFLOW_NAME"] = "trade-entry"
    os.environ["RUN_OUTCOME"] = "success"
    dashboard.main()
    html_out = (root / "dashboard.html").read_text()
    assert "MISSION CONTROL" in html_out
    assert "$100,095" in html_out
    assert "TSLA -5.2%" in html_out
    assert "would skip" in html_out
    assert "PAPER ACCOUNT ONLY" in html_out
    status = json.loads((root / "data" / "status.json").read_text())
    assert status["runs"][-1]["wf"] == "trade-entry" and status["runs"][-1]["ok"]
    print("rendered", len(html_out), "bytes")


if __name__ == "__main__":
    test_render_with_sample_data()
    print("PASS test_render_with_sample_data")
    print("1 test passed")
