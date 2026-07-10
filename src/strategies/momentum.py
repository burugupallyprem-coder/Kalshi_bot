"""Momentum continuation (long-only).

Trend filter at confirm_bar (default 12 = 10:30 ET): close above both the
day's open and running VWAP, AND the last `hold_above` closes all above VWAP.
Entry: first later bar that tags VWAP (low <= vwap) but CLOSES back above it.
Stop = lowest low of the last `stop_lookback` bars. Target = entry + rr x risk.
Optional `time_stop_bars`. One trade/symbol-day.
"""

NAME = "momentum"


def generate(day, params):
    confirm_bar = int(params.get("confirm_bar", 12))
    rr = float(params.get("rr", 2.0))
    stop_lookback = int(params.get("stop_lookback", 6))
    hold_above = int(params.get("hold_above", 3))
    max_risk_frac = float(params.get("max_risk_frac", 0.015))
    if len(day) < confirm_bar + 3:
        return []
    tp = (day["high"] + day["low"] + day["close"]) / 3.0
    cum_vol = day["volume"].cumsum()
    if (cum_vol <= 0).any():
        return []
    vwap = (tp * day["volume"]).cumsum() / cum_vol
    day_open = float(day.iloc[0]["open"])
    c = float(day.iloc[confirm_bar]["close"])
    if not (c > day_open and c > float(vwap.iloc[confirm_bar])):
        return []
    for i in range(confirm_bar + 1, len(day) - 1):
        lo = max(0, i - hold_above)
        held = all(float(day.iloc[k]["close"]) > float(vwap.iloc[k]) for k in range(lo, i))
        if not held:
            continue
        v = float(vwap.iloc[i])
        if float(day.iloc[i]["low"]) <= v and float(day.iloc[i]["close"]) > v:
            entry_est = float(day.iloc[i]["close"])
            slo = max(0, i - stop_lookback + 1)
            stop = float(day.iloc[slo:i + 1]["low"].min())
            risk = entry_est - stop
            if risk <= 0 or risk / entry_est > max_risk_frac:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "rr": rr,
                     "time_stop_bars": params.get("time_stop_bars"),
                     "reason": "momo_vwap_pullback"}]
    return []
