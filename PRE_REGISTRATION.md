# Pre-registration - Filtered ORB paper trial (v2)

Declared 2026-07-18. No moving goalposts. Failing is a valid, expected outcome.

## What is being tested
The research sweep of 2026-07-18 produced the FIRST config to clear the hardened
gate (single-window gate AND walk-forward), with TRAIN and VALIDATION agreeing:

- config: ORB long, open_bars=3, cutoff 10:30 ET, rr=1.5, vol_confirm=false,
  **min_or_width_frac=0.004, regime_filter=true, rs_topk=5**
- train (2024-07 -> 2025-12): 522 trades, +0.105R, PF 1.334
- validation (2026-01 -> 2026-07-17): 150 trades, +0.082R, PF 1.289, 3/3 quarters+,
  maxDD $1,349; survives 2c slippage (0.076R); walk-forward 3/4 folds positive

This is a BACKTEST edge. It has never traded live. This trial measures whether it
survives real-time IEX data and paper fills. It is NOT proven money and is NOT
eligible for real capital.

## Trial design (fixed in advance)
- Start: Monday 2026-07-20. Length: 21 trading sessions. Zero human touches.
- Account: Alpaca PAPER, $100k simulated. Live endpoint stays code-locked.
- Execution: the deployed live config in config.yaml (filters applied in real time).
- Risk: 0.5%/trade, max 5 concurrent (matches rs_topk=5), flat by 15:50 ET,
  never overnight. Structural worst-case day ~ -2.5%.

## Success gates (judged once, at the end)
- Mechanical: 100% autonomous sessions, zero risk-cap breaches, complete logs.
- Statistical: >= 60 trades, positive net expectancy AFTER real paper fills,
  PF >= 1.15, max drawdown <= 6%.
Missing any statistical gate = the backtest edge did NOT survive contact with live
fills. That is a real result, not a failure of the process.

## Honest translation
Backtest expectancy ~ +0.082R at 0.5% risk on $100k ~= $40/day, ~1 trade/day. Expect
live to come in LOWER. Paper $100k overstates a small live account. No capital talk,
and no real-money discussion, until this trial passes AND the roadmap gates
(3+ months positive, immigration attorney + DSO sign-off, explicit approval) are met.

## Kill-switch
arming.mode stays "manual" for the trial so a mid-trial research re-run cannot halt
the measurement. The day-level divergence monitor still alerts. After 21 sessions,
switch arming.mode to "auto" so a no-edge config can never keep trading unattended.
