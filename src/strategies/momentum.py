"""Momentum continuation - long or short (params["side"]).

LONG: at confirm_bar, close above day open AND vwap, last `hold_above` closes
above vwap; buy the first pullback that tags vwap but closes back above.
SHORT: mirrored - confirmed down-trend, short the first bounce that tags vwap
but closes back below. Stop = extreme of last `stop_lookback` bars.
Target = rr x risk. Optional `time_stop_bars`. One trade per symbol-day.
"""

NAME = "momentum"


def generate(day, params):
    side = params.get("side", "long")
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
    v_c = float(vwap.iloc[confirm_bar])
    trending = (c > day_open and c > v_c) if side == "long" else (c < day_open and c < v_c)
    if not trending:
        return []
    for i in range(confirm_bar + 1, len(day) - 1):
        lo = max(0, i - hold_above)
        if side == "long":
            held = all(float(day.iloc[k]["close"]) > float(vwap.iloc[k]) for k in range(lo, i))
        else:
            held = all(float(day.iloc[k]["close"]) < float(vwap.iloc[k]) for k in range(lo, i))
        if not held:
            continue
        v = float(vwap.iloc[i])
        row = day.iloc[i]
        if side == "long":
            tagged = float(row["low"]) <= v and float(row["close"]) > v
        else:
            tagged = float(row["high"]) >= v and float(row["close"]) < v
        if tagged:
            entry_est = float(row["close"])
            slo = max(0, i - stop_lookback + 1)
            stop = float(day.iloc[slo:i + 1]["low"].min()) if side == "long" \
                else float(day.iloc[slo:i + 1]["high"].max())
            risk = abs(entry_est - stop)
            if risk <= 0 or risk / entry_est > max_risk_frac:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "rr": rr, "side": side,
                     "time_stop_bars": params.get("time_stop_bars"),
                     "reason": f"momo_{side}_pullback"}]
    return []
