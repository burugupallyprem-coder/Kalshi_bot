"""Overnight (close-to-open) alpha-search harness. RESEARCH ONLY.

A DIFFERENT BOARD from the intraday engine: it holds from today's CLOSE to tomorrow's
OPEN and captures the documented overnight-drift anomaly. It reuses the EXACT same
multiple-testing machinery as the intraday search:
  B) expand a small, pre-declared, economically-motivated grid of variants (side x
     condition) into a batch;
  A) score each variant's net close->open return series, then apply the Deflated Sharpe
     Ratio across the batch (a raw "pass" among N tries is meaningless);
  C) forward-test the survivor on a fresh held-out window it never saw.
Only a candidate that clears BOTH gates pings Slack. Nothing deploys.

Costs are modelled explicitly (cost_bps round-trip). No-lookahead: exit uses the NEXT
session's open, entry the current session's close; the condition only reads the current
and prior sessions. `expand_overnight` and `overnight_returns` are unit-tested offline.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from src.backtest import multiple_testing as MT
    from src.backtest.alpha_search import evaluate_search, forward_verdict
except Exception:
    import multiple_testing as MT
    from alpha_search import evaluate_search, forward_verdict

ROOT = Path(__file__).resolve().parent.parent.parent


def expand_overnight(cfg):
    """side x condition grid -> a flat batch of concrete variants."""
    grid = cfg["overnight_search"]["grid"]
    out = []
    for side in grid["side"]:
        for cond in grid["cond"]:
            out.append({"name": f"overnight[side={side}, cond={cond}]",
                        "side": side, "cond": cond})
    return out


def daily_frames(bars):
    """{symbol: rows sorted by date} with a 'date' column added (date objects)."""
    frames = {}
    if bars.empty:
        return frames
    b = bars.copy()
    b["date"] = b["ts"].dt.date
    for sym, g in b.groupby("symbol"):
        frames[sym] = g.sort_values("date").reset_index(drop=True)
    return frames


def spy_regime_up(frames, sma_n):
    """{date: True} when SPY's close that day is above its trailing sma_n-day average."""
    up = {}
    spy = frames.get("SPY")
    if spy is None:
        return up
    closes = spy["close"].tolist()
    dates = spy["date"].tolist()
    for t in range(len(closes)):
        if t < sma_n:
            continue
        sma = sum(closes[t - sma_n:t]) / sma_n
        up[dates[t]] = closes[t] > sma
    return up


def overnight_returns(frames, variant, cfg, start, end, spy_up):
    """Net close->open returns for one variant, over sessions in [start, end]."""
    oc = cfg["overnight_search"]
    cost = float(oc.get("cost_bps", 5)) / 10000.0
    side, cond = variant["side"], variant["cond"]
    rets = []
    for sym, df in frames.items():
        o = df["open"].tolist(); c = df["close"].tolist(); d = df["date"].tolist()
        for t in range(1, len(df) - 1):          # need day t (entry) and t+1 (exit)
            dt = d[t]
            if dt < start or dt > end:
                continue
            if cond == "after_down" and not (c[t] < o[t]):
                continue
            if cond == "after_up" and not (c[t] > o[t]):
                continue
            if cond == "spy_up" and not spy_up.get(dt, False):
                continue
            entry, exit_ = c[t], o[t + 1]
            if entry <= 0:
                continue
            gross = (exit_ - entry) / entry
            r = gross if side == "long" else -gross
            rets.append(r - cost)
    return rets


def _quarantine(name, variant, search, forward):
    q = ROOT / "data" / "quarantine_overnight.json"
    q.parent.mkdir(exist_ok=True)
    try:
        rec = json.loads(q.read_text())
    except Exception:
        rec = []
    rec.append({"found_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "name": name, "variant": variant,
                "search_dsr": search["dsr"], "search_sharpe": search["best"]["sharpe"],
                "forward": forward,
                "status": ("CONFIRMED on fresh data - awaiting your review"
                           if forward["confirmed"] else
                           "DSR survivor but FAILED forward test - discarded")})
    q.write_text(json.dumps(rec, indent=2))


