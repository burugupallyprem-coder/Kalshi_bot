"""Phase 2: live PAPER execution of the filtered ORB CANDIDATE (long-only).

The deployed config (config.yaml `live`) is the filtered ORB that PASSED the
hardened gate on 2026-07-18: opening-range breakout + volatility floor
(min_or_width_frac) + market-regime gate (SPY must be breaking up) + relative-
strength selection (rs_topk strongest names vs SPY). Train and validation agree
and it clears the walk-forward. It is still a BACKTEST edge on a 21-session paper
trial (see PRE_REGISTRATION.md) - being MEASURED live, NOT proven money, and NOT
eligible for real capital. Do not add capital-scaling or live-money logic.
The earlier UNFILTERED ORB was retired as a no-edge benchmark.

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
import json
import time as time_mod
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from src import slackbot
from src.alpaca_client import AlpacaClient
from src.strategies import filters

ROOT = Path(__file__).resolve().parent.parent.parent
ET = ZoneInfo("America/New_York")


def load_config():
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def now_et():
    return datetime.now(ET)


MAX_WAIT_MIN = 300   # jobs arrive HOURS early (GitHub cron is unreliable) and wait; public repo = free minutes


def _minutes_to_open(clock):
    try:
        nxt = datetime.fromisoformat(clock["next_open"].replace("Z", "+00:00"))
        return (nxt - datetime.now(timezone.utc)).total_seconds() / 60.0
    except Exception:
        return None


def _sleep_until_et(target, sleep_fn, label):
    """Sleep in 30s steps until wall-clock ET reaches target (capped)."""
    waited = 0
    while now_et().time() < target and waited < MAX_WAIT_MIN * 60:
        sleep_fn(30)
        waited += 30
    if waited:
        print(f"[{label}] waited {waited // 60}m - proceeding at {now_et().time()} ET")


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
    min_or_width_frac = params.get("min_or_width_frac")
    if len(bars) < open_bars + 1:
        return None
    rng = bars[:open_bars]
    rng_high = max(float(b["h"]) for b in rng)
    rng_low = min(float(b["l"]) for b in rng)
    rng_vol = sum(float(b["v"]) for b in rng) / open_bars
    if rng_high <= rng_low:
        return None
    if min_or_width_frac and rng_low > 0 and (rng_high - rng_low) / rng_low < float(min_or_width_frac):
        return None   # volatility floor: skip dead-tape openings
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


def load_premarket_flags(cfg):
    """Today's flags from data/premarket_flags.json, or None."""
    try:
        flags = json.loads((ROOT / "data" / "premarket_flags.json").read_text())
        if flags.get("date") != now_et().strftime("%Y-%m-%d"):
            return None
        return flags
    except Exception:
        return None


def load_arming(cfg):
    """Kill-switch. Returns (armed, reason).
    manual -> always armed (preserves the pre-registered THE MONTH measurement).
    auto   -> obey data/arming.json written by the research verdict; missing file
              is treated as NOT armed (fail-safe: never trade an unproven config)."""
    arm = cfg.get("arming", {}) or {}
    mode = arm.get("mode", "manual")
    if mode != "auto":
        return True, f"arming.mode={mode} (trading regardless of verdict)"
    try:
        a = json.loads((ROOT / "data" / "arming.json").read_text())
    except Exception:
        return False, "arming.mode=auto but data/arming.json missing - refusing to trade (fail-safe)"
    return bool(a.get("armed")), a.get("reason", "no reason recorded")


def _bars_early_return(bars, open_bars):
    """(last-of-opening-range close / first open) - 1, from Alpaca bar dicts."""
    if len(bars) < open_bars:
        return 0.0
    first_open = float(bars[0]["o"])
    last_close = float(bars[open_bars - 1]["c"])
    return (last_close / first_open - 1.0) if first_open > 0 else 0.0


