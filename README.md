# Systematic Trading Research Platform

A from-scratch quantitative research platform for designing, backtesting, and paper-deploying
intraday and cross-asset systematic strategies — built with an emphasis on **methodological
rigor over P&L**. The defining feature of this project is not a winning strategy; it is an
evaluation pipeline disciplined enough to **honestly reject its own ideas** when they fail
out-of-sample.

> **Research / paper-trading only.** No live capital is traded. The broker client is
> hard-locked to paper endpoints.

---

## Why this project is different

Most retail strategy repos show a single, beautiful, over-fit backtest. This one is built to
do the opposite — to *catch* over-fitting before it costs money:

- **Pre-registration.** Parameter grids and success gates are declared *before* each run; no
  moving the goalposts after seeing results.
- **Train / validation separation.** Parameters are chosen on a training window and judged
  **once** on untouched out-of-sample data.
- **Walk-forward validation.** A strategy must hold up across multiple sequential folds, not a
  single lucky window.
- **Realistic costs.** Slippage and (for futures) tick-spread + commission are charged against
  every trade; a "WEAK PASS" label flags edges that only survive on zero-cost assumptions.
- **No-lookahead engine.** Signals never see the bar they trade on; stops are checked before
  targets; gaps fill on the unfavorable side.
- **Bootstrap significance + regime breakdowns** on any candidate that clears the gate.

## The honest scorecard

Every strategy below was run through the *same* pre-registered gate (net expectancy, profit
factor, walk-forward, cost sensitivity). The results are reported as they came:

| Strategy | Asset class | Verdict |
|---|---|---|
| Opening-Range Breakout (filtered: regime + relative-strength) | US equities (intraday) | Deployed to paper as a measured benchmark |
| VWAP mean-reversion | US equities | Rejected — no out-of-sample edge |
| Momentum continuation | US equities | Rejected |
| 3-step break-and-retest scalp | US equities (1-min) | Weak pass; flagged fragile |
| Momentum on index futures | MES/MNQ/MYM (real Databento data) | Rejected — edge did not survive real costs |
| Diversified time-series momentum (trend-following) | 21 CME futures markets | Rejected on this window |

The value here is the *process that produced this table* — the same discipline a quant
researcher uses to separate real edges from noise.

---

## Architecture

```
GitHub Actions (scheduler)  ->  Strategy / signal layer  ->  No-lookahead backtest engine
                                                                        |
Broker (Alpaca paper, code-locked)  <-  Risk engine (sizing, caps)  <---+
                                                                        |
Databento (futures data)  ->  Research harness (gate + walk-forward)  ->  Slack alerts + reports
```

- **Execution / live paper:** Alpaca paper API, server-side bracket orders, hard risk caps
  (fixed % risk per trade, position caps, forced end-of-day flat, never overnight).
- **Automation:** fully serverless via GitHub Actions (pre-market briefing, entry session,
  end-of-day reconciliation, weekly research sweep) with Slack monitoring and a self-rendering
  dashboard.
- **Data:** Alpaca (equities) and Databento (CME futures, roll-adjusted continuous series).
- **Safety:** paper-lock in the broker client; an arming kill-switch wired to research verdicts.

## Tech stack
Python (pandas, NumPy) · Alpaca & Databento APIs · GitHub Actions (CI + scheduling) ·
Slack API · YAML-driven configuration · pytest-style offline unit tests.

## Repository layout
- `src/strategies/` — signal generators (ORB, VWAP-reversion, momentum, filters)
- `src/backtest/` — no-lookahead engine, metrics, research harness, walk-forward, futures + TSMOM
- `src/live/` — paper execution, risk engine, pre-market, dashboard
- `tests/` — offline unit tests for the engine, filters, gate, and cost model
- `reports/` — committed, timestamped research reports (the audit trail)
- `PRE_REGISTRATION*.md` — pre-declared hypotheses and success criteria

---

*Built as a self-directed study in quantitative research methodology and trading-systems
engineering. Emphasis throughout: reproducibility, cost realism, and intellectual honesty
about what does and does not work.*
