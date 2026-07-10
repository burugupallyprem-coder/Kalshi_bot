"""Phase 1.5 research harness: disciplined parameter sweep.

Anti-overfitting rules:
- Grids are PRE-DECLARED in config.yaml (small, motivated - not thousands).
- Parameters are chosen on TRAIN data only; the winner is evaluated ONCE on
  untouched VALIDATION data. The gate applies to VALIDATION results.
- Overfit signature is flagged explicitly: good train + bad validation.
- Slippage sensitivity on the winner (does the edge survive higher costs?).

Run: python -m src.backtest.research
"""

import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml

from src import data as data_mod
from src import slackbot
from src.backtest import engine, metrics
from src.strategies import momentum, orb, vwap_revert

ROOT = Path(__file__).resolve().parent.parent.parent
STRATEGIES = {"orb": orb, "vwap_revert": vwap_revert, "momentum": momentum}


def load_config():
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def expand_grid(grid):
    keys = sorted(grid.keys())
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        combos.append(dict(zip(keys, values)))
    return combos


def day_groups(bars):
    """[(symbol, day_df), ...] precomputed once and reused for every config."""
    groups = []
    for symbol, sym_bars in bars.groupby("symbol"):
        for _, day in sym_bars.groupby("date"):
            day = day.reset_index(drop=True)
            if len(day) >= 20:
                groups.append((symbol, day))
    return groups


def run_config(groups, strat_mod, params, cfg, name):
    trades = []
    for _, day in groups:
        signals = strat_mod.generate(day, params)
        if signals:
            trades.extend(engine.simulate_day(day, signals, cfg, name))
    return trades


def run():
    cfg = load_config()
    rs = cfg["research"]
    val_end = rs.get("val_end") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    symbols = cfg["universe"]

    print(f"downloading {len(symbols)} symbols, {rs['train_start']} -> {val_end}")
    bars = data_mod.fetch_bars(symbols, rs["train_start"], val_end,
                               timeframe=cfg["backtest"]["timeframe"],
                               feed=cfg["backtest"]["feed"])
    bars = data_mod.rth_only(bars)
    print(f"bars: {len(bars):,} rows")
    train_end = pd.to_datetime(rs["train_end"]).date()
    val_start = pd.to_datetime(rs["val_start"]).date()
    train_groups = day_groups(bars[bars["date"] <= train_end])
    val_groups = day_groups(bars[bars["date"] >= val_start])
    print(f"train symbol-days: {len(train_groups):,}  val symbol-days: {len(val_groups):,}")

    gate = cfg["gate"]
    report = [f"# Research report - {ts}", "",
              f"Universe {len(symbols)} - train {rs['train_start']} -> {rs['train_end']} - "
              f"validation {rs['val_start']} -> {val_end} - long-only - "
              f"slippage {cfg['costs']['slippage_cents']}c/side - grids pre-declared", ""]
    slack_lines = [f"[RESEARCH] {ts} - train->validate sweep, {len(symbols)} symbols, long-only"]
    all_rows = []

    for strat_name, strat_mod in STRATEGIES.items():
        base = dict(cfg["strategies"].get(strat_name, {}))
        combos = expand_grid(rs["grids"][strat_name])
        results = []
        for combo in combos:
            params = {**base, **combo}
            trades = run_config(train_groups, strat_mod, params, cfg, strat_name)
            m = metrics.summarize(trades)
            row = {"strategy": strat_name, **combo,
                   "train_trades": m.get("trades", 0),
                   "train_exp_r": m.get("expectancy_r", 0.0),
                   "train_pf": m.get("profit_factor", 0.0)}
            results.append((params, m, row))
            all_rows.append(row)
        eligible = [r for r in results if r[1].get("trades", 0) >= rs["min_train_trades"]]
        if not eligible:
            report += [f"## {strat_name}: no config reached {rs['min_train_trades']} train trades", ""]
            slack_lines.append(f"- {strat_name}: no eligible config -> SKIP")
            continue
        eligible.sort(key=lambda r: r[1]["expectancy_r"], reverse=True)

        report += [f"## {strat_name}", "", "Top 3 on TRAIN:", ""]
        for params, m, row in eligible[:3]:
            combo_str = ", ".join(f"{k}={row[k]}" for k in sorted(rs["grids"][strat_name].keys()))
            report.append(f"- {combo_str}: {m['trades']} trades, {m['expectancy_r']}R, PF {m['profit_factor']}")
        best_params, best_train, best_row = eligible[0]

        val_trades = run_config(val_groups, strat_mod, best_params, cfg, strat_name)
        vm = metrics.summarize(val_trades)
        if vm.get("trades", 0) == 0:
            report += ["", "Validation: 0 trades -> FAIL", ""]
            slack_lines.append(f"- {strat_name}: best train {best_train['expectancy_r']}R, val 0 trades -> FAIL")
            continue
        verdict, why = metrics.gate_verdict(vm, gate)
        overfit = (best_train["expectancy_r"] >= gate["min_expectancy_r"]
                   and vm["expectancy_r"] < 0)
        flag = " ** OVERFIT SIGNATURE (good train, negative validation)" if overfit else ""
        report += ["",
                   f"**Winner on validation: {verdict}**{flag}",
                   f"- train: {best_train['trades']} trades, {best_train['expectancy_r']}R, PF {best_train['profit_factor']}",
                   f"- validation: {vm['trades']} trades, {vm['expectancy_r']}R (${vm['expectancy_usd']}/trade), "
                   f"PF {vm['profit_factor']}, {vm['quarters_positive']}/{vm['quarters_total']} quarters+, "
                   f"maxDD ${vm['max_drawdown']:,}",
                   f"- gate: {why}", ""]
        # slippage sensitivity on the winner
        sens = []
        for sc in rs.get("slippage_sensitivity_cents", []):
            cfg_s = {**cfg, "costs": {**cfg["costs"], "slippage_cents": sc}}
            sm = metrics.summarize(run_config(val_groups, strat_mod, best_params, cfg_s, strat_name))
            sens.append(f"{sc}c -> {sm.get('expectancy_r', 0)}R")
        if sens:
            report += [f"- slippage sensitivity (validation): {' | '.join(sens)}", ""]
        slack_lines.append(
            f"- {strat_name}: train {best_train['expectancy_r']}R -> val {vm['expectancy_r']}R "
            f"(PF {vm['profit_factor']}, {vm['trades']} trades) -> {verdict}{flag}")

    passed = [l for l in slack_lines if "-> PASS" in l]
    verdict_line = ("Verdict: a configuration cleared the gate ON VALIDATION - candidate for Phase 2 paper deployment (your call)."
                    if passed else
                    "Verdict: nothing clears the gate on validation. We keep iterating or accept the honest NO EDGE.")
    slack_lines.append(verdict_line)
    report += ["", verdict_line, ""]

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out_dir / f"research_{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    pd.DataFrame(all_rows).to_csv(out_dir / f"research_grid_{stamp}.csv", index=False)
    print(f"report written: reports/research_{stamp}.md")
    slackbot.post("\n".join(slack_lines))


if __name__ == "__main__":
    run()
