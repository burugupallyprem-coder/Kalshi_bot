"""Opening-range FADE - intraday mean-reversion (the economic opposite of ORB).

When price extends beyond the opening range by `ext_frac`, FADE it (short an up-extension,
long a down-extension), betting on reversion back toward the range. One trade/symbol-day.
`side` = which fades to take: short (fade up-moves) or long (fade down-moves).
"""

NAME = "or_fade"


def generate(day, params, ctx=None):
    side = params.get("side", "short")
    open_bars = int(params.get("open_bars", 3))
    cutoff = params.get("cutoff_et", "11:30")
    rr = float(params.get("rr", 1.0))
    ext = float(params.get("ext_frac", 0.003))
    max_risk_frac = float(params.get("max_risk_frac", 0.02))
    if len(day) < open_bars + 2:
        return []
    rng = day.iloc[:open_bars]
    hi, lo = float(rng["high"].max()), float(rng["low"].min())
    if hi <= lo:
        return []
    ch, cm = [int(x) for x in cutoff.split(":")]
    for i in range(open_bars, len(day) - 1):
        row = day.iloc[i]
        t = row["et"].time()
        if (t.hour, t.minute) >= (ch, cm):
            break
        c, h, l = float(row["close"]), float(row["high"]), float(row["low"])
        if side == "short" and c >= hi * (1 + ext):
            stop = h * (1 + ext)
            if stop <= c or (stop - c) / c > max_risk_frac:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "rr": rr, "side": "short",
                     "time_stop_bars": params.get("time_stop_bars"), "reason": "or_fade_short"}]
        if side == "long" and c <= lo * (1 - ext):
            stop = l * (1 - ext)
            if stop >= c or (c - stop) / c > max_risk_frac:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "rr": rr, "side": "long",
                     "time_stop_bars": params.get("time_stop_bars"), "reason": "or_fade_long"}]
    return []
