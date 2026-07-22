"""Peter's 3-step "boring" scalp on STOCKS - RESEARCH ONLY, PAPER-adjacent, nothing trades.

Ported from the Forex_backtest repo (strategy #10) to the Alpaca stock universe.
This is a research backtest only: it never touches the live/paper trader, the
arming kill-switch, or alpaca_client's PAPER LOCK.

The 3 steps, mechanized on 1-MINUTE bars:
  1. DIRECTION - daily 9/21 EMA. Uptrend = prev daily close > EMA9 > EMA21
     (longs), downtrend = prev close < EMA9 < EMA21 (shorts); else range.
     `trend_filter` grid knob: true = trade only with the daily trend, false =
     also trade ranges in the breakout's own direction.
  2. SETUP - previous-day High/Low as ZONES (half-width zone_frac x prev-day
     range) PLUS the first 5-minute opening range (first `open_bars` 1-min bars
     of the RTH session). Four battleground levels/day.
  3. ENTRY - break-and-retest: a 1-min CLOSE clears the zone, price retests it,
     a strong in-direction 1-min close triggers -> fill NEXT bar open (slippage
     against us). EXIT - initial stop behind the broken level, then a stop that
     TRAILS the swing low/high of the last `trail_lookback` bars, ratcheting one
     way only. Flat by risk.flat_by_et. Max 1-2 trades/symbol/day.

WHY ITS OWN SIMULATOR: the shared engine.py (which the live ORB champion uses)
models fixed R-multiple targets, not a trailing stop - so touching it would risk
the deployed strategy. This module has a self-contained, equally conservative
simulator (stop checked before target each bar; entry bar can stop out; gaps
fill at the open on the bad side; slippage charged against us both sides;
integer share sizing; 0.5% risk; 20% notional cap; no compounding) and reuses
the repo's data / metrics / slack layers and Trade type unchanged.

Honesty scaffolding kept from research.py: TRAIN 2024-07->2025-12 picks the
winner, judged ONCE on 2026 VALIDATION; gate on validation; slippage
sensitivity; walk-forward folds; WEAK PASS + overfit labels. Shorts modeled
without borrow fees (megacaps; noted). 1Min SIP volumes/fills are paper-grade.

Run: python -m src.backtest.strategy10_scalp
"""

import itertools
import math
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml

from src import data as data_mod
from src import slackbot
from src.backtest import metrics
from src.backtest.engine import Trade

ROOT = Path(__file__).resolve().parent.parent.parent


def load_config():
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def expand_grid(grid):
    keys = sorted(grid.keys())
    return [dict(zip(keys, values))
            for values in itertools.product(*(grid[k] for k in keys))]


def _size(entry, stop, cfg):
    equity = cfg["risk"]["equity"]
    risk_dollars = equity * cfg["risk"]["risk_pct"] / 100.0
    per_share = abs(entry - stop)
    if per_share <= 0:
        return 0
    shares = math.floor(risk_dollars / per_share)
    shares = min(shares, math.floor(equity * cfg["risk"]["max_position_pct"] / 100.0 / entry))
    return max(shares, 0)


def _minute(et):
    return et.hour * 60 + et.minute


def daily_ema_dir(df, fast, slow):
    """{date: +1/-1/0} known at that session's open (prior sessions only)."""
    daily = df.groupby("date")["close"].last()
    ema_f = daily.ewm(span=fast, adjust=False).mean()
    ema_s = daily.ewm(span=slow, adjust=False).mean()
    pc, pf, ps = daily.shift(1), ema_f.shift(1), ema_s.shift(1)
    out = {}
    for date in daily.index:
        a, b, c = pc[date], pf[date], ps[date]
        if pd.isna(a) or pd.isna(b) or pd.isna(c):
            out[date] = 0
        elif a > b and b > c:
            out[date] = 1
        elif a < b and b < c:
            out[date] = -1
        else:
            out[date] = 0
    return out


def prev_day_levels(df):
    g = df.groupby("date").agg(hi=("high", "max"), lo=("low", "min"))
    g["phi"] = g["hi"].shift(1)
    g["plo"] = g["lo"].shift(1)
    return {d: (r["phi"], r["plo"]) for d, r in g.iterrows() if r["phi"] == r["phi"]}


def opening_ranges(df, open_bars):
    """{date: (or_high, or_low)} from the first open_bars 1-min bars of the session."""
    out = {}
    for date, day in df.groupby("date"):
        head = day.iloc[:open_bars]
        out[date] = (float(head["high"].max()), float(head["low"].min()))
    return out


