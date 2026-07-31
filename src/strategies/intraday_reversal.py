"""Intraday reversal - fade the morning move. At `decide_bar` (~midday), if the day's
return from the open exceeds `move_frac`, enter the OPPOSITE side betting on an afternoon
reversion. One trade/symbol-day; the engine flattens by session end.
`side` = short (fade up-days) or long (fade down-days)."""

NAME = "intraday_reversal"


def generate(day, params, ctx=None):
    side = params.get("side", "short")
    decide_bar = int(params.get("decide_bar", 24))   # ~noon on 5-min bars
    move_frac = float(params.get("move_frac", 0.005))
    rr = float(params.get("rr", 1.0))
    max_risk_frac = float(params.get("max_risk_frac", 0.02))
    if len(day) < decide_bar + 2:
        return []
    o = float(day.iloc[0]["open"])
    c = float(day.iloc[decide_bar]["close"])
    ret = c / o - 1.0
    if side == "short" and ret >= move_frac:
        stop = float(day.iloc[:decide_bar + 1]["high"].max())
        if stop <= c or (stop - c) / c > max_risk_frac:
            return []
        return [{"entry_bar": decide_bar + 1, "stop": stop, "rr": rr, "side": "short",
                 "time_stop_bars": params.get("time_stop_bars"), "reason": "intraday_rev_short"}]
    if side == "long" and ret <= -move_frac:
        stop = float(day.iloc[:decide_bar + 1]["low"].min())
        if stop >= c or (c - stop) / c > max_risk_frac:
            return []
        return [{"entry_bar": decide_bar + 1, "stop": stop, "rr": rr, "side": "long",
                 "time_stop_bars": params.get("time_stop_bars"), "reason": "intraday_rev_long"}]
    return []
