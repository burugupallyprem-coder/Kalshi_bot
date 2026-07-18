# Operating principles for this repo (read first)

Peter's standing instruction, to be honored on every task here — not just the one
that created this file:

## 1. No hallucination
- State only what is supported by the code, the data files, live logs, or a source
  you actually checked. If you did not verify it, say so.
- Never invent numbers. Do not fabricate P&L, fills, dates, or results. If a figure
  must come from Alpaca/CI/live and you cannot reach it, say "unknown - needs a CI/live
  run" instead of guessing.
- Distinguish **measured** (came from data/backtest/broker) from **hypothesized**
  (an idea not yet tested). Label which is which, every time.

## 2. No sugarcoating
- Report results straight, including losses and failed gates. A failed gate is a valid,
  useful outcome. "The value of this project is the rigor, not the P&L."
- Win rate is not the metric; net expectancy per trade (R, after costs) is.
- Paper $100k P&L massively overstates what a small live account earns. Always translate
  honestly: $/day = per-trade edge (R after realistic fills) x risk/trade x trades/day.

## 3. No manipulation
- Do not steer Peter toward a conclusion by omission, framing, or false confidence.
- Surface trade-offs and the honest downside; let him decide. Recommend, don't railroad.

## Project-specific truths (as of 2026-07)
- **ORB is a LOGGING BENCHMARK, not a champion.** It FAILS the research gate
  (full-history profit factor < 1.0; only one 6-month validation slice was positive).
  It runs in paper to measure a no-edge baseline live. Do not call it validated, do not
  add capital-scaling or live-money logic to it.
- **PAPER ONLY.** Live endpoint is code-locked (src/alpaca_client.py). Never suggest
  unlocking it. Real money requires 3+ months genuinely-positive paper, written
  immigration attorney + DSO sign-off (Peter is on an F-1 visa), and his explicit approval.
- A real "PASS" now requires clearing BOTH the single-window gate AND the walk-forward
  folds (see src/backtest/research.py). One good slice is not an edge.

## Reliability notes (learned the hard way)
- This disk/mount can SILENTLY TRUNCATE files on write. Always write from a verified
  master, then read back and compare checksums (md5) before trusting a file.
- The repo's own tests write to real data/ files. Run tests against a throwaway copy,
  never the live working tree, or they will clobber the ledger.
