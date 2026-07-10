"""Offline unit tests. Run: python tests/test_offline.py"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main import build_heartbeat, build_status
from src.alpaca_client import AlpacaClient, LIVE_BASE

ACCOUNT = {"status": "ACTIVE", "equity": "100000", "buying_power": "200000",
           "cash": "100000", "trading_blocked": False, "account_blocked": False}
CLOCK_OPEN = {"is_open": True, "next_close": "2026-07-10T20:00:00Z"}
CLOCK_CLOSED = {"is_open": False, "next_open": "2026-07-13T13:30:00Z"}
POSITIONS = [{"symbol": "SPY", "qty": "10", "avg_entry_price": "560.25",
              "unrealized_pl": "12.50"}]


def test_heartbeat_open():
    msg = build_heartbeat(ACCOUNT, CLOCK_OPEN, "TS")
    assert "[HEARTBEAT] TS" in msg
    assert "equity $100,000.00" in msg
    assert "Market: OPEN" in msg
    assert "blocked: no" in msg


def test_heartbeat_closed():
    msg = build_heartbeat(ACCOUNT, CLOCK_CLOSED, "TS")
    assert "Market: CLOSED" in msg and "next open" in msg


def test_status():
    msg = build_status(ACCOUNT, POSITIONS, "TS")
    assert "1 open position(s)" in msg
    assert "SPY: 10 @ avg $560.25" in msg


def test_paper_lock():
    os.environ.pop("ALLOW_LIVE_TRADING", None)
    os.environ["ALPACA_API_KEY_ID"] = "k"
    os.environ["ALPACA_SECRET_KEY"] = "s"
    try:
        AlpacaClient(base_url=LIVE_BASE)
        raise AssertionError("live endpoint was NOT blocked")
    except RuntimeError as e:
        assert "PAPER LOCK" in str(e)
    AlpacaClient()  # paper works


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