def simulate_symbol(df, symbol, params, cfg):
    """1-min break-and-retest + swing-trailing stop for one symbol across all sessions."""
    tl = int(params["trail_lookback"])
    use_trend = bool(params["trend_filter"])
    max_td = int(params["max_trades_day"])
    min_mult = float(cfg["strategy10"].get("min_stop_cost_mult", 2.0))
    slip = cfg["costs"]["slippage_cents"] / 100.0
    open_bars = int(cfg["strategy10"]["open_bars"])
    zone_frac = float(cfg["strategy10"]["zone_frac"])
    buf_frac = float(cfg["strategy10"]["stop_buf_frac"])
    hh, mm = [int(x) for x in cfg["risk"]["flat_by_et"].split(":")]
    flat_min = hh * 60 + mm

    ema = daily_ema_dir(df, int(cfg["strategy10"]["ema_fast"]), int(cfg["strategy10"]["ema_slow"]))
    pdl = prev_day_levels(df)
    orl = opening_ranges(df, open_bars)

    trades = []
    pos = None
    pending = None
    cur_date = None
    trades_today = 0
    day_dir = 0
    rng = zone = buf = 0.0
    day_open_min = None
    state = {}
    df = df.reset_index(drop=True)
    n = len(df)

    def close_trade(row, exit_px, reason):
        d = pos["side"]
        risk_ps = abs(pos["entry"] - pos["stop_init"])
        pnl = (exit_px - pos["entry"]) * pos["shares"] * d
        trades.append(Trade(
            symbol=symbol, strategy="strategy10_scalp",
            date=str(row["et"].date()), entry_time=pos["entry_time"],
            exit_time=str(row["et"].time()), entry=round(pos["entry"], 4),
            exit=round(exit_px, 4), shares=pos["shares"],
            stop=round(pos["stop_init"], 4), target=0.0, pnl=round(pnl, 2),
            r_multiple=round((exit_px - pos["entry"]) * d / risk_ps, 3) if risk_ps > 0 else 0.0,
            exit_reason=reason, signal_reason=pos["reason"],
            side="long" if d == 1 else "short"))

    for i in range(n):
        row = df.iloc[i]
        date = row["date"]
        minute = _minute(row["et"])
        o, hi_b, lo_b, c = (float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"]))

        if date != cur_date:
            cur_date = date
            trades_today = 0
            pending = None
            day_dir = ema.get(date, 0)
            day_open_min = minute            # first RTH bar minute of this session
            state = {}
            if date in pdl:
                phi, plo = pdl[date]
                rng = phi - plo
                zone = zone_frac * rng if rng > 0 else 0.0
                buf = buf_frac * rng if rng > 0 else 0.0
            else:
                rng = zone = buf = 0.0

        # 1) flat cutoff
        if pos is not None and minute >= flat_min:
            close_trade(row, o - pos["side"] * slip, "eod_flat")
            pos = None

        # 2) pending entry fills at THIS bar open
        if pos is None and pending is not None and minute < flat_min:
            side = pending["side"]
            entry_px = o + side * slip
            stop = pending["stop"]
            risk_ps = (entry_px - stop) * side
            if risk_ps > 0 and risk_ps >= min_mult * 2 * slip:
                shares = _size(entry_px, stop, cfg)
                if shares > 0:
                    pos = {"side": side, "entry": entry_px, "stop": stop,
                           "stop_init": stop, "buf": pending["buf"], "shares": shares,
                           "entry_time": str(row["et"].time()), "reason": pending["reason"],
                           "exit_label": "stop", "win_low": [], "win_high": []}
                    trades_today += 1
        pending = None

        # 3) manage - stop checked first (entry bar included), then ratchet trail
        if pos is not None:
            side = pos["side"]
            if side == 1 and lo_b <= pos["stop"]:
                close_trade(row, min(o, pos["stop"]) - slip, pos["exit_label"])
                pos = None
            elif side == -1 and hi_b >= pos["stop"]:
                close_trade(row, max(o, pos["stop"]) + slip, pos["exit_label"])
                pos = None
            if pos is not None:
                pos["win_low"].append(lo_b)
                pos["win_high"].append(hi_b)
                if len(pos["win_low"]) >= tl:
                    if pos["side"] == 1:
                        ns = min(pos["win_low"][-tl:]) - pos["buf"]
                        if ns > pos["stop"]:
                            pos["stop"] = ns
                            pos["exit_label"] = "trail_stop"
                    else:
                        ns = max(pos["win_high"][-tl:]) + pos["buf"]
                        if ns < pos["stop"]:
                            pos["stop"] = ns
                            pos["exit_label"] = "trail_stop"

        # 4) signal on THIS close -> pending for next bar
        or_ready = day_open_min is not None and minute >= day_open_min + open_bars
        if (pos is None and minute < flat_min and trades_today < max_td and rng > 0
                and i < n - 1 and df.iloc[i + 1]["date"] == date):
            levels = [("PDH", pdl[date][0], 1), ("PDL", pdl[date][1], -1)]
            if or_ready and date in orl:
                orh, orlo = orl[date]
                levels += [("ORH", orh, 1), ("ORL", orlo, -1)]
            for key, L, lside in levels:
                if use_trend and lside != day_dir:
                    continue
                st = state.setdefault(key, {"broke": False, "retested": False, "used": False})
                if st["used"]:
                    continue
                if lside == 1:
                    band = L + zone
                    if not st["broke"]:
                        if c > band:
                            st["broke"] = True
                    elif not st["retested"]:
                        if lo_b <= band:
                            st["retested"] = True
                    elif c > band and c > o:
                        pending = {"side": 1, "stop": L - buf, "buf": buf,
                                   "reason": f"{key.lower()}_break_retest_long"}
                        st["used"] = True
                        break
                else:
                    band = L - zone
                    if not st["broke"]:
                        if c < band:
                            st["broke"] = True
                    elif not st["retested"]:
                        if hi_b >= band:
                            st["retested"] = True
                    elif c < band and c < o:
                        pending = {"side": -1, "stop": L + buf, "buf": buf,
                                   "reason": f"{key.lower()}_break_retest_short"}
                        st["used"] = True
                        break

    if pos is not None and n > 0:
        row = df.iloc[n - 1]
        close_trade(row, float(row["close"]) - pos["side"] * slip, "data_end")
    return trades


def run_combo(bars, combo, cfg):
    base = dict(combo)
    trades = []
    for symbol, sym in bars.groupby("symbol"):
        trades.extend(simulate_symbol(sym, symbol, base, cfg))
    return trades


def split_trades(trades, train_end, val_start):
    tr = [t for t in trades if pd.to_datetime(t.date).date() <= train_end]
    va = [t for t in trades if pd.to_datetime(t.date).date() >= val_start]
    return tr, va


def walk_forward(va_trades, folds):
    if not va_trades:
        return 0, 0, []
    df = pd.DataFrame([t.__dict__ for t in va_trades])
    dates = sorted(set(df["date"]))
    size = max(1, len(dates) // folds)
    per = []
    for k in range(folds):
        lo = k * size
        hi = (k + 1) * size if k < folds - 1 else len(dates)
        if lo >= len(dates):
            break
        window = set(dates[lo:hi])
        sub = df[df["date"].isin(window)]
        per.append(sub["r_multiple"].mean() if len(sub) else 0.0)
    return sum(1 for r in per if r > 0), len(per), per


def run():
    cfg = load_config()
    s10 = cfg["strategy10"]
    cfg["universe"] = s10["universe"]
    val_end = s10.get("val_end") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    symbols = s10["universe"]
    gate = cfg["gate"]
    train_end = pd.to_datetime(s10["train_end"]).date()
    val_start = pd.to_datetime(s10["val_start"]).date()
    train_floor = s10.get("min_train_expectancy_r", 0.02)

    print(f"downloading {len(symbols)} symbols {s10['timeframe']}, {s10['train_start']} -> {val_end}", flush=True)
    bars = data_mod.fetch_bars(symbols, s10["train_start"], val_end,
                               timeframe=s10["timeframe"], feed=s10["feed"])
    if bars.empty:
        slackbot.post(f"[BACKTEST-S10] {ts} - FAILED: no bars returned from Alpaca. Check keys/plan.")
        return
    bars = data_mod.rth_only(bars)
    print(f"bars: {len(bars):,} rows", flush=True)

    combos = expand_grid(s10["grids"])
    results = []
    for idx, combo in enumerate(combos, 1):
        tr, va = split_trades(run_combo(bars, combo, cfg), train_end, val_start)
        m = metrics.summarize(tr)
        cs = ", ".join(f"{k}={v}" for k, v in sorted(combo.items()))
        print(f"  [{idx}/{len(combos)}] {cs} -> train {m.get('trades', 0)} trades, "
              f"{m.get('expectancy_r', 0)}R", flush=True)
        results.append((combo, m, va))

    report = [f"# Strategy #10 (3-step boring scalp) on STOCKS - {ts}", "",
              "RESEARCH ONLY - does not touch the live/paper trader or arming. 1-minute bars.",
              f"Universe {symbols} - train {s10['train_start']} -> {s10['train_end']} - "
              f"validation {s10['val_start']} -> {val_end} - slippage "
              f"{cfg['costs']['slippage_cents']}c/side - 0.5% risk - shorts w/o borrow fees (noted)",
              "", "## Train grid (all combos)", ""]
    for combo, m, _ in results:
        cs = ", ".join(f"{k}={v}" for k, v in sorted(combo.items()))
        report.append(f"- {cs}: {m.get('trades', 0)} trades, {m.get('expectancy_r', 0)}R, "
                      f"PF {m.get('profit_factor', 0)}")
    report.append("")

    eligible = [r for r in results if r[1].get("trades", 0) >= s10["min_train_trades"]]
    if not eligible:
        verdict_line = f"SKIP - no combo reached {s10['min_train_trades']} train trades"
        report += [f"## Verdict: {verdict_line}", ""]
        slack_body = [verdict_line]
    else:
        eligible.sort(key=lambda r: r[1]["expectancy_r"], reverse=True)
        best_combo, best_train, best_va = eligible[0]
        vm = metrics.summarize(best_va)
        cs = ", ".join(f"{k}={v}" for k, v in sorted(best_combo.items()))
        if vm.get("trades", 0) == 0:
            verdict_line = f"FAIL - winner {cs} produced 0 validation trades"
            report += [f"## Verdict: {verdict_line}", ""]
            slack_body = [verdict_line]
        else:
            verdict, why = metrics.gate_verdict(vm, gate)
            wf = s10.get("walkforward", {}) or {}
            wf_pos, wf_tot, wf_per = walk_forward(best_va, int(wf.get("folds", 4)))
            wf_frac = wf_pos / wf_tot if wf_tot else 0.0
            wf_ok = wf_tot > 0 and wf_frac >= float(wf.get("min_positive_frac", 0.6))
            if verdict == "PASS" and not wf_ok:
                verdict = "FAIL"
                extra = f"walk-forward only {wf_pos}/{wf_tot} folds positive"
                why = extra if why == "all gate checks met" else f"{why}; {extra}"
            weak = verdict == "PASS" and best_train["expectancy_r"] < train_floor
            overfit = best_train["expectancy_r"] >= gate["min_expectancy_r"] and vm["expectancy_r"] < 0
            label = "WEAK PASS" if weak else verdict
            sens = []
            for sc in s10.get("slippage_sensitivity_cents", []):
                cfg_s = {**cfg, "costs": {**cfg["costs"], "slippage_cents": sc}}
                _, va_s = split_trades(run_combo(bars, best_combo, cfg_s), train_end, val_start)
                sens.append(f"{sc}c -> {metrics.summarize(va_s).get('expectancy_r', 0)}R")
            report += [
                f"## Verdict: {label}" + ("  ** OVERFIT SIGNATURE" if overfit else ""),
                f"- winner: {cs}",
                f"- train: {best_train['trades']} trades, {best_train['expectancy_r']}R, "
                f"PF {best_train['profit_factor']}",
                f"- validation: {vm['trades']} trades, win {vm['win_rate']}%, {vm['expectancy_r']}R "
                f"(${vm['expectancy_usd']}/trade), PF {vm['profit_factor']}, "
                f"{vm['quarters_positive']}/{vm['quarters_total']} quarters+, maxDD ${vm['max_drawdown']:,}",
                f"- slippage sensitivity: {' | '.join(sens)}",
                f"- walk-forward: {wf_pos}/{wf_tot} folds positive "
                f"(per-fold R: {', '.join(f'{r:+.3f}' for r in wf_per)})",
                f"- gate: {why}", ""]
            slack_body = [
                f"winner {cs}",
                f"train {best_train['expectancy_r']:+}R ({best_train['trades']}t) -> "
                f"val {vm['expectancy_r']:+}R (PF {vm['profit_factor']}, {vm['trades']}t) -> *{label}*"
                + (" (overfit!)" if overfit else ""),
                f"walk-forward {wf_pos}/{wf_tot} folds+ | slippage {' | '.join(sens)}"]

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out_dir / f"strategy10_{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    all_trades = run_combo(bars, eligible[0][0], cfg) if eligible else []
    if all_trades:
        pd.DataFrame([t.__dict__ for t in all_trades]).to_csv(
            out_dir / f"trades_strategy10_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv", index=False)
    print(f"report written: reports/strategy10_{stamp}.md", flush=True)

    header = (f"*[BACKTEST-S10]* {ts} - RESEARCH ONLY, does not touch the trader\n"
              f"Peter's 3-step boring scalp on stocks {symbols}, 1m break-and-retest, "
              "9/21 EMA dir + PDH/PDL + 5m OR, swing-trail, 0.5% risk")
    footer = f"Full detail: reports/strategy10_{stamp}.md"
    slackbot.post("\n\n".join([header] + slack_body + [footer]))


if __name__ == "__main__":
    run()
