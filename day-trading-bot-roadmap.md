# Day-Trading Bot — Build Roadmap (v1)

**Draft for approval — July 10, 2026**
Platform: Alpaca paper · Money: paper only · Infra: GitHub Actions + Slack · LLM: not in the trade loop (rules-based v1; Claude runs the weekly research cycle only)

---

## 1. The honest math (read this first)

- Your $50-150/day target = 0.05-0.15%/day on $100k. It is the YARDSTICK BEING TESTED, not a promise. Honest translation today: measured edge is ~zero, so measured $/day is ~zero. $/day = per-trade edge (R, after realistic fills) x risk per trade x trades/day - and paper $100k P&L massively OVERSTATES what a small live account would earn. No capital talk until a config clears the gate AND walk-forward.
- **Dollars = edge × capital.** Required daily return to make $100/day:

| Capital | Required/day | Annualized | Reality check |
|---|---|---|---|
| $5,000 | 2.0% | ~500% | Fantasy |
| $25,000 | 0.40% | ~100% | Elite, almost never sustained |
| $100,000 | 0.10% | ~25% | Top-decile professional |

- Alpaca's paper account defaults to **$100k**, so paper dollar-P&L will look far better than a realistic starting live account would deliver. We therefore measure **edge** (net expectancy per trade after costs), then translate to $/day per capital level at the end.
- **One month proves the machine, not the edge.** ~21 sessions proves full autonomy, risk-cap enforcement, and clean logs. It is not statistically enough to prove profitability — variance dominates below ~100 trades. The evidence burden sits on 2+ years of backtests first; the paper month validates live behavior.
- Base-rate honesty: most retail intraday strategies die after realistic costs. Discovering that cheaply is the system *working* — same house rule as OANDA: the value is the rigor, not the P&L.

## 2. Which app + your setup steps (~15 min)

1. **Alpaca** — sign up at alpaca.markets with just an email. The **paper account is automatic, free, open globally** — no residency, SSN, or funding questions. **Do not complete the live brokerage application** (not needed; that's where the visa-relevant questions live).
2. Dashboard → generate **paper API keys** → add as GitHub repo secrets `ALPACA_API_KEY_ID` and `ALPACA_SECRET_KEY`. Don't paste keys in chat.
3. Create a new repo `day-trader-bot` (keep it separate from Kalshi_bot) + a Slack webhook for `#day-trader-bot`, secret `SLACK_WEBHOOK_URL` — same pattern as the Kalshi setup.

Data: the free plan = real-time IEX feed + historical bars — sufficient for liquid large-caps on 5-minute bars. Upgrade to full SIP ($99/mo Algo Trader Plus) **only if** Phase 1 proves free data is the bottleneck.

## 3. Target system

```
Pre-market scanner → Strategy engine → Risk engine → Execution (paper) → Logs → Post-mortem loop
```

- **Pre-market scanner** (8:45 ET): universe = S&P 100 + major ETFs; select ~15 names by dollar volume and overnight gaps ≥ 2%. Skip earnings-day names.
- **Strategy engine** — runs on **5-minute bars**, deliberately not tick-scalping (GitHub Actions has minutes of scheduling jitter; pretending to scalp would be dishonest). v1 candidates, all of which must survive backtesting before deployment: opening-range breakout, VWAP mean-reversion, momentum continuation. Weekly champion/challenger promotion, OANDA-style.
- **Risk engine** (hard caps in code): ≤0.5% equity risk per trade via stop-distance sizing; max 3 concurrent positions; daily kill-switch at −1.5% equity (flatten + halt for the day); no new entries after 15:30 ET; flatten everything by 15:50 ET — never hold overnight.
- **Execution**: Alpaca paper **bracket orders** (server-side stop + target, so a crashed job can never orphan a position).
- **Ops**: GitHub Actions — pre-market job; two intraday loop jobs (9:25–12:45 and 12:40–16:05 ET, each under the 6-hour job limit); end-of-day job (flatten-verify + Slack daily recap + log commit).
- **Post-mortem**: every trade logged with thesis, stop, target, outcome. Weekly Slack report: expectancy/trade, profit factor, win rate with avg win:loss, max drawdown, vs. SPY buy-and-hold baseline. Lessons feed the next research cycle.

## 4. Phases

**Phase 0 — Accounts & skeleton** *(1 session)*
Repo, heartbeat workflow, Alpaca paper keys wired. *Done when: heartbeat posts account equity to Slack.*

**Phase 1 — Backtest harness** *(2–3 sessions)*
Pull 2+ years of 5-min bars for the universe; vectorbt harness; pessimistic cost model (spread + 2¢/share slippage); walk-forward validation, not one lucky window.
*GATE: at least one strategy shows positive net expectancy across walk-forward windows. If none survive, we iterate or stop — deploying a negative-expectancy bot to paper just automates losing.*

**Phase 2 — Paper execution engine** *(1–2 sessions)*
Risk caps, bracket orders, session loops, per-trade Slack alerts.
*Done when: a full simulated session runs end-to-end unattended.*

**Phase 3 — THE MONTH** *(21 sessions, zero human touches)*
Success criteria pre-registered before day 1 — no moving goalposts:
- Mechanical: 100% autonomous sessions, zero risk-cap breaches, complete logs
- Statistical: ≥60 trades, positive net expectancy after modeled costs, profit factor ≥ 1.15, max DD ≤ 6%

**Phase 4 — Verdict & translation**
Convert measured expectancy into $/day = edge(R after fills) x risk/trade x trades/day, at each capital level; state it honestly (near-zero today); compare against the $50-150/day yardstick; decide: extend / iterate / kill. Never scale capital on an unvalidated edge.

## 5. Gates before live money is even discussed

- ≥3 months of positive paper results after costs (the 1-month run is a checkpoint, not the gate)
- **Immigration attorney + DSO written sign-off — non-negotiable**, before any funded account (carried over from the Kalshi roadmap)
- Your explicit manual approval — the bot never gets this decision
- FYI: the old $25k pattern-day-trader minimum was **eliminated June 4, 2026** (FINRA moved to real-time intraday margin; brokers phase in through Oct 2027). Capital rules are now risk-based — but the math table in §1 still governs what's actually achievable.

## 6. Costs

$0 for everything that matters: Alpaca paper, IEX data, GitHub Actions. ~$5/mo Claude API for the weekly research/post-mortem cycle only — the trade loop is deterministic rules with no LLM in the hot path. Optional $99/mo SIP data, only if Phase 1 proves we need it.

---

*Not financial advice. Honest expectation-setting: the most likely outcome is discovering these strategies don't clear costs — that is the system doing its job. The prize is a verified answer about edge, not a promised paycheck.*
