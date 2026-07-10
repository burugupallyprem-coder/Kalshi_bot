"""Opening-range breakout (long-only).

First `open_bars` 5-min bars define the range. If a later bar CLOSES above the
range high before `cutoff_et`, go long at the next bar's open. Stop = range
low. Target = entry + rr x risk. Optional `vol_confirm`: breakout bar volume
must exceed 1.5x the average opening-range bar volume. One trade/symbol-day.
"""

NAME = "orb"


def generate(day, params):
    open_bars = int(params.get("open_bars", 3))
    cutoff = params.get("cutoff_et", "11:30")
    rr = float(params.get("rr", 2.0))
    max_risk_frac = float(params.get("max_risk_frac", 0.02))
    vol_confirm = bool(params.get("vol_confirm", False))
    if len(day) < open_bars + 2:
        return []
    rng = day.iloc[:open_bars]
    rng_high = float(rng["high"].max())
    rng_low = float(rng["low"].min())
    rng_vol = float(rng["volume"].mean())
    if rng_high <= rng_low:
        return []
    ch, cm = [int(x) for x in cutoff.split(":")]
    for i in range(open_bars, len(day) - 1):
        t = day.iloc[i]["et"].time()
        if (t.hour, t.minute) >= (ch, cm):
            break
        row = day.iloc[i]
        if float(row["close"]) > rng_high:
            if vol_confirm and rng_vol > 0 and float(row["volume"]) < 1.5 * rng_vol:
                return []
            close = float(row["close"])
            risk = close - rng_low
            if risk <= 0 or risk / close > max_risk_frac:
                return []
            return [{"entry_bar": i + 1, "stop": rng_low, "rr": rr,
                     "time_stop_bars": params.get("time_stop_bars"),
                     "reason": "orb_breakout"}]
    return []
