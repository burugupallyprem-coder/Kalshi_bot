"""Indicator alpha-search (daily swing). RESEARCH ONLY.

Tests the indicators the crowd actually trades -- Bollinger Bands, RSI, MACD, Fibonacci
retracement -- the way they are actually used (daily bars, multi-day holds), but with
OUR rigor instead of Pine Script's optimistic backtester:
  B) expand a small, pre-declared grid of indicator variants into a batch;
  A) score each variant's net daily return series, then apply the Deflated Sharpe Ratio
     across the batch (a raw "pass" among N tries is meaningless);
  C) forward-test the survivor on a fresh held-out window it never saw.
Only a candidate that clears BOTH gates pings Slack. Nothing deploys.

Costs modelled explicitly (cost_bps per unit of position turnover). No-lookahead: the
position at day t is applied to the t->t+1 return (pos.shift(1)), and every indicator
is causal. `expand_indicators` and `strategy_returns` are unit-tested offline.
"""

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from src.backtest import multiple_testing as MT
    from src.backtest.alpha_search import evaluate_search, forward_verdict
    from src.backtest.overnight_search import daily_frames
    from src.backtest import indicators as IND
except Exception:
    import multiple_testing as MT
    from alpha_search import evaluate_search, forward_verdict
    from overnight_search import daily_frames
    import indicators as IND

ROOT = Path(__file__).resolve().parent.parent.parent


def expand_indicators(cfg):
    """Per-indicator grids -> a flat batch of concrete variants."""
    out = []
    for ind, grid in cfg["indicator_search"]["grid"].items():
        keys = sorted(grid)
        for combo in itertools.product(*(grid[k] for k in keys)):
            params = dict(zip(keys, combo))
            name = f"{ind}[" + ", ".join(f"{k}={v}" for k, v in params.items()) + "]"
            out.append({"name": name, "indicator": ind, "params": params})
    return out


def _position(close, variant):
    ind, p = variant["indicator"], variant["params"]
    if ind == "bollinger":
        return IND.bollinger_pos(close, int(p.get("period", 20)), float(p.get("k", 2.0)),
                                 p.get("mode", "revert"))
    if ind == "rsi":
        return IND.rsi_pos(close, int(p.get("period", 14)), float(p.get("low", 30)),
                           float(p.get("high", 70)))
    if ind == "macd":
        return IND.macd_pos(close, int(p.get("fast", 12)), int(p.get("slow", 26)),
                            int(p.get("signal", 9)))
    if ind == "fib":
        return IND.fib_pos(close, int(p.get("lookback", 20)), float(p.get("retr", 0.5)))
    raise ValueError(f"unknown indicator {ind}")


def strategy_returns(frames, variant, cfg, start, end):
    """Pooled net daily returns for one variant across all symbols, over [start, end]."""
    cost = float(cfg["indicator_search"].get("cost_bps", 5)) / 10000.0
    rets = []
    for sym, df in frames.items():
        close = df.set_index("date")["close"].astype(float)
        pos = _position(close, variant)
        r = close.pct_change().fillna(0.0)
        turn = (pos - pos.shift(1)).abs().fillna(0.0)
        strat = pos.shift(1).fillna(0.0) * r - turn * cost   # enter next day; costs on turnover
        for d, v in strat.items():
            if start <= d <= end and pos.shift(1).get(d, 0.0) != 0.0:
                rets.append(float(v))
    return rets


def _quarantine(name, variant, search, forward):
    q = ROOT / "data" / "quarantine_indicator.json"
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
    ic = cfg["indicator_search"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fwd_end = ic.get("forward_end") or (pd.Timestamp.now("UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    bars = data_mod.fetch_bars(ic["universe"], ic["search_start"], fwd_end,
                               timeframe="1Day", feed=cfg["backtest"]["feed"])
    if bars.empty:
        slackbot.post(f"[INDICATORS] {ts} FAILED: no daily bars from Alpaca."); return
    frames = daily_frames(bars)
    s_start = pd.to_datetime(ic["search_start"]).date()
    s_end = pd.to_datetime(ic["search_end"]).date()
    f_start = pd.to_datetime(ic["forward_start"]).date()
    fwd_e = pd.to_datetime(fwd_end).date()

    variants = expand_indicators(cfg)
    trials = [{"name": v["name"], "r_multiples": strategy_returns(frames, v, cfg, s_start, s_end)}
              for v in variants]
    res = evaluate_search(trials, float(ic.get("dsr_threshold", 0.95)), int(ic.get("min_trades", 60)))

    fwd = None
    if res["survivor"]:
        v = next(x for x in variants if x["name"] == res["best"]["name"])
        fret = strategy_returns(frames, v, cfg, f_start, fwd_e)
        fwd = forward_verdict(fret, int(ic.get("forward_min_trades", 30)))
        _quarantine(v["name"], v, res, fwd)

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    L = [f"# Indicator search (daily swing) - {ts}", "",
         "RESEARCH ONLY. Classic indicators (native Python, no Pine Script), same DSR + forward gates.",
         f"search {ic['search_start']}->{ic['search_end']} | forward {ic['forward_start']}->{fwd_end}",
         f"variants tested: **{res['n_trials']}** | DSR threshold {res['threshold']} | cost {ic.get('cost_bps',5)}bps/turn",
         f"best: {res['best']['name'] if res['best'] else '-'} | search Sharpe "
         f"{res['best']['sharpe'] if res['best'] else 0} ({res['best']['trades'] if res['best'] else 0} days)",
         f"luck bar (expected max Sharpe under null): {res['expected_max_null']}",
         f"**Deflated Sharpe: {res['dsr']}**"]
    if res["survivor"] and fwd:
        L.append(f"forward test: {'CONFIRMED' if fwd['confirmed'] else 'FAILED'} "
                 f"(Sharpe {fwd['sharpe']}, expectancy {fwd['expectancy_r']}, {fwd['trades']} days)")
    L += ["", "## All variants by search Sharpe"]
    for s in sorted(res["all"], key=lambda x: x["sharpe"], reverse=True):
        L.append(f"- {s['name']}: {s['sharpe']} ({s['trades']} days)")
    (out / f"indicator_search_{stamp}.md").write_text("\n".join(L), encoding="utf-8")

    if res["survivor"] and fwd and fwd["confirmed"]:
        slackbot.post(
            f"*[INDICATORS] CONFIRMED CANDIDATE* {ts}\n"
            f"'{res['best']['name']}' cleared BOTH gates: deflated Sharpe {res['dsr']} across "
            f"{res['n_trials']} variants, AND positive on fresh forward data "
            f"(Sharpe {fwd['sharpe']}, {fwd['expectancy_r']}, {fwd['trades']} days).\n"
            f"Quarantined for your review - NOT deployed.\nDetail: reports/indicator_search_{stamp}.md")
    elif res["survivor"]:
        slackbot.post(
            f"[INDICATORS] {ts} - a variant passed the deflated-Sharpe bar but FAILED the forward "
            f"test. Correctly discarded. {res['n_trials']} tested.\nDetail: reports/indicator_search_{stamp}.md")
    else:
        b = res["best"] or {}
        slackbot.post(
            f"[INDICATORS] {ts} - {res['n_trials']} indicator variants tested, no edge "
            f"(best DSR {res['dsr']} < {res['threshold']}). "
            f"Best '{b.get('name','-')}': raw Sharpe {b.get('sharpe',0)} over {b.get('trades',0)} days. "
            f"Still searching.\nDetail: reports/indicator_search_{stamp}.md")


if __name__ == "__main__":
    run()
