import argparse
from datetime import datetime, timezone

from src import slackbot
from src.alpaca_client import AlpacaClient


def _money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def build_heartbeat(account, clock, ts):
    blocked = account.get("trading_blocked") or account.get("account_blocked")
    market = "OPEN" if clock.get("is_open") else "CLOSED"
    when = (
        f"closes {clock.get('next_close', '?')}"
        if clock.get("is_open")
        else f"next open {clock.get('next_open', '?')}"
    )
    return "\n".join([
        f"[HEARTBEAT] {ts}",
        (
            f"Account: {account.get('status', '?')} - equity {_money(account.get('equity'))}"
            f" - buying power {_money(account.get('buying_power'))}"
            f" - blocked: {'YES' if blocked else 'no'}"
        ),
        f"Market: {market} ({when})",
        "stock-trader-bot Phase 0 is alive. Paper account only.",
    ])


def build_status(account, positions, ts):
    lines = [
        f"[STATUS] {ts}",
        f"Equity {_money(account.get('equity'))} - cash {_money(account.get('cash'))}"
        f" - {len(positions)} open position(s)",
    ]
    for p in positions:
        lines.append(
            f"- {p.get('symbol')}: {p.get('qty')} @ avg {_money(p.get('avg_entry_price'))}"
            f" (unrealized {_money(p.get('unrealized_pl'))})"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="stock-trader-bot Phase 0")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--heartbeat", action="store_true")
    mode.add_argument("--status", action="store_true")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    client = AlpacaClient()  # paper-locked
    account = client.account()
    if args.heartbeat:
        msg = build_heartbeat(account, client.clock(), ts)
    else:
        msg = build_status(account, client.positions(), ts)
    slackbot.post(msg)
    print("done")


if __name__ == "__main__":
    main()
