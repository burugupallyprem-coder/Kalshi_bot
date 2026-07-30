"""TSMOM backtest orchestration + pre-registered gate. RESEARCH ONLY.

Picks the lookback on TRAIN, judges ONCE on out-of-sample, walk-forward across OOS,
and a cost-sensitivity check. `evaluate(prices, cfg)` is data-agnostic and offline-
testable; run() wires in the Databento daily loader + Slack.
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from src.backtest import tsmom
except Exception:                      # allow standalone import in tests
    import tsmom

ROOT = Path(__file__).resolve().parent.parent.parent


def _fold_sharpes(net, n_folds):
    r = pd.Series(net).dropna()
    if r.empty:
        return []
    idx = np.array_split(np.arange(len(r)), n_folds)
    return [tsmom.metrics(r.iloc[part])["sharpe"] for part in idx if len(part) > 5]


def evaluate(prices, cfg):
    ts = cfg["tsmom"]
    gate = ts["gate"]
    vw = int(ts.get("vol_window", 60))
    tv = float(ts.get("target_vol", 0.10))
    cost = float(ts.get("cost_per_turnover", 0.0))
    split = pd.to_datetime(ts["oos_start"])
    train = prices[prices.index < split]
    oos = prices[prices.index >= split]

    # choose lookback on TRAIN only
    scored = []
    for lb in ts["lookbacks"]:
        net, _ = tsmom.backtest(train, lookback=int(lb), vol_window=vw, target_vol=tv,
                                cost_per_turnover=cost)
        scored.append((int(lb), tsmom.metrics(net)["sharpe"]))
    scored.sort(key=lambda x: x[1], reverse=True)
    best_lb = scored[0][0]

    # judge ONCE on OOS
    net_oos, _ = tsmom.backtest(oos, lookback=best_lb, vol_window=vw, target_vol=tv,
                                cost_per_turnover=cost)
    m = tsmom.metrics(net_oos)
    folds = _fold_sharpes(net_oos, int(gate.get("wf_folds", 4)))
    wf_pos = sum(1 for s in folds if s > 0)
    # cost sensitivity
    sens = {}
    for c in ts.get("cost_sensitivity", []):
        n2, _ = tsmom.backtest(oos, lookback=best_lb, vol_window=vw, target_vol=tv, cost_per_turnover=c)
        sens[c] = tsmom.metrics(n2)["sharpe"]

    reasons = []
    if m["sharpe"] < gate["min_sharpe"]:
        reasons.append(f"OOS Sharpe {m['sharpe']} < {gate['min_sharpe']}")
    if folds and wf_pos / len(folds) < gate.get("min_wf_frac", 0.6):
        reasons.append(f"walk-forward {wf_pos}/{len(folds)} folds positive")
    if m["max_drawdown"] < -abs(gate.get("max_drawdown", 1.0)):
        reasons.append(f"maxDD {m['max_drawdown']} worse than {-abs(gate['max_drawdown'])}")
    verdict = "PASS" if not reasons else "FAIL"
    return {"verdict": verdict, "why": "; ".join(reasons) or "all gate checks met",
            "best_lookback": best_lb, "train_scores": scored, "oos": m,
            "wf": (wf_pos, len(folds), folds), "sens": sens,
            "yearly": tsmom.yearly(net_oos)}


def build_report(res, cfg, ts_str):
    ts = cfg["tsmom"]
    m = res["oos"]; wp, wt, folds = res["wf"]
    L = [f"# TSMOM (diversified trend-following) - {ts_str}", "",
         "RESEARCH ONLY - the one futures approach with real evidence (MOP 2012). "
         "Does not touch the live bot.",
         f"universe ({len(ts['universe'])}): {ts['universe']}",
         f"train < {ts['oos_start']} -> chose lookback; OOS >= {ts['oos_start']} judged once",
         f"target vol {ts.get('target_vol')} | cost/turnover {ts.get('cost_per_turnover')}", "",
         f"## OOS verdict: **{res['verdict']}**  (lookback={res['best_lookback']}d)",
         f"- Sharpe {m['sharpe']} | ann return {m['ann_return']:.1%} | ann vol {m['ann_vol']:.1%} | "
         f"maxDD {m['max_drawdown']:.1%} | hit {m['hit_rate']}",
         f"- walk-forward: {wp}/{wt} folds positive (Sharpes: {folds})",
         f"- cost sensitivity (Sharpe): {res['sens']}",
         f"- gate: {res['why']}", "",
         "## OOS return by year", ""]
    for y, r in res["yearly"].items():
        L.append(f"- {y}: {r:+.1%}")
    L += ["", "## Train lookback scan (Sharpe)"]
    for lb, s in res["train_scores"]:
        L.append(f"- {lb}d: {s}")
    return "\n".join(L)


def run():
    from src import slackbot
    from src.backtest import futures_daily
    cfg = _load_cfg()
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        prices = futures_daily.load(cfg["tsmom"]["universe"], cfg)
    except Exception as e:
        slackbot.post(f"[TSMOM] {ts_str} FAILED loading data: {e}"); return
    res = evaluate(prices, cfg)
    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out / f"tsmom_{stamp}.md").write_text(build_report(res, cfg, ts_str), encoding="utf-8")
    m = res["oos"]; wp, wt, _ = res["wf"]
    note = ("Cleared the gate on out-of-sample data - a genuine (modest) trend edge. "
            "Earns a paper trial, NOT live/prop. " if res["verdict"] == "PASS" else
            "Did not clear the gate. Honest stop. ")
    slackbot.post(
        f"*[TSMOM]* {ts_str} - diversified trend-following, RESEARCH ONLY\n"
        f"OOS Sharpe {m['sharpe']} | ann {m['ann_return']:.1%} | maxDD {m['max_drawdown']:.1%} | "
        f"wf {wp}/{wt} -> *{res['verdict']}* (lookback {res['best_lookback']}d)\n"
        f"{note}Full detail: reports/tsmom_{stamp}.md")


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    run()
