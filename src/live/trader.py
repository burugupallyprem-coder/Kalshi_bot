"""Phase 2: live PAPER execution of the research winner (ORB, long-only).

Two modes, both idempotent and safe to re-run:
  --entry-session   poll from ~09:35 ET until cutoff; place bracket orders on
                    ORB signals. Server-side stops/targets mean a crashed job
                    can never orphan a position.
  --eod-flatten     15:50 ET: cancel open orders, close any open positions,
                    post the daily recap to Slack, append the trade log.

Risk caps enforced here IN ADDITION to server-side brackets:
  - risk per trade <= risk_pct of live equity (stop-distance sizing)
  - max_positions concurrent names
  - one attempt per symbol per day
  - no entries after the strategy cutoff
Worst-case daily loss is structurally bounded ~= max_positions x risk_pct.
"""

import argparse
import csv
import time as time_mod
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from src import slackbot
from src.alpaca_client import AlpacaClient

ROOT = Path(__file__).resolve().parent.parent.parent
ET = ZoneInfo("America/New_York")


def load_config():
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def now_et():
    return datetime.now(ET)


def _parse_hhmm(s):
    hh, mm = [int(x) for x in s.split(":")]
    return dtime(hh, mm)


def compute_orb_signal(bars, params):
    """bars: list of Alpaca bar dicts (completed 5-min bars, ascending).
    Returns dict(stop, entry_est) when the LAST completed bar closes above the
    opening range; None otherwise. Mirrors src/strategies/orb.py logic."""
    open_bars = int(params.get("open_bars", 3))
    max_risk_frac = float(params.get("max_risk_frac", 0.02))
    vol_confirm = bool(params.get("vol_confirm", False))
    if len(bars) < open_bars + 1:
        return None
    rng = bars[:open_bars]
    rng_high = max(float(b["h"]) for b in rng)
    rng_low = min(float(b["l"]) for b in rng)
    rng_vol = sum(float(b["v"]) for b in rng) / open_bars
    if rng_high <= rng_low:
        return None
    last = bars[-1]
    close = float(last["c"])
    if close <= rng_high:
        return None
    if vol_confirm and rng_vol > 0 and float(last["v"]) < 1.5 * rng_vol:
        return None
    risk = close - rng_low
    if risk <= 0 or risk / close > max_risk_frac:
        return None
    return {"stop": rng_low, "entry_est": close}


def size_shares(entry, stop, equity, cfg):
    import math
    risk_dollars = equity * cfg["risk"]["risk_pct"] / 100.0
    per_share = entry - stop
    if per_share <= 0:
        return 0
    shares = math.floor(risk_dollars / per_share)
    max_value = equity * cfg["risk"]["max_position_pct"] / 100.0
    return max(min(shares, math.floor(max_value / entry)), 0)


def run_entry_session(cfg, client=None, sleep_fn=time_mod.sleep):
    live = cfg["live"]
    params = live["params"]
    strategy = live["strategy"]
    cutoff = _parse_hhmm(params.get("cutoff_et", "10:30"))
    poll_secs = int(live.get("poll_seconds", 120))
    max_positions = int(live.get("max_positions", 3))
    client = client or AlpacaClient()  # paper-locked

    clock = client.clock()
    if not clock.get("is_open"):
        print("market closed - nothing to do")
        return
    et_now = now_et()
    offset = et_now.strftime("%z")
    offset = offset[:3] + ":" + offset[3:]   # -0400 -> -04:00 (DST-safe)
    start_iso = f"{et_now.strftime('%Y-%m-%d')}T09:30:00{offset}"
    attempted = set()
    placed = []
    print(f"[entry-session] {strategy} on {len(cfg['universe'])} symbols until {cutoff} ET")

    while now_et().time() < cutoff:
        try:
            equity = float(client.account()["equity"])
            open_names = {p["symbol"] for p in client.positions()}
            open_names |= {o["symbol"] for o in client.open_orders()}
            if len(open_names) >= max_positions:
                sleep_fn(poll_secs)
                continue
            symbols = [s for s in cfg["universe"]
                       if s not in attempted and s not in open_names]
            if symbols:
                bars_by_sym = client.today_bars(symbols, start_iso,
                                                feed=live.get("feed", "iex"))
                for sym in symbols:
                    if len(open_names) + len(placed) >= max_positions:
                        break
                    sig = compute_orb_signal(bars_by_sym.get(sym) or [], params)
                    if not sig:
                        continue
                    attempted.add(sym)
                    entry_est = sig["entry_est"]
                    stop = sig["stop"]
                    target = entry_est + float(params.get("rr", 1.5)) * (entry_est - stop)
                    qty = size_shares(entry_est, stop, equity, cfg)
                    if qty <= 0:
                        continue
                    order = client.place_bracket_order(sym, qty, stop, target)
                    placed.append(sym)
                    slackbot.post(
                        f"[TRADE] BUY {qty} {sym} ~${entry_est:.2f} | "
                        f"stop ${stop:.2f} target ${target:.2f} | "
                        f"risk ${(entry_est - stop) * qty:,.0f} "
                        f"({cfg['risk']['risk_pct']}% of ${equity:,.0f}) | "
                        f"thesis: ORB breakout (paper, order {order.get('id', '?')[:8]})")
        except Exception as e:  # log and keep the session alive
            print(f"[entry-session] error: {e}")
        sleep_fn(poll_secs)

    print(f"[entry-session] done - placed {len(placed)}: {placed}")


def run_eod_flatten(cfg, client=None):
    client = client or AlpacaClient()  # paper-locked
    clock = client.clock()
    if not clock.get("is_open"):
        print("[eod] market closed - skip (day orders already expired)")
        return
    if now_et().time() < dtime(15, 40):
        print("[eod] too early - this cron tick is for the other DST season")
        return
    positions = client.positions()
    open_orders = client.open_orders()
    client.cancel_all_orders()
    if positions:
        client.close_all_positions()
    account = client.account()
    equity = float(account["equity"])
    last_equity = float(account.get("last_equity") or equity)
    day_pnl = equity - last_equity
    # append recap row
    out = ROOT / "data" / "paper_days.csv"
    out.parent.mkdir(exist_ok=True)
    new = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "equity", "day_pnl", "positions_flattened", "orders_cancelled"])
        w.writerow([now_et().strftime("%Y-%m-%d"), f"{equity:.2f}", f"{day_pnl:.2f}",
                    len(positions), len(open_orders)])
    slackbot.post(
        f"[EOD] {now_et().strftime('%Y-%m-%d')} paper recap\n"
        f"Equity ${equity:,.2f} | day P&L ${day_pnl:+,.2f}\n"
        f"Flattened {len(positions)} position(s), cancelled {len(open_orders)} order(s). "
        f"Everything is cash overnight - by design.")
    print(f"[eod] equity {equity:.2f} day_pnl {day_pnl:+.2f}")


def main():
    parser = argparse.ArgumentParser(description="stock-trader-bot Phase 2 (paper)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--entry-session", action="store_true")
    mode.add_argument("--eod-flatten", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    if args.entry_session:
        run_entry_session(cfg)
    else:
        run_eod_flatten(cfg)


if __name__ == "__main__":
    main()
