"""Stage 2: confirm the momentum lead on REAL futures with REAL costs. RESEARCH ONLY.

Runs the LOCKED Stage-1 winner (no re-optimization) on real MES/MNQ/MYM data
through the same engine + metrics + walk-forward, but charges each contract its
own realistic cost (tick half-spread + commission, via instruments.py). Per-symbol
runs are pooled for the gate. M2K (Russell micro) is a secondary check only.

This module is DATA-AGNOSTIC: `evaluate(bars_by_symbol, cfg)` takes an already-
loaded dict of {symbol: RTH DataFrame} so it is fully unit-testable offline. The
Databento fetch lives in src/backtest/futures_data.py; run.py wires them together.

Nothing here trades or touches the live/paper trader or arming.
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import instruments
from src.backtest import engine, metrics, research
from src.strategies import momentum

ROOT = Path(__file__).resolve().parent.parent.parent


def _cfg_for_symbol(cfg, symbol):
    """Clone cfg with this contract's realistic per-side cost in the engine's unit."""
    fs = cfg["futures_stage2"]
    slip = instruments.effective_slippage_cents(
        symbol,
        commission_per_side=fs.get("commission_per_side", 0.50),
        ticks_spread_per_side=fs.get("ticks_spread_per_side", 0.5))
    return {**cfg, "costs": {**cfg.get("costs", {}), "slippage_cents": slip}}, slip


def _run_symbol(day_df_list, cfg_sym, params):
    trades = []
    for day in day_df_list:
        sigs = momentum.generate(day, params)
        if sigs:
            trades.extend(engine.simulate_day(day, sigs, cfg_sym, "momentum"))
    return trades


def evaluate(bars_by_symbol, cfg):
    """bars_by_symbol: {symbol: RTH DataFrame}. Returns per-symbol + pooled results
    for the LOCKED momentum params, with per-contract real costs and walk-forward."""
    fs = cfg["futures_stage2"]
    params = dict(fs["locked_params"])
    rs = cfg["research"]
    gate = cfg["gate"]
    val_start = pd.to_datetime(fs.get("val_start", rs["val_start"])).date()
    wf = rs.get("walkforward", {}) or {}

    per_symbol = {}
    pooled_trades = []
    for symbol, bars in bars_by_symbol.items():
        cfg_sym, slip = _cfg_for_symbol(cfg, symbol)
        # only the out-of-sample span is judged (the params are LOCKED, not fit here)
        val = bars[bars["date"] >= val_start]
        days = [d.reset_index(drop=True) for _, d in val.groupby("date") if len(d) >= 20]
        trades = _run_symbol(days, cfg_sym, params)
        m = metrics.summarize(trades)
        per_symbol[symbol] = {"slippage_cents": slip, "metrics": m, "trades": trades}
        if symbol in fs.get("primary", []):
            pooled_trades.extend(trades)

    pm = metrics.summarize(pooled_trades)
    verdict, why = (metrics.gate_verdict(pm, gate) if pm.get("trades", 0) else ("FAIL", "0 trades"))
    # pooled walk-forward across the primary micros' trade dates
    wf_pos = wf_tot = 0
    wf_per = []
    if pm.get("trades", 0):
        df = pm["df"]
        dates = sorted(set(df["date"]))
        folds = research.walk_forward_folds(dates, int(wf.get("folds", 4)))
        for lo, hi in folds:
            sub = df[(df["date"] >= lo) & (df["date"] <= hi)]
            wf_per.append(sub["r_multiple"].mean() if len(sub) else 0.0)
        wf_pos = sum(1 for r in wf_per if r > 0)
        wf_tot = len(wf_per)
        if verdict == "PASS" and (wf_tot == 0 or wf_pos / wf_tot < float(wf.get("min_positive_frac", 0.6))):
            verdict = "FAIL"
            why = (why + "; " if why != "all gate checks met" else "") + \
                  f"walk-forward {wf_pos}/{wf_tot} folds positive"
    # broad check: positive on >=2 of the 3 primary micros
    prim_pos = sum(1 for s in fs.get("primary", [])
                   if per_symbol.get(s, {}).get("metrics", {}).get("expectancy_r", 0) > 0)
    if verdict == "PASS" and prim_pos < 2:
        verdict = "FAIL"
        why = f"{why}; only {prim_pos}/3 primary micros positive"
    return {"verdict": verdict, "why": why, "pooled": pm, "per_symbol": per_symbol,
            "wf": (wf_pos, wf_tot, wf_per), "primary_positive": prim_pos}


def build_report(res, cfg, ts):
    fs = cfg["futures_stage2"]
    pm = res["pooled"]
    wp, wt, wper = res["wf"]
    lines = [f"# Stage 2: futures momentum on REAL data - {ts}", "",
             "RESEARCH ONLY - LOCKED Stage-1 params, real per-contract costs, "
             "out-of-sample; does not touch the live trader.",
             f"locked: {', '.join(f'{k}={v}' for k, v in sorted(fs['locked_params'].items()))}",
             f"primary micros: {fs.get('primary')} | secondary: {fs.get('secondary')}",
             f"costs: {fs.get('ticks_spread_per_side',0.5)} tick half-spread + "
             f"${fs.get('commission_per_side',0.5)}/side (VERIFY with broker)", "",
             f"## POOLED (primary micros) -> **{res['verdict']}**"]
    if pm.get("trades", 0):
        lines += [
            f"- {pm['trades']} trades, {pm['expectancy_r']}R (${pm['expectancy_usd']}/trade), "
            f"PF {pm['profit_factor']}, {pm['quarters_positive']}/{pm['quarters_total']} quarters+, "
            f"maxDD ${pm['max_drawdown']:,}",
            f"- walk-forward: {wp}/{wt} folds positive "
            f"(per-fold R: {', '.join(f'{x:+.3f}' for x in wper)})",
            f"- gate: {res['why']}"]
    else:
        lines.append(f"- {res['why']}")
    lines += ["", "## Per-symbol (real costs)"]
    for sym, d in res["per_symbol"].items():
        m = d["metrics"]
        tag = "primary" if sym in fs.get("primary", []) else "secondary"
        lines.append(f"- {sym} ({tag}, cost {d['slippage_cents']}c/side): "
                     f"{m.get('trades',0)} trades, {m.get('expectancy_r',0)}R, "
                     f"PF {m.get('profit_factor',0)}")
    return "\n".join(lines)


def run():
    from src import data as _d  # noqa
    from src import slackbot
    from src.backtest import futures_data
    cfg = research.load_config()
    fs = cfg["futures_stage2"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    symbols = list(fs.get("primary", [])) + list(fs.get("secondary", []))
    try:
        bars_by_symbol = futures_data.load(symbols, cfg)
    except Exception as e:
        slackbot.post(f"[FUTURES-STAGE2] {ts} FAILED loading data: {e}")
        return
    if not bars_by_symbol:
        slackbot.post(f"[FUTURES-STAGE2] {ts} FAILED: no futures bars returned.")
        return
    res = evaluate(bars_by_symbol, cfg)
    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out / f"futures_stage2_{stamp}.md").write_text(build_report(res, cfg, ts), encoding="utf-8")
    pm = res["pooled"]; wp, wt, _ = res["wf"]
    verdict_note = ("CONFIRMED on real futures - earns a PAPER trial (not live, not a "
                    "prop challenge). " if res["verdict"] == "PASS" else
                    "Did NOT confirm on real futures. Honest stop - no re-sweeping. ")
    slackbot.post(
        f"*[FUTURES-STAGE2]* {ts} - LOCKED momentum on real MES/MNQ/MYM, RESEARCH ONLY\n"
        f"pooled {pm.get('trades',0)}t {pm.get('expectancy_r',0):+}R PF {pm.get('profit_factor',0)} | "
        f"wf {wp}/{wt} | {res['primary_positive']}/3 micros+ -> *{res['verdict']}*\n"
        f"{verdict_note}Full detail: reports/futures_stage2_{stamp}.md")


if __name__ == "__main__":
    run()
