# Pre-Registration — Strategy #10 (3-step boring scalp) forward paper trial

**Registered:** 2026-07-23. **Status:** RESEARCH ONLY. Does not touch the live/paper
trader, the arming kill-switch, or the alpaca_client PAPER LOCK.

## Why this exists
Strategy #10 (1-minute break-and-retest scalp) came back **WEAK PASS** on the
2026 backtest validation window: +0.098R over 2,070 trades, PF 1.172,
walk-forward 4/4 folds, survives 2c slippage — but the TRAIN edge was ~0, so the
selection carried little information and the validation window was already spent
by prior research. A WEAK PASS is a hypothesis, not proven money. The only honest
way to confirm it is to measure the **frozen** config on data that did not exist
when it was built.

## What is frozen (no changes, no re-search)
From `config.yaml -> strategy10.forward.frozen`:
- `trail_lookback = 20`, `trend_filter = false`, `max_trades_day = 2`
- universe, session, sizing, costs: exactly the strategy #10 backtest settings
  (10-name liquid subset, 1-minute bars, 1c/share/side slippage, 0.5% risk).

## The window
- **Lock date: 2026-07-23.** Only trades with session date **>= lock_date** count.
- Data before the lock date is fetched purely as warmup (prev-day levels, EMAs)
  and is **never scored**.
- Expected volume ~300 trades/month (the backtest ran ~300/mo across the
  universe), so the sample fills fast — unlike the SMC swing trial.

## Pre-declared verdict gates (no moving goalposts)
- **Interim look at 100 closed trades** — reported, not a verdict (variance still
  high).
- **Verdict at 300 closed trades.** PASS requires ALL of, on the forward window:
  - expectancy >= +0.05R
  - profit factor >= 1.15
  - >= 60% of calendar quarters positive
  - bootstrap 90% CI on expectancy_R clears zero (edge distinguishable from luck)
- Failing any gate is a valid, expected outcome. A forward result that lands near
  or below zero says the backtest edge did not survive — exactly what this test is
  for.

## What a PASS does and does not mean
- A forward PASS would upgrade strategy #10 from "WEAK PASS backtest" to
  "confirmed out-of-sample edge — candidate for a paper deployment decision."
- It does **not** authorize real capital. Real money remains behind every existing
  gate, including the F-1 / immigration-attorney sign-off. This trial touches none
  of that.

## How it is measured
`python -m src.backtest.strategy10_scalp_forward` (weekly workflow `strategy10-forward`)
runs the frozen config, scores only post-lock trades, and posts `[S10-FORWARD]` to
Slack with progress toward the 100/300 thresholds and the gate status. The report
commits to `reports/`.
