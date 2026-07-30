"""TSMOM diagnostic: is the FAIL real, or did my roll logic inject noise? RESEARCH ONLY.

One data pull, three answers:
  1. reproduce the naive-roll result (the FAIL) and re-run with a clean SMOOTH roll,
  2. per-market artifact scan (annualized vol + biggest single-day move) - a roll bug
     shows up as absurd vol / >20% daily jumps,
  3. cache both roll-adjusted price panels to data/ so future runs cost $0.
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from src.backtest import tsmom, futures_daily
except Exception:
    import tsmom, futures_daily

ROOT = Path(__file__).resolve().parent.parent.parent


def artifact_scan(panel):
    rets = panel.pct_change()
    out = {}
    for m in panel.columns:
        r = rets[m].dropna()
        out[m] = {"ann_vol": round(float(r.std()*np.sqrt(252)), 3),
                  "max_abs_day": round(float(r.abs().max()), 3)}
    return out


def evaluate_panel(panel, cfg):
    ts = cfg["tsmom"]
    split = pd.to_datetime(ts["oos_start"])
    oos = panel[panel.index >= split]
    best, best_s = None, -9
    for lb in ts["lookbacks"]:
        net, _ = tsmom.backtest(panel[panel.index < split], lookback=int(lb),
                                vol_window=int(ts.get("vol_window", 60)),
                                target_vol=float(ts.get("target_vol", 0.10)),
                                cost_per_turnover=float(ts.get("cost_per_turnover", 0.0)))
        s = tsmom.metrics(net)["sharpe"]
        if s > best_s:
            best, best_s = int(lb), s
    net_oos, _ = tsmom.backtest(oos, lookback=best, vol_window=int(ts.get("vol_window", 60)),
                                target_vol=float(ts.get("target_vol", 0.10)),
                                cost_per_turnover=float(ts.get("cost_per_turnover", 0.0)))
    return best, tsmom.metrics(net_oos)


def run():
    from src import slackbot
    cfg = _cfg()
    ts = cfg["tsmom"]
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        raw = futures_daily.fetch_raw(ts["universe"], cfg)
    except Exception as e:
        slackbot.post(f"[TSMOM-DIAG] {ts_str} FAILED loading data: {e}"); return

    results = {}
    panels = {}
    for roll in ("naive", "smooth"):
        panel = futures_daily.build_panel(raw, roll, int(ts.get("min_roll_days", 3)))
        panels[roll] = panel
        lb, m = evaluate_panel(panel, cfg)
        results[roll] = (lb, m)
        # cache each panel so future runs are free
        (ROOT / "data").mkdir(exist_ok=True)
        panel.to_csv(ROOT / "data" / f"tsmom_prices_{roll}.csv")

    scan = artifact_scan(panels["naive"])
    noisy = sorted(scan.items(), key=lambda kv: kv[1]["max_abs_day"], reverse=True)[:6]

    L = [f"# TSMOM diagnostic - {ts_str}", "", "RESEARCH ONLY - is the FAIL real or a roll artifact?", ""]
    for roll in ("naive", "smooth"):
        lb, m = results[roll]
        L += [f"## {roll} roll (lookback {lb}d)",
              f"- OOS Sharpe {m['sharpe']} | ann {m['ann_return']:.1%} | ann vol {m['ann_vol']:.1%} | "
              f"maxDD {m['max_drawdown']:.1%}", ""]
    L += ["## Per-market artifact scan (naive roll) - biggest single-day moves",
          "(a healthy diversified daily future is well under ~10%/day; >20% = roll/data artifact)"]
    for mkt, d in noisy:
        L.append(f"- {mkt}: max 1-day move {d['max_abs_day']:.0%}, ann vol {d['ann_vol']:.0%}")
    (ROOT / "reports").mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (ROOT / "reports" / f"tsmom_diag_{stamp}.md").write_text("\n".join(L), encoding="utf-8")

    nlb, nm = results["naive"]; slb, sm = results["smooth"]
    worst = noisy[0]
    verdict = ("roll artifact likely - clean roll changes the answer materially"
               if (sm["sharpe"] - nm["sharpe"]) > 0.3 or worst[1]["max_abs_day"] > 0.20
               else "looks REAL - clean roll ~ same, no artifact markets; the strategy just didn't work here")
    slackbot.post(
        f"*[TSMOM-DIAG]* {ts_str} RESEARCH ONLY\n"
        f"naive roll: Sharpe {nm['sharpe']} maxDD {nm['max_drawdown']:.0%}\n"
        f"smooth roll: Sharpe {sm['sharpe']} maxDD {sm['max_drawdown']:.0%}\n"
        f"worst 1-day move: {worst[0]} {worst[1]['max_abs_day']:.0%}\n"
        f"read: {verdict}\nprices cached to data/ (future runs $0). Detail: reports/tsmom_diag_{stamp}.md")


def _cfg():
    import yaml
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    run()