def _bars_spy_long_ok(spy_bars, open_bars):
    """Market regime gate: True if SPY closed above its opening-range high on any
    completed bar so far. Session loop only runs before cutoff, so 'so far' is
    already time-bounded - no end-of-day lookahead."""
    if not spy_bars or len(spy_bars) < open_bars + 1:
        return False
    hi = max(float(b["h"]) for b in spy_bars[:open_bars])
    return any(float(b["c"]) > hi for b in spy_bars[open_bars:])


def _session_ran_today(client, today):
    """Reliable across isolated GitHub runners: a session ran today if EITHER the
    committed marker says so OR Alpaca shows an order placed today. The Alpaca
    check is authoritative on days that traded (the marker can lose a commit race)."""
    marker = ROOT / "data" / "last_entry.json"
    try:
        if json.loads(marker.read_text()).get("date") == today:
            return True
    except Exception:
        pass
    try:
        start_iso = f"{today}T00:00:00Z"
        return len(client.orders_after(start_iso)) > 0
    except Exception:
        return False


def run_entry_session(cfg, client=None, sleep_fn=time_mod.sleep):
    live = cfg["live"]
    params = live["params"]
    strategy = live["strategy"]
    cutoff = _parse_hhmm(params.get("cutoff_et", "10:30"))
    poll_secs = int(live.get("poll_seconds", 120))
    max_positions = int(live.get("max_positions", 3))
    client = client or AlpacaClient()  # paper-locked

    clock = client.clock()
    session_start = _parse_hhmm(live.get("session_start_et", "09:35"))
    if not clock.get("is_open"):
        mto = _minutes_to_open(clock)
        if mto is None or mto > MAX_WAIT_MIN:
            print(f"market closed, next open {mto} min away - not a trading morning")
            return
        print(f"[entry-session] arrived early ({mto:.0f}m before open) - waiting")
    if now_et().time() < session_start:
        _sleep_until_et(session_start, sleep_fn, "entry-session")
    if now_et().time() >= cutoff:
        today = now_et().strftime("%Y-%m-%d")
        if _session_ran_today(client, today):
            print("[entry-session] past cutoff - a session already ran/traded today, staying quiet")
            return
        print("[entry-session] past cutoff and no session ran today - late scheduler")
        slackbot.post(
            f"[TRADE] {today} - NO SESSION. Entry job started at "
            f"{now_et().strftime('%H:%M')} ET, past the {params.get('cutoff_et','10:30')} ET "
            f"cutoff, so no trades were possible. This means GitHub delivered the schedule "
            f"late - a scheduling problem, NOT a strategy decision. Investigate cron timing.")
        return
    armed, arm_reason = load_arming(cfg)
    if not armed:
        slackbot.post(f"[TRADE] Entry session DISARMED - no entries today. Reason: {arm_reason}")
        print(f"[entry-session] disarmed: {arm_reason}")
        return
    pm_cfg = live.get("premarket") or {}
    guard = pm_cfg.get("guard_mode", "log_only")
    flags = load_premarket_flags(cfg) or {}
    skip_syms = set()
    if flags.get("halt_today"):
        if guard == "enforce":
            slackbot.post("[TRADE] Session HALTED by pre-market flag (large overnight gap). No entries today.")
            return
        print("[entry-session] premarket would-halt flag present (log_only - trading normally)")
    if flags.get("skip_symbols"):
        if guard == "enforce":
            skip_syms = set(flags["skip_symbols"])
            print(f"[entry-session] enforcing symbol skips: {sorted(skip_syms)}")
        else:
            print(f"[entry-session] premarket would-skip (log_only): {flags['skip_symbols']}")
    et_now = now_et()
    offset = et_now.strftime("%z")
    offset = offset[:3] + ":" + offset[3:]   # -0400 -> -04:00 (DST-safe)
    start_iso = f"{et_now.strftime('%Y-%m-%d')}T09:30:00{offset}"
    attempted = set()
    placed = []
    polls = 0
    try:
        (ROOT / "data").mkdir(exist_ok=True)
        (ROOT / "data" / "last_entry.json").write_text(json.dumps(
            {"date": now_et().strftime("%Y-%m-%d"), "started_et": now_et().strftime("%H:%M")}))
    except Exception as e:
        print(f"[entry-session] could not write run marker: {e}")
    regime_ok_ever = False
    last_shortlist = []
    signals_seen = 0
    open_bars = int(params.get("open_bars", 3))
    regime_filter = bool(params.get("regime_filter", False))
    rs_topk = params.get("rs_topk")
    print(f"[entry-session] {strategy} on {len(cfg['universe'])} symbols until {cutoff} ET "
          f"| regime_filter={regime_filter} rs_topk={rs_topk} "
          f"min_or_width_frac={params.get('min_or_width_frac')}")

    while now_et().time() < cutoff:
        try:
            polls += 1
            equity = float(client.account()["equity"])
            open_names = {p["symbol"] for p in client.positions()}
            open_names |= {o["symbol"] for o in client.open_orders()}
            if len(open_names) >= max_positions:
                sleep_fn(poll_secs)
                continue
            # Fetch the FULL universe each poll: SPY is needed for the regime gate
            # and every name is needed to rank relative strength. Same filters the
            # research winner used - now applied to live bars.
            bars_by_sym = client.today_bars(cfg["universe"], start_iso,
                                            feed=live.get("feed", "iex"))
            spy_bars = bars_by_sym.get("SPY") or []

            # market-regime gate (long only): only trade when SPY itself breaks up
            if regime_filter and not _bars_spy_long_ok(spy_bars, open_bars):
                print("[entry-session] regime: SPY not breaking up - standing down this poll")
                sleep_fn(poll_secs)
                continue
            regime_ok_ever = True

            # relative-strength selection: restrict to the strongest names vs SPY
            allowed = set(cfg["universe"])
            if rs_topk:
                spy_er = _bars_early_return(spy_bars, open_bars)
                scores = {sym: _bars_early_return(b, open_bars) - spy_er
                          for sym, b in bars_by_sym.items() if len(b) >= open_bars}
                allowed = filters.top_k_symbols(scores, rs_topk)

            symbols = [s for s in cfg["universe"]
                       if s in allowed and s not in attempted
                       and s not in open_names and s not in skip_syms]
            last_shortlist = sorted(allowed)
            if symbols:
                for sym in symbols:
                    if len(open_names) + len(placed) >= max_positions:
                        break
                    sig = compute_orb_signal(bars_by_sym.get(sym) or [], params)
                    if not sig:
                        continue
                    signals_seen += 1
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

    # ALWAYS report, even (especially) when nothing traded. Silence must never be
    # ambiguous: the operator must be able to tell "stood down correctly" from
    # "never ran at all".
    today_str = now_et().strftime("%Y-%m-%d")
    if placed:
        body = f"Placed {len(placed)} order(s): {', '.join(placed)}."
    elif regime_filter and not regime_ok_ever:
        body = ("0 trades - REGIME STAND-DOWN: SPY never closed above its opening range "
                "before cutoff, so the filter blocked every entry. Working as designed.")
    elif signals_seen == 0:
        body = (f"0 trades - no qualifying breakout. Shortlist was "
                f"{last_shortlist or 'empty'} (vol floor {params.get('min_or_width_frac')}).")
    else:
        body = f"0 trades - {signals_seen} signal(s) found but sizing/caps rejected them."
    slackbot.post(
        f"[TRADE] {today_str} entry session complete ({polls} poll(s), "
        f"09:35-{params.get('cutoff_et', '10:30')} ET).\n{body}\n"
        f"regime_filter={regime_filter} | rs_topk={params.get('rs_topk')} | "
        f"max_positions={max_positions}")


