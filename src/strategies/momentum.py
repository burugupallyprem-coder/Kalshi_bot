"""Momentum continuation (long-only).

Trend filter at confirm_bar (default 12 = 10:30 ET): close above both the
day's open and running VWAP. Entry: first later bar that tags VWAP (low <=
vwap) but CLOSES back above it - buying the pullback in a confirmed uptrend.
Stop = lowest low of the last `stop_lookback` bars. Target = entry + rr x risk.
One trade per symbol-day.
"""

NAME = "momentum"


def generate(day, params):
    confirm_bar = params.get("confirm_bar", 12)
    rr = params.get("rr", 2.0)
    stop_lookback = params.get("stop_lookback", 6)
    max_risk_frac = params.get("max_risk_frac", 0.015)
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
        return []  # not a confirmed up-trend day
    for i in range(confirm_bar + 1, len(day) - 1):
        v = float(vwap.iloc[i])
        if float(day.iloc[i]["low"]) <= v and float(day.iloc[i]["close"]) > v:
            entry_est = float(day.iloc[i]["close"])
            lo = max(0, i - stop_lookback + 1)
            stop = float(day.iloc[lo:i + 1]["low"].min())
            risk = entry_est - stop
            if risk <= 0 or risk / entry_est > max_risk_frac:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "rr": rr,
                     "reason": "momo_vwap_pullback"}]
    return []
