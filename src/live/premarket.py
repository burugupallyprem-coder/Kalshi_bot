"""Phase 2.5: pre-market intelligence briefing.

Runs ~1 hour before the open. Gathers overnight gaps (latest pre-market trade
vs previous close) and headlines from the Alpaca News API, posts a
[PREMARKET] briefing to Slack, and writes data/premarket_flags.json.

Design principles:
- FLAGS ARE CODE, WORDS ARE LLM. Halt/skip decisions come from deterministic
  thresholds. When ANTHROPIC_API_KEY is set, Claude writes the briefing prose;
  it can never place trades or override risk logic.
- guard_mode in config.live.premarket:
    log_only (default) - flags are informational; the entry session trades
                         normally. We collect evidence of what enforcement
                         WOULD have done before letting it touch the strategy
                         that was validated without it.
    enforce            - entry session halts on halt_today and skips flagged
                         symbols.

Run: python -m src.live.premarket [--force]
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from src import slackbot
from src.alpaca_client import AlpacaClient

ROOT = Path(__file__).resolve().parent.parent.parent
ET = ZoneInfo("America/New_York")


def load_config():
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def compute_gaps(client, symbols):
    """% gap: latest (pre-market) trade vs previous daily close."""
    start = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    dailies = client.daily_bars(symbols, start)
    latest = client.latest_trades(symbols)
    gaps = {}
    for sym in symbols:
        bars = dailies.get(sym) or []
        trade = latest.get(sym) or {}
        price = trade.get("p")
        if not bars or not price:
            continue
        prev_close = float(bars[-1]["c"])
        if prev_close <= 0:
            continue
        gaps[sym] = round((float(price) - prev_close) / prev_close * 100, 2)
    return gaps


def compute_flags(gaps, universe, pm_cfg, today):
    halt = abs(gaps.get("SPY", 0.0)) >= float(pm_cfg.get("halt_spy_gap_pct", 1.5))
    skip = sorted(s for s in universe
                  if abs(gaps.get(s, 0.0)) >= float(pm_cfg.get("skip_symbol_gap_pct", 4.0)))
    return {"date": today, "halt_today": halt, "skip_symbols": skip, "gaps": gaps}


def rule_based_briefing(gaps, headlines, flags):
    movers = sorted(gaps.items(), key=lambda kv: -abs(kv[1]))[:6]
    lines = ["*[PREMARKET]* " + flags["date"]]
    lines.append("Overnight gaps: " + ", ".join(f"{s} {g:+.1f}%" for s, g in movers))
    if headlines:
        lines.append("Headlines:")
        for h in headlines[:6]:
            syms = ",".join(h.get("symbols") or [])[:30]
            lines.append(f"- ({syms}) {h.get('headline', '')[:110]}")
    else:
        lines.append("Headlines: none fetched")
    return "\n".join(lines)


def llm_briefing(gaps, headlines, flags, model):
    """Claude writes the prose. Returns None on any failure (fallback kicks in)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        material = {
            "overnight_gaps_pct": gaps,
            "headlines": [{"symbols": h.get("symbols"), "headline": h.get("headline")}
                          for h in headlines[:25]],
            "risk_flags_decided_by_code": {k: flags[k] for k in ("halt_today", "skip_symbols")},
        }
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 500,
                  "messages": [{"role": "user", "content":
                      "You brief a paper-trading bot owner before the US open. "
                      "Using ONLY the data below, write <=120 words: overnight tone, "
                      "top movers among the universe, notable headlines, and anything "
                      "unusual an opening-range-breakout strategy should be aware of "
                      "today. Plain language, no advice, no predictions of prices. "
                      "Do not invent facts.\n\n" + json.dumps(material)}]},
            timeout=45,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"].strip()
        return f"*[PREMARKET]* {flags['date']} (Claude briefing)\n{text}"
    except Exception as e:
        print(f"[premarket] LLM briefing failed, using rule-based: {e}")
        return None


def minutes_to_open(clock):
    if clock.get("is_open"):
        return -1
    try:
        nxt = datetime.fromisoformat(clock["next_open"].replace("Z", "+00:00"))
        return (nxt - datetime.now(timezone.utc)).total_seconds() / 60.0
    except Exception:
        return None


def run(force=False):
    cfg = load_config()
    pm_cfg = (cfg.get("live") or {}).get("premarket") or {}
    if not pm_cfg.get("enabled", True) and not force:
        print("[premarket] disabled in config")
        return
    client = AlpacaClient()  # paper-locked
    clock = client.clock()
    mto = minutes_to_open(clock)
    if not force:
        if mto is None or mto < 0 or mto > 100 or mto < 10:
            print(f"[premarket] not the pre-open window (minutes to open: {mto}) - skip")
            return
    today = datetime.now(ET).strftime("%Y-%m-%d")
    universe = cfg["universe"]
    gaps = compute_gaps(client, universe)
    start_iso = (datetime.now(timezone.utc) - timedelta(hours=16)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        headlines = client.news(universe, start_iso, limit=50)
    except Exception as e:
        print(f"[premarket] news fetch failed: {e}")
        headlines = []
    flags = compute_flags(gaps, universe, pm_cfg, today)

    out = ROOT / "data" / "premarket_flags.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(flags, indent=2), encoding="utf-8")

    briefing = (llm_briefing(gaps, headlines, flags, pm_cfg.get("llm_model", "claude-haiku-4-5-20251001"))
                or rule_based_briefing(gaps, headlines, flags))
    guard = pm_cfg.get("guard_mode", "log_only")
    if flags["halt_today"] or flags["skip_symbols"]:
        action = "ENFORCED" if guard == "enforce" else "log-only (not enforced yet)"
        briefing += (f"\nFlags [{action}]: halt_today={flags['halt_today']}, "
                     f"skip={flags['skip_symbols'] or 'none'}")
    else:
        briefing += "\nFlags: none - normal session."
    slackbot.post(briefing)
    print(f"[premarket] done - halt={flags['halt_today']} skip={flags['skip_symbols']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="run outside the pre-open window")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
