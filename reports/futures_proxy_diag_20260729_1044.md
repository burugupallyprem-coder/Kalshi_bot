# Futures-proxy diagnostic: momentum - 2026-07-29 10:39 UTC

RESEARCH ONLY - re-scores the pre-registered winner, no new validation debt.
winner: hold_above=3, rr=3.0, side=long, stop_lookback=12, time_stop_bars=24
validation: 148 trades, 0.263R, PF 1.349

## Bootstrap on validation expectancy_R (2000 resamples)
- point +0.263R | 90% CI [+0.048, +0.461] | P(mean>0) = 97.9%
- read: CI clears zero - edge unlikely to be pure luck

## Validation breakdown (descriptive - do NOT fit filters to this)
  by symbol:
    DIA: 34 trades, +0.629R, win 50%
    IWM: 38 trades, -0.360R, win 29%
    QQQ: 36 trades, +0.585R, win 50%
    SPY: 40 trades, +0.254R, win 45%
  by quarter:
    2026Q1: 64 trades, +0.291R, win 41%
    2026Q2: 68 trades, +0.292R, win 47%
    2026Q3: 16 trades, +0.026R, win 38%
  by direction:
    long: 148 trades, +0.263R, win 43%
  by exit reason:
    eod_flat: 12 trades, +0.305R, win 50%
    stop: 65 trades, -1.037R, win 0%
    target: 29 trades, +2.957R, win 100%
    time_stop: 42 trades, +0.402R, win 69%