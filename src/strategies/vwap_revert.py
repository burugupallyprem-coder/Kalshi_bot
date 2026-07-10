"""VWAP mean-reversion (long-only).

Running VWAP from intraday bars. When close stretches more than z_entry
rolling-sigmas BELOW vwap (between start/end windows), buy the snap-back.
Target = vwap at signal. Stop = entry stretch extended by stop_sigmas.
One trade per symbol-day.
"""

NAME = "vwap_revert"


def generate(day, params):
    z_entry = params.get("z_entry", 1.5)
    stop_sigmas = params.get("stop_sigmas", 1.0)
    window = params.get("sigma_window", 12)
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
    for i in range(window, len(day) - 1):
        t = day.iloc[i]["et"].time()
        if (t.hour, t.minute) < (start_h, start_m):
            continue
        if (t.hour, t.minute) >= (end_h, end_m):
            break
        s = float(sigma.iloc[i])
        if s <= 0 or not s == s:  # nan guard
            continue
        if float(dev.iloc[i]) <= -z_entry * s:
            entry_est = float(day.iloc[i]["close"])
            stop = entry_est - stop_sigmas * s
            target = float(vwap.iloc[i])
            if target <= entry_est or stop >= entry_est:
                continue
            return [{"entry_bar": i + 1, "stop": stop, "target": target,
                     "reason": f"vwap_stretch_{z_entry}sig"}]
    return []
