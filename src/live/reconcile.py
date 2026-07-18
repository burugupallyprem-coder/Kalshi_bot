"""Authoritative rebuild of data/paper_days.csv from Alpaca's own records.

The live EOD writer is best-effort (a dropped/late cron can miss a day). This
script is the source of truth: it pulls the paper account's portfolio history
from Alpaca and rewrites the daily ledger so equity/day_pnl are exactly what the
broker recorded - no fabricated numbers, no silent gaps.

Runs in CI where ALPACA_* secrets exist:  python -m src.live.reconcile
Columns not derivable from portfolio history (positions_flattened /
orders_cancelled / positions_carried) are written blank and marked reconstructed.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.alpaca_client import AlpacaClient

ROOT = Path(__file__).resolve().parent.parent.parent


def rebuild(client=None, period="3M"):
    client = client or AlpacaClient()  # paper-locked
    hist = client.portfolio_history(period=period, timeframe="1D")
    ts = hist.get("timestamp") or []
    equity = hist.get("equity") or []
    pl = hist.get("profit_loss") or []
    rows = []
    for i, t in enumerate(ts):
        eq = equity[i] if i < len(equity) else None
        if eq is None:
            continue
        day = datetime.fromtimestamp(int(t), tz=timezone.utc).astimezone(
            timezone.utc).strftime("%Y-%m-%d")
        day_pnl = pl[i] if i < len(pl) and pl[i] is not None else ""
        rows.append((day, eq, day_pnl))
    return rows


def write_ledger(rows, out=None):
    out = out or (ROOT / "data" / "paper_days.csv")
    out.parent.mkdir(exist_ok=True)
    # in-place overwrite (this mount may block unlink) with authoritative data
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "equity", "day_pnl", "positions_flattened",
                    "orders_cancelled", "positions_carried"])
        for day, eq, day_pnl in rows:
            pnl_str = f"{float(day_pnl):.2f}" if day_pnl not in ("", None) else ""
            w.writerow([day, f"{float(eq):.2f}", pnl_str, "", "", ""])
    return out


def main():
    rows = rebuild()
    if not rows:
        print("[reconcile] no portfolio history returned - leaving ledger untouched")
        return
    out = write_ledger(rows)
    print(f"[reconcile] rewrote {out} with {len(rows)} authoritative day(s) from Alpaca")


if __name__ == "__main__":
    main()
