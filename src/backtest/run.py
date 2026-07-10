"""Phase 1 backtest runner.

Downloads historical 5-min bars from Alpaca, runs all candidate strategies
per symbol-day through the simulator, applies the gate, writes a markdown
report to reports/, and posts a summary to Slack.

Run: python -m src.backtest.run
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def run():
    cfg = load_config()
    bt = cfg["backtest"]
    end = bt.get("end") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    start = bt["start"]
    symbols = cfg["universe"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"downloading {len(symbols)} symbols, {start} -> {end}, feed={bt['feed']}")
    bars = data_mod.fetch_bars(symbols, start, end,
                               timeframe=bt["timeframe"], feed=bt["feed"])
    if bars.empty:
        slackbot.post(f"[BACKTEST] {ts} - FAILED: no bars returned from Alpaca. Check keys/plan.")
        sys.exit(1)
    bars = data_mod.rth_only(bars)
    n_days = bars.groupby("symbol")["date"].nunique()
    print(f"bars: {len(bars):,} rows, days/symbol median {int(n_days.median())}")

    results = {}
    for strat_name, strat_mod in STRATEGIES.items():
        params = cfg["strategies"].get(strat_name, {})
        trades = []
        for symbol, sym_bars in bars.groupby("symbol"):
            for _, day in sym_bars.groupby("date"):
                day = day.reset_index(drop=True)
                if len(day) < 20:  # skip half sessions / bad data days
                    continue
                signals = strat_mod.generate(day, params)
                if signals:
                    trades.extend(engine.simulate_day(day, signals, cfg, strat_name))
        results[strat_name] = metrics.summarize(trades)

    # ---- report ----
    gate = cfg["gate"]
    lines = [f"# Backtest report - {ts}", "",
             f"Universe: {len(symbols)} symbols - {start} -> {end} - {bt['timeframe']} bars - "
             f"feed {bt['feed']} - LONG-ONLY - slippage {cfg['costs']['slippage_cents']}c/share/side - "
             f"risk {cfg['risk']['risk_pct']}%/trade on fixed ${cfg['risk']['equity']:,} equity", "",
             "Data caveats: split-adjusted; IEX fallback volumes are thin; shorts not modeled; "
             "no borrow fees; paper-grade fills.", ""]
    slack_lines = [f"[BACKTEST] {ts} - {start} -> {end}, {len(symbols)} symbols, long-only, costs modeled"]
    for name, m in results.items():
        if m["trades"] == 0:
            lines += [f"## {name}: 0 trades", ""]
            slack_lines.append(f"- {name}: 0 trades -> FAIL (no signals)")
            continue
        verdict, why = metrics.gate_verdict(m, gate)
        lines += [
            f"## {name}: {verdict}",
            "",
            f"- trades {m['trades']} - win rate {m['win_rate']}% - avg win ${m['avg_win']} / avg loss ${m['avg_loss']}",
            f"- expectancy {m['expectancy_r']}R (${m['expectancy_usd']}/trade) - profit factor {m['profit_factor']}",
            f"- net P&L ${m['net_pnl']:,} - max drawdown ${m['max_drawdown']:,}",
            f"- quarters positive {m['quarters_positive']}/{m['quarters_total']}",
            f"- gate: {why}", "",
            "Quarterly P&L:", "```", str(m["quarterly_table"]), "```", "",
        ]
        slack_lines.append(
            f"- {name}: {m['trades']} trades, {m['expectancy_r']}R "
            f"(${m['expectancy_usd']}/trade), PF {m['profit_factor']}, "
            f"{m['quarters_positive']}/{m['quarters_total']} quarters+ -> {verdict}"
        )
    passed = [n for n, m in results.items()
              if m["trades"] and metrics.gate_verdict(m, gate)[0] == "PASS"]
    verdict_line = (f"Verdict: {', '.join(passed)} clear the gate -> eligible for Phase 2 paper deployment."
                    if passed else
                    "Verdict: NO strategy clears the gate. Honest result - we iterate parameters/rules, "
                    "we do not deploy losers.")
    slack_lines.append(verdict_line)
    lines += ["", verdict_line, ""]

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md"
    out_file.write_text("\n".join(lines), encoding="utf-8")
    # per-trade log for audit
    for name, m in results.items():
        if m["trades"]:
            m["df"].to_csv(out_dir / f"trades_{name}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv",
                           index=False)
    print(f"report written: {out_file}")
    slackbot.post("\n".join(slack_lines))


if __name__ == "__main__":
    run()
