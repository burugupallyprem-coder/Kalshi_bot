# stock-trader-bot

Autonomous stock day-trading research bot. **Paper account only** — the code contains a hard PAPER LOCK: the live endpoint raises an error unless an unlock phrase is set, which stays off until every roadmap gate passes (3+ months positive paper, immigration attorney + DSO sign-off, explicit owner approval).

Pipeline: **Alpaca (paper) + Slack + GitHub Actions.**

## Setup (one time, ~10 min)

1. Push this folder to your GitHub repo (see commands below).
2. Add four repo secrets (Settings -> Secrets and variables -> Actions):

| Secret | Value |
|---|---|
| `ALPACA_API_KEY_ID` | Alpaca **paper** API key ID |
| `ALPACA_SECRET_KEY` | Alpaca **paper** secret key |
| `SLACK_BOT_TOKEN` | Slack bot token (starts `xoxb-`) |
| `SLACK_CHANNEL_ID` | Channel ID (looks like `C0123ABCD` - not the channel name) |

3. Slack: the bot needs the `chat:write` scope and must be **invited to the channel** (`/invite @YourBotName` in the channel).
4. Actions tab -> `bot` workflow -> Run workflow -> mode `heartbeat`.

Expected in Slack within ~1 min:

```
[HEARTBEAT] 2026-07-10 14:02 UTC
Account: ACTIVE - equity $100,000.00 - buying power $200,000.00 - blocked: no
Market: OPEN (closes 2026-07-10T20:00:00-04:00)
stock-trader-bot Phase 0 is alive. Paper account only.
```

A pre-market heartbeat also runs automatically weekdays at 13:00 UTC.

### Troubleshooting first run
- `Slack API error: not_in_channel` -> invite the bot to the channel.
- `channel_not_found` -> use the channel **ID** (channel details -> bottom), not `#name`.
- HTTP 401/403 from Alpaca -> regenerate keys and make sure they are **paper** keys (toggle top-left of the Alpaca dashboard).

### Push commands

```
cd stock-trader-bot
git init
git add .
git commit -m "Phase 0: Alpaca paper client, Slack alerts, heartbeat workflow"
git branch -M main
git remote add origin https://github.com/burugupallyprem-coder/<YOUR-RENAMED-REPO>.git
git push -u origin main --force
```

(`--force` replaces the old Kalshi contents - intended.)

## Local run

```bash
pip install -r requirements.txt
python tests/test_offline.py                     # offline unit tests
ALPACA_API_KEY_ID=... ALPACA_SECRET_KEY=... python -m src.main --heartbeat
```

Without Slack secrets set, messages print to stdout.

## Layout

```
src/alpaca_client.py   Alpaca REST client (paper-locked)
src/slackbot.py        Slack chat.postMessage alerts
src/main.py            --heartbeat / --status
config.yaml            Phase 1 will add universe, strategy params, risk caps
.github/workflows/bot.yml
```

## Roadmap position (see day-trading-bot-roadmap.md)

- **Phase 0 - DONE** (heartbeat verified 2026-07-10).
- **Phase 1 (built)** - backtest harness: `python -m src.backtest.run`, or the `backtest` Actions workflow (manual + Saturdays 14:00 UTC). Downloads 2 years of 5-min bars, runs all three candidate strategies (opening-range breakout, VWAP mean-reversion, momentum continuation) through the no-lookahead simulator with pessimistic costs, writes `reports/backtest_*.md` + per-trade CSVs, posts a [BACKTEST] summary to Slack. GATE (config.yaml): >=100 trades, >=0.05R expectancy, profit factor >=1.15, >=60% quarters positive - only PASSing strategies are eligible for Phase 2 paper deployment.
- **Phase 2 (built)** - paper execution of the ORB **logging benchmark** (open_bars=3, rr=1.5, cutoff 10:30 ET). ORB is NOT a validated edge - it FAILS the gate (full-history PF < 1.0; only one 6-month validation slice was positive). It runs in paper only to MEASURE a no-edge baseline live, not because it is expected to profit. `trade` workflow runs the entry session each morning and the EOD flatten at 15:45 ET (DST-safe double crons). Server-side bracket orders; 0.5% risk/trade; max 3 positions; worst-case day structurally ~ -1.5%; never holds overnight. [TRADE] and [EOD] alerts to Slack; daily log committed to data/paper_days.csv.
- Phase 3 - THE MONTH: 21 sessions, zero human touches, pre-registered success criteria.
- Phase 4 - verdict: translate measured edge into $/day per capital level, honestly.

House rules: win rate is not the metric; expectancy after costs is. Paper P&L on the default $100k account overstates what a small live account would earn - dollars = edge x capital.
