"""Stage 1 diagnostic: is the futures-proxy WEAK PASS real, or a lucky window?

RESEARCH ONLY. Re-scores the pre-registered winner of one strategy on the index
proxy - NO new validation debt, no new parameter search. Same scrutiny you ran on
the scalp: bootstrap CI on validation expectancy, and breakdowns by symbol,
quarter, direction, and exit reason. If the edge is carried by one symbol, a
handful of trades, or the short side, it's noise - and we've spent $0 to learn it.

Target strategy: config.futures_proxy.diag_strategy (default: momentum).
Run: python -m src.backtest.futures_proxy_diag
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src import data as data_mod
from src import slackbot
from src.backtest import futures_proxy, metrics, research
from src.backtest.futures_proxy import STRAT_MODS

ROOT = Path(__file__).resolve().parent.parent.parent


def bootstrap_ci(r_values, n=2000, seed=0):
    r = np.asarray([x for x in r_values], dtype=float)
    if len(r) == 0:
        return 0.0, 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1)
    return (float(r.mean()), float(np.percentile(means, 5)),
            float(np.percentile(means, 95)), float((means > 0).mean() * 100))


def _breakdown(df, col):
    out = []
    for key, g in df.groupby(col):
        out.append(f"    {key}: {len(g)} trades, {g['r_multiple'].mean():+.3f}R, "
                   f"win {round((g['pnl'] > 0).mean() * 100)}%")
    return out


def run():
    cfg = research.load_config()
    fp = cfg["futures_proxy"]
    cfg["universe"] = fp["universe"]
    rs = cfg["research"]
    name = fp.get("diag_strategy", "momentum")
    strat = STRAT_MODS[name]
    val_end = rs.get("val_end") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    bars = data_mod.fetch_bars(fp["universe"], rs["train_start"], val_end,
                               timeframe=cfg["backtest"]["timeframe"], feed=cfg["backtest"]["feed"])
    if bars.empty:
        slackbot.post(f"[FUTURES-PROXY-DIAG] {ts} FAILED: no bars from Alpaca."); return
    bars = data_mod.rth_only(bars)

    # re-derive the SAME winner the proxy chose (no new search)
    r = futures_proxy.evaluate_strategy(bars, cfg, name)
    if r["combo"] is None:
        slackbot.post(f"[FUTURES-PROXY-DIAG] {ts} {name}: no eligible winner to diagnose."); return
    base = dict(cfg["strategies"].get(name, {}))
    best_params = {**base, **r["combo"]}

    val_start = pd.to_datetime(rs["val_start"]).date()
    val_groups = research.day_groups(bars[bars["date"] >= val_start])
    val_ctx = research.build_context(val_groups, cfg)
    trades = research.run_config(val_groups, strat, best_params, cfg, name, val_ctx)
    m = metrics.summarize(trades)
    df = m["df"]
    df["quarter"] = pd.PeriodIndex(pd.to_datetime(df["date"]), freq="Q").astype(str)

    point, lo, hi, pgt0 = bootstrap_ci(df["r_multiple"])
    report = [f"# Futures-proxy diagnostic: {name} - {ts}", "",
              "RESEARCH ONLY - re-scores the pre-registered winner, no new validation debt.",
              f"winner: {', '.join(f'{k}={v}' for k, v in sorted(r['combo'].items()))}",
              f"validation: {m['trades']} trades, {m['expectancy_r']}R, PF {m['profit_factor']}", "",
              "## Bootstrap on validation expectancy_R (2000 resamples)",
              f"- point {point:+.3f}R | 90% CI [{lo:+.3f}, {hi:+.3f}] | P(mean>0) = {pgt0:.1f}%",
              f"- read: {'CI clears zero - edge unlikely to be pure luck' if lo > 0 else 'CI INCLUDES zero - edge is NOT distinguishable from luck'}",
              "", "## Validation breakdown (descriptive - do NOT fit filters to this)",
              "  by symbol:"] + _breakdown(df, "symbol") + \
             ["  by quarter:"] + _breakdown(df, "quarter") + \
             ["  by direction:"] + _breakdown(df, "side") + \
             ["  by exit reason:"] + _breakdown(df, "exit_reason")

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out / f"futures_proxy_diag_{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    verdict = ("survives: bootstrap CI clears zero" if lo > 0
               else "FRAGILE: bootstrap CI includes zero - not distinguishable from luck")
    slackbot.post(
        f"*[FUTURES-PROXY-DIAG]* {ts} - {name} WEAK-PASS scrutiny, RESEARCH ONLY\n"
        f"val {m['trades']}t {m['expectancy_r']:+}R PF {m['profit_factor']} | "
        f"bootstrap {point:+.3f}R CI [{lo:+.3f}, {hi:+.3f}] P(>0)={pgt0:.0f}%\n"
        f"{verdict}\nFull detail: reports/futures_proxy_diag_{stamp}.md")
    print(f"diag report: reports/futures_proxy_diag_{stamp}.md")


if __name__ == "__main__":
    run()
