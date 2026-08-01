# Indicator search (daily swing) - 2026-08-01 11:01 UTC

RESEARCH ONLY. Classic indicators (native Python, no Pine Script), same DSR + forward gates.
search 2021-01-01->2025-06-30 | forward 2025-07-01->2026-07-31
variants tested: **9** | DSR threshold 0.95 | cost 5bps/turn
best: fib[lookback=20, retr=0.618] | search Sharpe 0.0076 (3109 days)
luck bar (expected max Sharpe under null): 0.0087
**Deflated Sharpe: 0.4754**

## All variants by search Sharpe
- fib[lookback=20, retr=0.618]: 0.0076 (3109 days)
- bollinger[k=2.5, mode=revert, period=20]: 0.006 (3892 days)
- bollinger[k=2.0, mode=breakout, period=20]: 0.0035 (8164 days)
- fib[lookback=20, retr=0.5]: 0.0019 (4574 days)
- macd[fast=12, signal=9, slow=26]: -0.001 (14638 days)
- rsi[high=70, low=30, period=10]: -0.0037 (6544 days)
- rsi[high=70, low=30, period=14]: -0.0053 (5177 days)
- bollinger[k=2.0, mode=revert, period=20]: -0.0063 (8144 days)
- bollinger[k=2.5, mode=breakout, period=20]: -0.0086 (3900 days)