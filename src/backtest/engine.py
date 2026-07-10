"""Bar-driven day-trade simulator. Long-only v1.

Signal contract: strategies inspect bars up to index i and emit
{"entry_bar": i + 1, ...} - the trade fills at the OPEN of that next bar.
No lookahead is possible because signal logic never sees entry_bar's data.

Honesty rules baked in:
- Stop is checked BEFORE target when both could hit in the same bar.
- The entry bar itself can stop out (no free pass).
- Gap through stop fills at the open (worse for us); gap through target
  fills at the open (better) - both realistic.
- Optional time-stop: exit at bar close after N bars held with no resolution.
- Slippage charged on both sides. Everything flat by the configured time.
- If the data ends early (halt/half session), position closes at last bar.
- Fixed equity per trade (no compounding) so expectancy stats stay clean.
"""

import math
from dataclasses import dataclass
from datetime import time as dtime


@dataclass
class Trade:
    symbol: str
    strategy: str
    date: str
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    shares: int
    stop: float
    target: float
    pnl: float
    r_multiple: float
    exit_reason: str
    signal_reason: str


def _size(entry, stop, cfg):
    equity = cfg["risk"]["equity"]
    risk_dollars = equity * cfg["risk"]["risk_pct"] / 100.0
    per_share = entry - stop
    if per_share <= 0:
        return 0
    shares = math.floor(risk_dollars / per_share)
    max_value = equity * cfg["risk"]["max_position_pct"] / 100.0
    shares = min(shares, math.floor(max_value / entry))
    return max(shares, 0)


def _close(trades, pos, row, exit_px, reason, strategy_name):
    risk_ps = pos["entry"] - pos["stop"]
    pnl = (exit_px - pos["entry"]) * pos["shares"]
    trades.append(Trade(
        symbol=str(row.get("symbol", "?")), strategy=strategy_name,
        date=str(row["et"].date()), entry_time=pos["entry_time"],
        exit_time=str(row["et"].time()), entry=round(pos["entry"], 4),
        exit=round(exit_px, 4), shares=pos["shares"],
        stop=round(pos["stop"], 4), target=round(pos["target"], 4),
        pnl=round(pnl, 2),
        r_multiple=round((exit_px - pos["entry"]) / risk_ps, 3) if risk_ps > 0 else 0.0,
        exit_reason=reason, signal_reason=pos["reason"],
    ))


def simulate_day(day, signals, cfg, strategy_name):
    """day: DataFrame with symbol/open/high/low/close/et, reset_index. Long-only."""
    slip = cfg["costs"]["slippage_cents"] / 100.0
    hh, mm = [int(x) for x in cfg["risk"]["flat_by_et"].split(":")]
    flat_at = dtime(hh, mm)
    sig_by_bar = {}
    for s in signals:
        sig_by_bar.setdefault(int(s["entry_bar"]), s)  # first signal per bar wins

    trades = []
    pos = None
    n = len(day)
    for j in range(n):
        row = day.iloc[j]
        bar_time = row["et"].time()

        # 1) entry fills at THIS bar's open (signal was generated on bar j-1)
        if pos is None and j in sig_by_bar and bar_time < flat_at:
            sig = sig_by_bar[j]
            entry_px = float(row["open"]) + slip
            stop = float(sig["stop"])
            if entry_px > stop:
                target = sig.get("target")
                if target is None:
                    target = entry_px + float(sig["rr"]) * (entry_px - stop)
                shares = _size(entry_px, stop, cfg)
                if shares > 0:
                    pos = {"entry": entry_px, "stop": stop, "target": float(target),
                           "shares": shares, "entry_time": str(bar_time),
                           "reason": sig.get("reason", strategy_name),
                           "bars_held": 0,
                           "time_stop": sig.get("time_stop_bars")}

        # 2) exits on this bar (stop before target - conservative)
        if pos is not None:
            if bar_time >= flat_at:
                _close(trades, pos, row, float(row["open"]) - slip, "eod_flat", strategy_name)
                pos = None
            elif float(row["low"]) <= pos["stop"]:
                _close(trades, pos, row, min(float(row["open"]), pos["stop"]) - slip,
                       "stop", strategy_name)
                pos = None
            elif float(row["high"]) >= pos["target"]:
                _close(trades, pos, row, max(float(row["open"]), pos["target"]) - slip,
                       "target", strategy_name)
                pos = None
            elif pos["time_stop"] is not None and pos["bars_held"] >= int(pos["time_stop"]):
                _close(trades, pos, row, float(row["close"]) - slip, "time_stop", strategy_name)
                pos = None
            else:
                pos["bars_held"] += 1

    # 3) data ended with an open position (halt / half session) - close at last bar
    if pos is not None and n > 0:
        row = day.iloc[n - 1]
        _close(trades, pos, row, float(row["close"]) - slip, "data_end", strategy_name)

    return trades
