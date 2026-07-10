"""VWAP mean-reversion (long-only).

Buy when close stretches more than z_entry rolling-sigmas BELOW running VWAP.
Target = VWAP at signal. Stop = entry - stop_sigmas x sigma.
Optional `chop_filter`: only trade if price already crossed VWAP >= 2 times
today (range-bound day - mean reversion's home turf; skips strong trend days).
Optional `time_stop_bars`: bail out if reversion hasn't happened in N bars.
One trade/symbol-day.
"""

NAME = "vwap_revert"


def generate(day, params):
    z_entry = float(params.get("z_entry", 1.5))
    stop_sigmas = float(params.get("stop_sigmas", 1.0))
    window = int(params.get("sigma_window", 12))
    chop_filter = bool(params.get("chop_filter", False))
    start_h, start_m = [int(x) for x in params.get("start_et", "10:00").split(":")]
    end_h, end_m = [int(x) for x in params.get("end_et", "15:00").split(":")]
    if len(day) < window + 2:
        return []
    tp = (day["high"] + day["low"] + day["close"]) / 3.0
    cum_vol = day["volume"].cumsum()
    if (cum_vol <= 0).any():
        return []
    vwap = (tp * day["volume"]).cumsum() / cum_vol
    dev = day["close"] - vwap
    sigma = dev.rolling(window).std()
    crosses = ((dev.shift(1) * dev) < 0).cumsum()
    for i in range(window, len(day) - 1):
        t = day.iloc[i]["et"].time()
        if (t.hour, t.minute) < (start_h, start_m):
            continue
        if (t.hour, t.minute) >= (end_h, end_m):
            break
        s = float(sigma.iloc[i])
        if s <= 0 or s != s:
            continue
        if chop_filter and int(crosses.iloc[i]) < 2:
            continue
        if float(dev.iloc[i]) <= -z_entry * s:
            entry_est = float(day.iloc[i]["close"])
            stop = entry_est - stop_sigmas * s
            target = float(vwap.iloc[i])
            if target <= entry_est or stop >= entry_est:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "target": target,
                     "time_stop_bars": params.get("time_stop_bars"),
                     "reason": "vwap_stretch"}]
    return []
