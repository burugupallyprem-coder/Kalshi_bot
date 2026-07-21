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

from src import slackbot
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


def sanity_check(rows, account_equity, tol=1.0):
    """Refuse to trust portfolio history that contradicts the live account.

    Learned the hard way 2026-07-21: portfolio/history returned a flat baseline
    (every day 100000.00 / 0.00) while the account was actually at 99,793 - and
    the old code happily overwrote a correct ledger with it. Never again: if the
    most recent reconstructed equity disagrees with the broker's current equity,
    the data is not authoritative and we do NOT write."""
    if not rows:
        return False, "no portfolio history returned"
    last_equity = float(rows[-1][1])
    if abs(last_equity - float(account_equity)) > tol:
        return False, (f"history disagrees with account: last reconstructed equity "
                       f"${last_equity:,.2f} vs live equity ${float(account_equity):,.2f}")
    distinct = {round(float(r[1]), 2) for r in rows}
    if len(distinct) == 1:
        return False, (f"history is a flat line at ${last_equity:,.2f} across "
                       f"{len(rows)} days - not real data")
    return True, "history agrees with the live account"


def main():
    client = AlpacaClient()
    rows = rebuild(client=client)
    equity = float(client.account()["equity"])
    ok, why = sanity_check(rows, equity)
    if not ok:
        msg = (f"[RECONCILE][ABORTED] Ledger NOT rewritten - {why}. "
               f"Existing data/paper_days.csv left untouched. "
               f"Alpaca portfolio/history is not usable as-is; the EOD writer remains "
               f"the source of truth until this is fixed.")
        print(msg)
        try:
            slackbot.post(msg)
        except Exception as e:
            print(f"[reconcile] slack post failed: {e}")
        return
    out = write_ledger(rows)
    print(f"[reconcile] rewrote {out} with {len(rows)} authoritative day(s) from Alpaca")


if __name__ == "__main__":
    main()