def _append_paper_day(equity, day_pnl, n_flat, n_cancelled, carried=0):
    """Append one row to data/paper_days.csv. carried = positions that could
    NOT be flattened (market already closed) - logged for honesty, never hidden."""
    out = ROOT / "data" / "paper_days.csv"
    out.parent.mkdir(exist_ok=True)
    new = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "equity", "day_pnl", "positions_flattened",
                        "orders_cancelled", "positions_carried"])
        w.writerow([now_et().strftime("%Y-%m-%d"), f"{equity:.2f}", f"{day_pnl:.2f}",
                    n_flat, n_cancelled, carried])


def run_eod_flatten(cfg, client=None, sleep_fn=time_mod.sleep):
    client = client or AlpacaClient()  # paper-locked

    # dedupe FIRST: a redundant cron tick must never double-flatten or double-log.
    log_path = ROOT / "data" / "paper_days.csv"
    today = now_et().strftime("%Y-%m-%d")
    if log_path.exists() and any(line.startswith(today) for line in log_path.read_text().splitlines()):
        print("[eod] already flattened/logged today - skip")
        return

    clock = client.clock()
    is_open = bool(clock.get("is_open"))

    # On-time path: market open. Wait until 15:45 ET, then cancel + flatten.
    if is_open:
        if now_et().time() < dtime(15, 45):
            print("[eod] arrived early - waiting for 15:45 ET (scheduler-proof)")
            _sleep_until_et(dtime(15, 45), sleep_fn, "eod")
        positions = client.positions()
        open_orders = client.open_orders()
        client.cancel_all_orders()
        if positions:
            client.close_all_positions()
        account = client.account()
        equity = float(account["equity"])
        last_equity = float(account.get("last_equity") or equity)
        day_pnl = equity - last_equity
        _append_paper_day(equity, day_pnl, len(positions), len(open_orders), carried=0)
        slackbot.post(
            f"[EOD] {today} paper recap\n"
            f"Equity ${equity:,.2f} | day P&L ${day_pnl:+,.2f}\n"
            f"Flattened {len(positions)} position(s), cancelled {len(open_orders)} order(s). "
            f"Everything is cash overnight - by design.")
        print(f"[eod] equity {equity:.2f} day_pnl {day_pnl:+.2f}")
        return

    # Late/missed path: market already closed when this tick ran. We cannot
    # market-close now. Never silently skip: cancel stale orders, LOG the day so
    # the ledger cannot freeze, and LOUDLY surface any position that carried
    # without protection (bracket stop/target are DAY orders - expired at close).
    positions = client.positions()
    open_orders = client.open_orders()
    if not positions and not open_orders:
        # Flat and closed - the on-time tick owns clean flat days and reconcile.py
        # is the authoritative backfill. Don't write speculative holiday rows.
        print("[eod] market closed, account already flat - nothing to flatten")
        slackbot.post(
            f"[EOD] {today} - no action. EOD tick ran at {now_et().strftime('%H:%M')} ET "
            f"(after the close) and the account was already flat: no positions, no open "
            f"orders, nothing to cancel. No ledger row written for today.\n"
            f"If you see this every day, the EOD schedule is arriving late - investigate.")
        return
    try:
        client.cancel_all_orders()
    except Exception as e:
        print(f"[eod] cancel_all_orders failed on closed market: {e}")
    account = client.account()
    equity = float(account["equity"])
    last_equity = float(account.get("last_equity") or equity)
    day_pnl = equity - last_equity
    carried = len(positions)
    _append_paper_day(equity, day_pnl, 0, len(open_orders), carried=carried)
    slackbot.post(
        f"[EOD][WARNING] {today} - EOD ran AFTER market close ({now_et().strftime('%H:%M')} ET).\n"
        f"Equity ${equity:,.2f} | day P&L ${day_pnl:+,.2f}\n"
        f"{carried} position(s) COULD NOT be flattened and have carried overnight "
        f"WITHOUT protective stops (bracket legs are day orders - they expired at close). "
        f"Cancelled {len(open_orders)} stale order(s). "
        f"This violates the flat-by-close rule - investigate cron timing.")
    print(f"[eod][WARN] post-close: equity {equity:.2f} day_pnl {day_pnl:+.2f} carried {carried}")


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
