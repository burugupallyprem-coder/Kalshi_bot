"""Stage 1: FUTURES EDGE PROXY - do ANY of our signals have edge on the INDEX intraday?

RESEARCH ONLY. Never touches the live/paper trader or the arming kill-switch.

We run each existing signal on the index ETFs that the micro futures track
(SPY->MES, QQQ->MNQ, DIA->MYM, IWM->M2K), through the SAME gate + walk-forward as
everything else, each using its own pre-declared research grid. Logic: if a signal
can't clear the gate on the very index it would trade, a paid futures data feed
will not rescue it.

Signals tested (from config.futures_proxy.strategies):
  - orb           : opening-range breakout (with regime + rel-strength filters)
  - vwap_revert   : intraday mean reversion  <- the interesting one: indices
                    mean-revert far more than single stocks, so a signal that
                    failed on the 20-stock basket may behave differently here.
  - momentum      : trend continuation

Discipline (identical to research.py): grids PRE-DECLARED; winner chosen on TRAIN;
judged ONCE on validation + walk-forward + slippage. WEAK-PASS if train edge ~0.

COSTS: equity cent-slippage stand-in. Real futures costs (tick spread + fees) are
heavier and modeled properly in Stage 2. A positive result here means "worth
paying for real data to confirm", never "done".

Run: python -m src.backtest.futures_proxy
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src import data as data_mod
from src import slackbot
from src.backtest import metrics, research
from src.strategies import momentum, orb, vwap_revert

ROOT = Path(__file__).resolve().parent.parent.parent
STRAT_MODS = {"orb": orb, "vwap_revert": vwap_revert, "momentum": momentum}


def _combo_str(d):
    return ", ".join(f"{k}={v}" for k, v in sorted(d.items()))


def evaluate_strategy(bars, cfg, name):
    """Pick this strategy's TRAIN winner from its pre-declared grid, then judge it
    ONCE on validation + walk-forward + slippage on the index universe."""
    strat = STRAT_MODS[name]
    rs = cfg["research"]
    gate = cfg["gate"]
    grid = rs["grids"][name]
    base = dict(cfg["strategies"].get(name, {}))
    train_end = pd.to_datetime(rs["train_end"]).date()
    val_start = pd.to_datetime(rs["val_start"]).date()
    train_groups = research.day_groups(bars[bars["date"] <= train_end])
    val_groups = research.day_groups(bars[bars["date"] >= val_start])
    train_ctx = research.build_context(train_groups, cfg)
    val_ctx = research.build_context(val_groups, cfg)
    wf = rs.get("walkforward", {}) or {}
    min_train = rs.get("min_train_trades", 150)

    scored = []
    for combo in research.expand_grid(grid):
        params = {**base, **combo}
        tm = metrics.summarize(
            research.run_config(train_groups, strat, params, cfg, name, train_ctx))
        scored.append((params, combo, tm))
    eligible = [x for x in scored if x[2].get("trades", 0) >= min_train]
    if not eligible:
        return {"name": name, "verdict": "SKIP",
                "why": f"no combo reached {min_train} train trades",
                "combo": None, "train": None, "val": None, "wf": (0, 0, []), "sens": []}
    eligible.sort(key=lambda x: x[2].get("expectancy_r", 0.0), reverse=True)
    best_params, best_combo, best_train = eligible[0]

    vm = metrics.summarize(
        research.run_config(val_groups, strat, best_params, cfg, name, val_ctx))
    if vm.get("trades", 0) == 0:
        return {"name": name, "verdict": "FAIL", "why": "0 validation trades",
                "combo": best_combo, "train": best_train, "val": vm, "wf": (0, 0, []), "sens": []}
    verdict, why = metrics.gate_verdict(vm, gate)
    wf_pos, wf_tot, wf_per = research.evaluate_walk_forward(
        val_groups, strat, best_params, cfg, name, int(wf.get("folds", 4)), val_ctx)
    wf_ok = wf_tot > 0 and (wf_pos / wf_tot) >= float(wf.get("min_positive_frac", 0.6))
    if verdict == "PASS" and not wf_ok:
        verdict = "FAIL"
        extra = f"walk-forward only {wf_pos}/{wf_tot} folds positive"
        why = extra if why == "all gate checks met" else f"{why}; {extra}"
    weak = verdict == "PASS" and best_train["expectancy_r"] < rs.get("min_train_expectancy_r", 0.02)
    label = "WEAK PASS" if weak else verdict
    sens = []
    for sc in rs.get("slippage_sensitivity_cents", []):
        cfg_s = {**cfg, "costs": {**cfg["costs"], "slippage_cents": sc}}
        sm = metrics.summarize(
            research.run_config(val_groups, strat, best_params, cfg_s, name, val_ctx))
        sens.append(f"{sc}c -> {sm.get('expectancy_r', 0)}R")
    return {"name": name, "verdict": label, "why": why, "combo": best_combo,
            "train": best_train, "val": vm, "wf": (wf_pos, wf_tot, wf_per), "sens": sens}


def run():
    cfg = research.load_config()
    fp = cfg["futures_proxy"]
    cfg["universe"] = fp["universe"]
    rs = cfg["research"]
    val_end = rs.get("val_end") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pmap = fp["proxy_map"]

    print(f"downloading {fp['universe']} {cfg['backtest']['timeframe']}, "
          f"{rs['train_start']} -> {val_end}", flush=True)
    bars = data_mod.fetch_bars(fp["universe"], rs["train_start"], val_end,
                               timeframe=cfg["backtest"]["timeframe"],
                               feed=cfg["backtest"]["feed"])
    if bars.empty:
        slackbot.post(f"[FUTURES-PROXY] {ts} FAILED: no bars from Alpaca. Check keys/plan.")
        return
    bars = data_mod.rth_only(bars)

    report = [f"# Futures edge PROXY (Stage 1) - {ts}", "",
              "RESEARCH ONLY - does not touch the live trader or arming.",
              f"Index ETFs as micro-futures stand-ins: "
              f"{', '.join(f'{k}->{v}' for k, v in pmap.items())}",
              f"train {rs['train_start']} -> {rs['train_end']} | validation "
              f"{rs['val_start']} -> {val_end} | same gate + walk-forward | "
              f"cent-slippage stand-in (real futures costs = Stage 2)", ""]
    slack = [f"*[FUTURES-PROXY]* {ts} - Stage 1 (index ETFs as MES/MNQ/MYM/M2K), RESEARCH ONLY"]
    any_pass = False

    for name in fp["strategies"]:
        r = evaluate_strategy(bars, cfg, name)
        if r["verdict"] in ("PASS", "WEAK PASS"):
            any_pass = True
        report += [f"## {name}", "", f"Verdict: **{r['verdict']}**"]
        if r["combo"] is not None and r["val"] is not None:
            v, t = r["val"], r["train"]
            wp, wt, wper = r["wf"]
            report += [
                f"- winner: {_combo_str(r['combo'])}",
                f"- train: {t['trades']} trades, {t['expectancy_r']}R, PF {t['profit_factor']}",
                f"- validation: {v['trades']} trades, win {v['win_rate']}%, {v['expectancy_r']}R "
                f"(${v['expectancy_usd']}/trade), PF {v['profit_factor']}, "
                f"{v['quarters_positive']}/{v['quarters_total']} quarters+, maxDD ${v['max_drawdown']:,}",
                f"- walk-forward: {wp}/{wt} folds positive "
                f"(per-fold R: {', '.join(f'{x:+.3f}' for x in wper)})",
                f"- slippage: {' | '.join(r['sens'])}",
                f"- gate: {r['why']}", ""]
            slack.append(f"*{name}* -> *{r['verdict']}* | val {v['trades']}t {v['expectancy_r']:+}R "
                         f"PF {v['profit_factor']} | wf {wp}/{wt}")
        else:
            report += [f"- {r['why']}", ""]
            slack.append(f"*{name}* -> {r['verdict']} ({r['why']})")

    verdict_line = ("A signal cleared the gate + walk-forward on the index proxy - "
                    "CANDIDATE for Stage 2 (real futures data). Not proven; costs are a "
                    "stand-in." if any_pass else
                    "No signal cleared the gate on the index it would trade. A paid futures "
                    "feed would not change this. Honest NO-GO for now.")
    report += ["", f"Verdict: {verdict_line}", ""]
    slack.append(verdict_line)

    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out / f"futures_proxy_{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    print(f"report: reports/futures_proxy_{stamp}.md", flush=True)
    slackbot.post("\n".join(slack) + f"\nFull detail: reports/futures_proxy_{stamp}.md")


if __name__ == "__main__":
    run()
