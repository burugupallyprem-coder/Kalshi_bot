"""Opening-gap strategy - long or short is DERIVED from the overnight gap + mode.

At the open, gap = (day_open - prev_close) / prev_close. Only acts when |gap| >= min_gap.
  mode="fade": gap up -> short (expect fill back toward prior close); gap down -> long.
  mode="go":   gap up -> long  (continuation);                        gap down -> short.
Enters at the next bar's open; stop = stop_frac beyond entry; target = rr x risk.
Needs ctx["prev_close"] (a float) supplied by research.build_context. One trade/symbol-day.
"""

NAME = "gap"


def generate(day, params, ctx=None):
    mode = params.get("mode", "fade")
    min_gap = float(params.get("min_gap", 0.003))
    rr = float(params.get("rr", 1.5))
    stop_frac = float(params.get("stop_frac", 0.004))
    time_stop_bars = params.get("time_stop_bars")
    if ctx is None:
        return []
    prev_close = ctx.get("prev_close")
    if not prev_close or len(day) < 3:
        return []
    prev_close = float(prev_close)
    day_open = float(day.iloc[0]["open"])
    gap = (day_open - prev_close) / prev_close
    if abs(gap) < min_gap:
        return []
    up = gap > 0
    if mode == "fade":
        side = "short" if up else "long"
    else:
        side = "long" if up else "short"
    entry_est = float(day.iloc[1]["open"])
    stop = entry_est * (1 - stop_frac) if side == "long" else entry_est * (1 + stop_frac)
    return [{"entry_bar": 1, "stop": stop, "rr": rr, "side": side,
             "time_stop_bars": time_stop_bars, "reason": f"gap_{mode}_{side}"}]
