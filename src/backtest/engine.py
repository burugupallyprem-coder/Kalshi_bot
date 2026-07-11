"""Bar-driven day-trade simulator. Long AND short (v2).

Signal contract: strategies inspect bars up to index i and emit
{"entry_bar": i + 1, "side": "long"|"short", ...} - fills at the OPEN of that
next bar. No lookahead: signal logic never sees entry_bar's data.

Direction is handled by a multiplier d (+1 long, -1 short). Slippage is always
charged AGAINST us: longs buy higher / sell lower; shorts sell lower / cover
higher. Shorts are simulated without borrow fees - fine for megacaps, noted in
reports; treat marginal short edges with extra suspicion.

Honesty rules baked in:
- Stop is checked BEFORE target when both could hit in the same bar.
- The entry bar itself can stop out (no free pass).
- Gap through stop fills at the open (worse for us); gap through target fills
  at the open (better) - both directions.
- Optional time-stop; everything flat by the configured time; data-end close.
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
    side: str = "long"


def _size(entry, stop, cfg):
    equity = cfg["risk"]["equity"]
    risk_dollars = equity * cfg["risk"]["risk_pct"] / 100.0
    per_share = abs(entry - stop)
    if per_share <= 0:
        return 0
    shares = math.floor(risk_dollars / per_share)
    max_value = equity * cfg["risk"]["max_position_pct"] / 100.0
    shares = min(shares, math.floor(max_value / entry))
    return max(shares, 0)


def _close(trades, pos, row, exit_px, reason, strategy_name):
    d = pos["d"]
    risk_ps = abs(pos["entry"] - pos["stop"])
    pnl = (exit_px - pos["entry"]) * pos["shares"] * d
    trades.append(Trade(
        symbol=str(row.get("symbol", "?")), strategy=strategy_name,
        date=str(row["et"].date()), entry_time=pos["entry_time"],
        exit_time=str(row["et"].time()), entry=round(pos["entry"], 4),
        exit=round(exit_px, 4), shares=pos["shares"],
        stop=round(pos["stop"], 4), target=round(pos["target"], 4),
        pnl=round(pnl, 2),
        r_multiple=round((exit_px - pos["entry"]) * d / risk_ps, 3) if risk_ps > 0 else 0.0,
        exit_reason=reason, signal_reason=pos["reason"],
        side="long" if d == 1 else "short",
    ))


def simulate_day(day, signals, cfg, strategy_name):
    """day: DataFrame with symbol/open/high/low/close/et, reset_index."""
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
            d = -1 if sig.get("side") == "short" else 1
            entry_px = float(row["open"]) + d * slip     # slip against us
            stop = float(sig["stop"])
            if d * (entry_px - stop) > 0:                # stop must be on the loss side
                target = sig.get("target")
                if target is None:
                    target = entry_px + d * float(sig["rr"]) * abs(entry_px - stop)
                shares = _size(entry_px, stop, cfg)
                if shares > 0:
                    pos = {"entry": entry_px, "stop": stop, "target": float(target),
                           "shares": shares, "entry_time": str(bar_time),
                           "reason": sig.get("reason", strategy_name), "d": d,
                           "bars_held": 0,
                           "time_stop": sig.get("time_stop_bars")}

        # 2) exits on this bar (stop before target - conservative)
        if pos is not None:
            d = pos["d"]
            stop_hit = (float(row["low"]) <= pos["stop"]) if d == 1 else (float(row["high"]) >= pos["stop"])
            tgt_hit = (float(row["high"]) >= pos["target"]) if d == 1 else (float(row["low"]) <= pos["target"])
            if bar_time >= flat_at:
                px = float(row["open"])
                _close(trades, pos, row, px - d * slip, "eod_flat", strategy_name)
                pos = None
            elif stop_hit:
                # gap through stop fills at the open (worse for us)
                px = min(float(row["open"]), pos["stop"]) if d == 1 else max(float(row["open"]), pos["stop"])
                _close(trades, pos, row, px - d * slip, "stop", strategy_name)
                pos = None
            elif tgt_hit:
                # gap through target fills at the open (better for us)
                px = max(float(row["open"]), pos["target"]) if d == 1 else min(float(row["open"]), pos["target"])
                _close(trades, pos, row, px - d * slip, "target", strategy_name)
                pos = None
            elif pos["time_stop"] is not None and pos["bars_held"] >= int(pos["time_stop"]):
                px = float(row["close"])
                _close(trades, pos, row, px - d * slip, "time_stop", strategy_name)
                pos = None
            else:
                pos["bars_held"] += 1

    # 3) data ended with an open position (halt / half session) - close at last bar
    if pos is not None and n > 0:
        row = day.iloc[n - 1]
        px = float(row["close"])
        _close(trades, pos, row, px - pos["d"] * slip, "data_end", strategy_name)

    return trades
