"""Strategy #10 FORWARD paper-validation trial - RESEARCH ONLY, touches nothing live.

Measures the FROZEN strategy #10 winner (config.yaml -> strategy10.forward.frozen)
on data from lock_date onward only - a fresh out-of-sample window nobody picked
over. This is the honest confirmation of the backtest WEAK PASS: no re-search, no
moving goalposts (see PRE_REGISTRATION_STRATEGY10.md).

Each run fetches 1-minute bars from (lock_date - warmup_days) to now, simulates the
frozen config, then scores ONLY trades whose session date >= lock_date. Warmup bars
exist purely so prev-day levels / EMAs are defined; they are never scored. Reports
progress toward the interim (100) and verdict (300) trade thresholds, the gate, and
a bootstrap CI once enough trades exist.

Run: python -m src.backtest.strategy10_scalp_forward
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src import data as data_mod
from src import slackbot
from src.backtest import metrics
from src.backtest.strategy10_scalp import load_config, run_combo, split_trades  # noqa: F401
from src.backtest.strategy10_scalp import simulate_symbol
from src.backtest.strategy10_scalp_diag import bootstrap_ci

ROOT = Path(__file__).resolve().parent.parent.parent


def forward_only(trades, lock):
    """Keep only trades whose session date is on/after the lock date (warmup excluded)."""
    return [t for t in trades if pd.to_datetime(t.date).date() >= lock]


def run():
    cfg = load_config()
    s10 = cfg["strategy10"]
    fwd = s10["forward"]
    cfg["universe"] = s10["universe"]
    frozen = fwd["frozen"]
    lock = pd.to_datetime(fwd["lock_date"]).date()
    gate = fwd["gate"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    end = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    warm_start = (lock - timedelta(days=int(fwd["warmup_days"]))).strftime("%Y-%m-%d")
    symbols = s10["universe"]

    print(f"downloading {len(symbols)} symbols {s10['timeframe']}, {warm_start} -> {end}", flush=True)
    bars = data_mod.fetch_bars(symbols, warm_start, end,
                               timeframe=s10["timeframe"], feed=s10["feed"])
    if bars.empty:
        slackbot.post(f"[S10-FORWARD] {ts} - no bars from Alpaca (check keys/plan).")
        return
    bars = data_mod.rth_only(bars)

    all_trades = []
    for symbol, sym in bars.groupby("symbol"):
        all_trades.extend(simulate_symbol(sym, symbol, dict(frozen), cfg))
    fwd_trades = forward_only(all_trades, lock)
    m = metrics.summarize(fwd_trades)
    n = m.get("trades", 0)

    combo_str = ", ".join(f"{k}={v}" for k, v in sorted(frozen.items()))
    report = [f"# Strategy #10 FORWARD trial - {ts}", "",
              "RESEARCH ONLY - frozen config, measured only on data >= lock date. "
              "No re-search, no moving goalposts (see PRE_REGISTRATION_STRATEGY10.md).",
              f"frozen: {combo_str}", f"lock date: {fwd['lock_date']} - scored window "
              f"{fwd['lock_date']} -> {end}", ""]

    if n == 0:
        report += ["## Status: 0 trades yet in the forward window.", ""]
        body = [f"frozen {combo_str}", "0 trades scored yet (window just opened)."]
    else:
        interim, target = int(fwd["interim_trades"]), int(fwd["target_trades"])
        stage = ("verdict-ready" if n >= target else
                 "interim look" if n >= interim else "accumulating")
        ci_txt = ""
        if n >= interim:
            lo, hi, frac_pos, pt = bootstrap_ci([t.r_multiple for t in fwd_trades])
            ci_txt = (f"bootstrap 90% CI [{lo:+.3f},{hi:+.3f}]R P(>0)={frac_pos*100:.0f}% "
                      f"-> CI {'clears 0' if lo > 0 else 'includes 0'}")
        if n >= target:
            verdict, why = metrics.gate_verdict(m, gate)
            if n >= interim and lo <= 0 and verdict == "PASS":
                verdict, why = "FAIL", f"{why}; bootstrap CI includes 0"
            status = f"VERDICT: {verdict} ({why})"
        else:
            status = f"progress {n}/{target} trades ({stage}) - no verdict yet"
        report += [
            f"## {status}",
            f"- forward: {m['trades']} trades, win {m['win_rate']}%, {m['expectancy_r']}R "
            f"(${m['expectancy_usd']}/trade), PF {m['profit_factor']}, "
            f"{m['quarters_positive']}/{m['quarters_total']} quarters+, maxDD ${m['max_drawdown']:,}",
            (f"- {ci_txt}" if ci_txt else "- (bootstrap CI once >= interim sample)"),
            f"- thresholds: interim {interim}, verdict {target}", ""]
        body = [f"frozen {combo_str}",
                f"{m['trades']} trades, {m['expectancy_r']:+}R, PF {m['profit_factor']}, "
                f"{m['quarters_positive']}/{m['quarters_total']}q+ ({stage})",
                ci_txt or f"accumulating -> interim look at {interim} trades"]

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (out_dir / f"strategy10forward_{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    if fwd_trades:
        pd.DataFrame([t.__dict__ for t in fwd_trades]).to_csv(
            out_dir / f"trades_strategy10forward_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv",
            index=False)
    print(f"report written: reports/strategy10forward_{stamp}.md", flush=True)

    header = (f"*[S10-FORWARD]* {ts} - RESEARCH ONLY, does not touch the trader\n"
              f"Strategy #10 frozen forward trial since {fwd['lock_date']}")
    footer = f"Full detail: reports/strategy10forward_{stamp}.md"
    slackbot.post("\n\n".join([header] + body + [footer]))


if __name__ == "__main__":
    run()
