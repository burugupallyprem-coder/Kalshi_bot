"""Stage 1: FUTURES EDGE PROXY - does the ORB signal have edge on the INDEX intraday?

RESEARCH ONLY. Never touches the live/paper trader or the arming kill-switch.

We test the filtered-ORB signal on the index ETFs that the micro futures track
(SPY->MES, QQQ->MNQ, DIA->MYM, IWM->M2K), through the SAME gate + walk-forward as
everything else. Logic: if the signal can't clear the gate on the very index it
would trade, a paid futures data feed will not rescue it. If it can, it earns
Stage 2 (real futures data + contract mechanics).

Two futures-realistic framings, judged separately (each picks its winner on TRAIN,
then is judged ONCE on validation - no extra validation looks):
  - single_instrument (rs_topk=None): trade each index on its own. This is the
    honest single-contract case (you'd pick one micro, e.g. MES). It DROPS the
    cross-sectional relative-strength filter that carried the stock edge, so
    expect it to be weak - that is exactly the thing we need to know.
  - index_basket (rs_topk=2): trade the 2 strongest of the 4 indices each day,
    restoring relative strength across the micros.

COSTS: uses the equity cent-slippage model as a stand-in. Real futures costs
(tick spread + exchange fees) differ and are modeled properly in Stage 2. Treat
any positive result here as "worth paying for real data to confirm", not "done".

Run: python -m src.backtest.futures_proxy
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src import data as data_mod
from src import slackbot
from src.backtest import metrics, research
from src.strategies import orb

ROOT = Path(__file__).resolve().parent.parent.parent


def _combo_str(d):
    return ", ".join(f"{k}={v}" for k, v in sorted(d.items()))


def evaluate_framing(bars, cfg, framing_params):
    """Pick the TRAIN winner across the small rr grid for one framing, then judge
    it ONCE on validation + walk-forward + slippage. Returns a result dict."""
    rs = cfg["research"]
    fp = cfg["futures_proxy"]
    gate = cfg["gate"]
    train_end = pd.to_datetime(rs["train_end"]).date()
    val_start = pd.to_datetime(rs["val_start"]).date()
    train_groups = research.day_groups(bars[bars["date"] <= train_end])
    val_groups = research.day_groups(bars[bars["date"] >= val_start])
    train_ctx = research.build_context(train_groups, cfg)
    val_ctx = research.build_context(val_groups, cfg)
    wf = rs.get("walkforward", {}) or {}
    base = dict(cfg["strategies"].get("orb", {}))
    fixed = dict(fp["fixed"])
    min_train = rs.get("min_train_trades", 100)

    # sweep the declared grid within this framing; winner chosen on TRAIN only
    combos = research.expand_grid(fp["grid"])
    scored = []
    for combo in combos:
        params = {**base, **fixed, **framing_params, **combo}
        tm = metrics.summarize(
            research.run_config(train_groups, orb, params, cfg, "orb", train_ctx))
        scored.append((params, combo, tm))
    eligible = [x for x in scored if x[2].get("trades", 0) >= min_train]
    if not eligible:
        return {"framing": framing_params, "verdict": "SKIP",
                "why": f"no combo reached {min_train} train trades",
                "best_combo": None, "train": None, "val": None, "wf": (0, 0, [])}
    eligible.sort(key=lambda x: x[2].get("expectancy_r", 0.0), reverse=True)
    best_params, best_combo, best_train = eligible[0]

    vm = metrics.summarize(
        research.run_config(val_groups, orb, best_params, cfg, "orb", val_ctx))
    if vm.get("trades", 0) == 0:
        return {"framing": framing_params, "verdict": "FAIL", "why": "0 validation trades",
                "best_combo": best_combo, "train": best_train, "val": vm, "wf": (0, 0, [])}
    verdict, why = metrics.gate_verdict(vm, gate)
    wf_pos, wf_tot, wf_per = research.evaluate_walk_forward(
        val_groups, orb, best_params, cfg, "orb", int(wf.get("folds", 4)), val_ctx)
    wf_ok = wf_tot > 0 and (wf_pos / wf_tot) >= float(wf.get("min_positive_frac", 0.6))
    if verdict == "PASS" and not wf_ok:
        verdict = "FAIL"
        extra = f"walk-forward only {wf_pos}/{wf_tot} folds positive"
        why = extra if why == "all gate checks met" else f"{why}; {extra}"
    sens = []
    for sc in rs.get("slippage_sensitivity_cents", []):
        cfg_s = {**cfg, "costs": {**cfg["costs"], "slippage_cents": sc}}
        sm = metrics.summarize(
            research.run_config(val_groups, orb, best_params, cfg_s, "orb", val_ctx))
        sens.append(f"{sc}c -> {sm.get('expectancy_r', 0)}R")
    return {"framing": framing_params, "verdict": verdict, "why": why,
            "best_combo": best_combo, "train": best_train, "val": vm,
            "wf": (wf_pos, wf_tot, wf_per), "sens": sens}


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

    for label, fr in fp["framings"].items():
        r = evaluate_framing(bars, cfg, fr)
        if r["verdict"] == "PASS":
            any_pass = True
        report += [f"## {label} ({_combo_str(fr)})", "", f"Verdict: **{r['verdict']}**"]
        if r["best_combo"] is not None and r["val"] is not None:
            v, t = r["val"], r["train"]
            wp, wt, wper = r["wf"]
            report += [
                f"- winner: {_combo_str(r['best_combo'])}",
                f"- train: {t['trades']} trades, {t['expectancy_r']}R, PF {t['profit_factor']}",
                f"- validation: {v['trades']} trades, win {v['win_rate']}%, {v['expectancy_r']}R "
                f"(${v['expectancy_usd']}/trade), PF {v['profit_factor']}, "
                f"{v['quarters_positive']}/{v['quarters_total']} quarters+, maxDD ${v['max_drawdown']:,}",
                f"- walk-forward: {wp}/{wt} folds positive "
                f"(per-fold R: {', '.join(f'{x:+.3f}' for x in wper)})",
                f"- slippage: {' | '.join(r.get('sens', []))}",
                f"- gate: {r['why']}", ""]
            slack.append(f"*{label}* -> *{r['verdict']}* | val {v['trades']}t {v['expectancy_r']:+}R "
                         f"PF {v['profit_factor']} | wf {wp}/{wt}")
        else:
            report += [f"- {r['why']}", ""]
            slack.append(f"*{label}* -> {r['verdict']} ({r['why']})")

    verdict_line = ("A framing cleared the gate + walk-forward on the index proxy - "
                    "CANDIDATE for Stage 2 (real futures data). Not proven; costs are a "
                    "stand-in." if any_pass else
                    "Neither framing cleared the gate on the index it would trade. A paid "
                    "futures feed would not change this. Honest NO-GO for now.")
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
