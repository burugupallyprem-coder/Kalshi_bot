"""Strategy #10 (stocks) rigorous DIAGNOSTIC - RESEARCH ONLY, touches nothing live.

The stock scalp came back WEAK PASS (validation +0.098R / PF 1.172 / 2070 trades /
walk-forward 4/4, but TRAIN edge ~0). This module dissects that result the same
way the gold diagnostic did, and adds two stress tests that matter specifically
for a thin-margin WEAK PASS:

  1. BREAKDOWN of the winner's trades by symbol, quarter, exit reason, level
     family (prev-day level vs 5-min opening range) and direction.
       - TRAIN breakdown  = fair game for forming new filter hypotheses.
       - VALIDATION breakdown = DESCRIPTIVE ONLY. It is printed so you can SEE
         where the edge landed, but designing a filter from it is selecting on
         validation (p-hacking) - explicitly flagged, do not do it.
  2. GROSS vs NET on both windows (how much the 1c/side slippage eats).
  3. BOOTSTRAP confidence interval on the VALIDATION expectancy_R: resample the
     validation trades' R-multiples with replacement to get a 90% CI and the
     fraction of resamples above zero. This answers "is +0.098R distinguishable
     from luck?" beyond the single point estimate - the check a thin PF needs.

No NEW validation debt is spent: it re-scores the same pre-registered winner and
only re-describes trades already counted. Engine, winner-selection and honesty
rules are IMPORTED unchanged from strategy10_scalp.

Run: python -m src.backtest.strategy10_scalp_diag
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src import data as data_mod
from src import slackbot
from src.backtest import metrics
from src.backtest.strategy10_scalp import (expand_grid, load_config, run_combo,
                                           split_trades)

ROOT = Path(__file__).resolve().parent.parent.parent


def _level_family(reason):
    r = reason or ""
    if r.startswith("pdh") or r.startswith("pdl"):
        return "prev_day_level"
    if r.startswith("orh") or r.startswith("orl"):
        return "opening_range"
    return "other"


def _grp(df, keyfn, label):
    if df.empty:
        return [f"  by {label}: (no trades)"]
    g = df.copy()
    g["_k"] = g.apply(keyfn, axis=1) if callable(keyfn) else g[keyfn]
    out = [f"  by {label}:"]
    for k, sub in g.groupby("_k"):
        wins = (sub["r_multiple"] > 0).mean() * 100
        pf_den = -sub.loc[sub["r_multiple"] <= 0, "r_multiple"].sum()
        pf = (sub.loc[sub["r_multiple"] > 0, "r_multiple"].sum() / pf_den) if pf_den > 0 else float("inf")
        out.append(f"    {k}: {len(sub)} trades, {sub['r_multiple'].mean():+.3f}R, "
                   f"win {wins:.0f}%, PF {pf:.2f}")
    return out


def _trade_breakdown(trades, label):
    if not trades:
        return [f"{label}: (no trades)"], 0, 0
    tdf = pd.DataFrame([t.__dict__ for t in trades])
    tdf["date"] = pd.to_datetime(tdf["date"])
    tdf["quarter"] = pd.PeriodIndex(tdf["date"], freq="Q").astype(str)
    tdf["dir"] = tdf["signal_reason"].str.contains("long").map({True: "long", False: "short"})
    lines = [label + ":"]
    lines += _grp(tdf, "symbol", "symbol")
    lines += _grp(tdf, "quarter", "quarter")
    lines += _grp(tdf, lambda r: r["exit_reason"], "exit reason")
    lines += _grp(tdf, lambda r: _level_family(r["signal_reason"]), "level family")
    lines += _grp(tdf, "dir", "direction")
    pos_q = int((tdf.groupby("quarter")["r_multiple"].mean() > 0).sum())
    tot_q = int(tdf["quarter"].nunique())
    return lines, pos_q, tot_q


def bootstrap_ci(r_values, n=2000, seed=0, lo=5, hi=95):
    """(low_pct, high_pct, frac_above_zero, point_mean) of the resampled mean R."""
    r = np.asarray(list(r_values), dtype=float)
    if r.size == 0:
        return 0.0, 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n, r.size), replace=True).mean(axis=1)
    return (float(np.percentile(means, lo)), float(np.percentile(means, hi)),
            float((means > 0).mean()), float(r.mean()))


def _top_bottom_symbols(trades, k=3):
    if not trades:
        return "n/a"
    df = pd.DataFrame([t.__dict__ for t in trades])
    per = df.groupby("symbol")["r_multiple"].mean().sort_values(ascending=False)
    top = ", ".join(f"{s} {r:+.3f}R" for s, r in per.head(k).items())
    bot = ", ".join(f"{s} {r:+.3f}R" for s, r in per.tail(k).items())
    return f"best[{top}] worst[{bot}]"


def run():
    cfg = load_config()
    s10 = cfg["strategy10"]
    cfg["universe"] = s10["universe"]
    val_end = s10.get("val_end") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    symbols = s10["universe"]
    train_end = pd.to_datetime(s10["train_end"]).date()
    val_start = pd.to_datetime(s10["val_start"]).date()

    print(f"downloading {len(symbols)} symbols {s10['timeframe']}", flush=True)
    bars = data_mod.fetch_bars(symbols, s10["train_start"], val_end,
                               timeframe=s10["timeframe"], feed=s10["feed"])
    if bars.empty:
        slackbot.post(f"[BACKTEST-S10-DIAG] {ts} - FAILED: no bars from Alpaca.")
        return
    bars = data_mod.rth_only(bars)
    print(f"bars: {len(bars):,} rows", flush=True)

    # re-select the SAME train winner the backtest used
    scored = []
    for combo in expand_grid(s10["grids"]):
        tr, va = split_trades(run_combo(bars, combo, cfg), train_end, val_start)
        scored.append((combo, metrics.summarize(tr), tr, va))
    eligible = [s for s in scored if s[1].get("trades", 0) >= s10["min_train_trades"]]
    if not eligible:
        slackbot.post(f"[BACKTEST-S10-DIAG] {ts} - no eligible winner to dissect.")
        return
    eligible.sort(key=lambda s: s[1]["expectancy_r"], reverse=True)
    combo, mtr, tr, va = eligible[0]
    combo_str = ", ".join(f"{k}={v}" for k, v in sorted(combo.items()))
    vmetrics = metrics.summarize(va)

    # gross (zero slippage) on both windows
    cfg0 = {**cfg, "costs": {**cfg["costs"], "slippage_cents": 0.0}}
    tr0, va0 = split_trades(run_combo(bars, combo, cfg0), train_end, val_start)
    m_tr0, m_va0 = metrics.summarize(tr0), metrics.summarize(va0)

    lo, hi, frac_pos, pt = bootstrap_ci([t.r_multiple for t in va])

    report = [f"# Strategy #10 (stocks) rigorous diagnostic - {ts}", "",
              "RESEARCH ONLY - re-scores the pre-registered winner; no new validation debt.",
              f"winner: {combo_str}",
              f"NET   train {mtr['trades']}t {mtr['expectancy_r']:+.3f}R PF {mtr['profit_factor']} | "
              f"validation {vmetrics['trades']}t {vmetrics['expectancy_r']:+.3f}R PF {vmetrics['profit_factor']}",
              f"GROSS train {m_tr0.get('trades',0)}t {m_tr0.get('expectancy_r',0):+.3f}R | "
              f"validation {m_va0.get('trades',0)}t {m_va0.get('expectancy_r',0):+.3f}R "
              f"(slippage eats {m_va0.get('expectancy_r',0)-vmetrics['expectancy_r']:+.3f}R on val)",
              "",
              "## Bootstrap on VALIDATION expectancy_R (2000 resamples, seed 0)",
              f"- point {pt:+.3f}R | 90% CI [{lo:+.3f}R, {hi:+.3f}R] | "
              f"P(mean>0) = {frac_pos*100:.1f}%",
              f"- read: {'CI clears zero - edge is unlikely to be pure luck' if lo > 0 else 'CI includes zero - edge NOT distinguishable from luck at 90%'}",
              ""]
    tr_lines, _, _ = _trade_breakdown(tr, "## TRAIN breakdown (fair game for new filter ideas)")
    va_lines, _, _ = _trade_breakdown(va, "## VALIDATION breakdown (DESCRIPTIVE ONLY - do NOT design filters from this)")
    report += tr_lines + [""] + va_lines + [""]

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out_dir / f"strategy10diag_{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    print(f"report written: reports/strategy10diag_{stamp}.md", flush=True)

    ci_read = "clears 0" if lo > 0 else "includes 0"
    header = (f"*[BACKTEST-S10-DIAG]* {ts} - RESEARCH ONLY, no new val debt\n"
              f"Dissecting the WEAK PASS stock scalp (winner {combo_str})")
    body = [
        f"val {vmetrics['expectancy_r']:+.3f}R net vs {m_va0.get('expectancy_r',0):+.3f}R gross "
        f"({vmetrics['trades']} trades)",
        f"bootstrap 90% CI [{lo:+.3f}, {hi:+.3f}]R, P(>0)={frac_pos*100:.0f}% -> CI {ci_read}",
        f"val by symbol: {_top_bottom_symbols(va)}"]
    footer = f"Full detail: reports/strategy10diag_{stamp}.md"
    slackbot.post("\n\n".join([header] + body + [footer]))


if __name__ == "__main__":
    run()
