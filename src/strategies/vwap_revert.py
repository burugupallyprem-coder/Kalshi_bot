"""VWAP mean-reversion - long or short (params["side"]).

LONG: close stretched z_entry sigmas BELOW vwap -> buy the snap-back, target
vwap. SHORT: stretched ABOVE vwap -> short the fade, target vwap.
Optional `chop_filter`: require >= 2 vwap crosses today (range-bound day).
Optional `time_stop_bars`. One trade per symbol-day.
"""

NAME = "vwap_revert"


def generate(day, params):
    side = params.get("side", "long")
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
        stretched = (float(dev.iloc[i]) <= -z_entry * s) if side == "long" \
            else (float(dev.iloc[i]) >= z_entry * s)
        if stretched:
            entry_est = float(day.iloc[i]["close"])
            target = float(vwap.iloc[i])
            if side == "long":
                stop = entry_est - stop_sigmas * s
                ok = target > entry_est and stop < entry_est
            else:
                stop = entry_est + stop_sigmas * s
                ok = target < entry_est and stop > entry_est
            if not ok:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "target": target, "side": side,
                     "time_stop_bars": params.get("time_stop_bars"),
                     "reason": f"vwap_{side}_fade"}]
    return []