def run():
    import pandas as pd
    from src import data as data_mod, slackbot
    from src.backtest import research
    cfg = research.load_config()
    oc = cfg["overnight_search"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fwd_end = oc.get("forward_end") or (pd.Timestamp.now("UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    syms = list(dict.fromkeys(oc["universe"] + ["SPY"]))   # ensure SPY for regime
    bars = data_mod.fetch_bars(syms, oc["search_start"], fwd_end,
                               timeframe="1Day", feed=cfg["backtest"]["feed"])
    if bars.empty:
        slackbot.post(f"[OVERNIGHT] {ts} FAILED: no daily bars from Alpaca."); return
    frames = daily_frames(bars)
    spy_up = spy_regime_up(frames, int(oc.get("regime_sma", 50)))
    s_end = pd.to_datetime(oc["search_end"]).date()
    f_start = pd.to_datetime(oc["forward_start"]).date()
    fwd_e = pd.to_datetime(fwd_end).date()
    s_start = pd.to_datetime(oc["search_start"]).date()

    variants = expand_overnight(cfg)
    trials = [{"name": v["name"],
               "r_multiples": overnight_returns(frames, v, cfg, s_start, s_end, spy_up)}
              for v in variants]
    res = evaluate_search(trials, float(oc.get("dsr_threshold", 0.95)), int(oc.get("min_trades", 60)))

    fwd = None
    if res["survivor"]:
        v = next(x for x in variants if x["name"] == res["best"]["name"])
        fret = overnight_returns(frames, v, cfg, f_start, fwd_e, spy_up)
        fwd = forward_verdict(fret, int(oc.get("forward_min_trades", 30)))
        _quarantine(v["name"], v, res, fwd)

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    L = [f"# Overnight close->open search - {ts}", "",
         "RESEARCH ONLY. Different board (overnight drift). Same deflated-Sharpe + forward gates.",
         f"search {oc['search_start']}->{oc['search_end']} | forward {oc['forward_start']}->{fwd_end}",
         f"variants tested: **{res['n_trials']}** | DSR threshold {res['threshold']} | cost {oc.get('cost_bps',5)}bps rt",
         f"best: {res['best']['name'] if res['best'] else '-'} | search Sharpe "
         f"{res['best']['sharpe'] if res['best'] else 0} ({res['best']['trades'] if res['best'] else 0} nights)",
         f"luck bar (expected max Sharpe under null): {res['expected_max_null']}",
         f"**Deflated Sharpe: {res['dsr']}**"]
    if res["survivor"] and fwd:
        L.append(f"forward test: {'CONFIRMED' if fwd['confirmed'] else 'FAILED'} "
                 f"(Sharpe {fwd['sharpe']}, expectancy {fwd['expectancy_r']}, {fwd['trades']} nights)")
    L += ["", "## All variants by search Sharpe"]
    for s in sorted(res["all"], key=lambda x: x["sharpe"], reverse=True):
        L.append(f"- {s['name']}: {s['sharpe']} ({s['trades']} nights)")
    (out / f"overnight_search_{stamp}.md").write_text("\n".join(L), encoding="utf-8")

    if res["survivor"] and fwd and fwd["confirmed"]:
        slackbot.post(
            f"*[OVERNIGHT] CONFIRMED CANDIDATE* {ts}\n"
            f"'{res['best']['name']}' cleared BOTH gates: deflated Sharpe {res['dsr']} across "
            f"{res['n_trials']} variants, AND positive on fresh forward data "
            f"(Sharpe {fwd['sharpe']}, {fwd['expectancy_r']}, {fwd['trades']} nights).\n"
            f"Quarantined for your review - NOT deployed.\nDetail: reports/overnight_search_{stamp}.md")
    elif res["survivor"]:
        slackbot.post(
            f"[OVERNIGHT] {ts} - a variant passed the deflated-Sharpe bar but FAILED the forward "
            f"test. Correctly discarded. {res['n_trials']} tested.\nDetail: reports/overnight_search_{stamp}.md")
    else:
        slackbot.post(
            f"[OVERNIGHT] {ts} - {res['n_trials']} variants tested, no edge "
            f"(best DSR {res['dsr']} < {res['threshold']}). Still searching.\n"
            f"Detail: reports/overnight_search_{stamp}.md")


if __name__ == "__main__":
    run()
