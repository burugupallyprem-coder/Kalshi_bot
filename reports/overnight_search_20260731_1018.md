# Overnight close->open search - 2026-07-31 10:18 UTC

RESEARCH ONLY. Different board (overnight drift). Same deflated-Sharpe + forward gates.
search 2021-01-01->2025-06-30 | forward 2025-07-01->2026-07-30
variants tested: **8** | DSR threshold 0.95 | cost 5bps rt
best: overnight[side=long, cond=after_up] | search Sharpe 0.0115 (8823 nights)
luck bar (expected max Sharpe under null): 0.0607
**Deflated Sharpe: 0.0**

## All variants by search Sharpe
- overnight[side=long, cond=after_up]: 0.0115 (8823 nights)
- overnight[side=long, cond=spy_up]: 0.0086 (10935 nights)
- overnight[side=long, cond=always]: -0.0062 (16890 nights)
- overnight[side=long, cond=after_down]: -0.0251 (8027 nights)
- overnight[side=short, cond=after_down]: -0.047 (8027 nights)
- overnight[side=short, cond=always]: -0.067 (16890 nights)
- overnight[side=short, cond=after_up]: -0.0858 (8823 nights)
- overnight[side=short, cond=spy_up]: -0.0938 (10935 nights)