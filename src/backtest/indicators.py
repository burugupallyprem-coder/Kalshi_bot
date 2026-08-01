"""Classic charting indicators, computed natively in Python (no Pine Script, no
TradingView). All are standard, decades-old formulas and are strictly CAUSAL: the
value at bar t uses only closes up to and including t. Returns pandas Series/positions
aligned to the input index. Used by indicator_search.py. RESEARCH ONLY.
"""

import numpy as np
import pandas as pd


def rsi(close, period=14):
    """Wilder's RSI (0-100), causal."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    ag = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    al = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = ag / al.replace(0.0, np.nan)
    r = 100.0 - 100.0 / (1.0 + rs)
    r = r.mask((al == 0) & (ag > 0), 100.0)   # no losses over the window -> RSI 100
    return r.fillna(50.0)                       # flat (0 gain, 0 loss) -> neutral 50


def macd_lines(close, fast=12, slow=26, signal=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    macd = ef - es
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig


def bollinger(close, period=20, k=2.0):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


# ---- position generators (return a +1/-1/0 daily position Series, causal) ----

def bollinger_pos(close, period=20, k=2.0, mode="revert"):
    lo, mid, up = bollinger(close, period, k)
    pos = np.zeros(len(close)); state = 0
    c = close.values; lov = lo.values; miv = mid.values; upv = up.values
    for i in range(len(close)):
        if np.isnan(miv[i]):
            pos[i] = 0; continue
        if mode == "revert":
            if state == 0:
                if c[i] < lov[i]: state = 1
                elif c[i] > upv[i]: state = -1
            elif state == 1 and c[i] >= miv[i]: state = 0
            elif state == -1 and c[i] <= miv[i]: state = 0
        else:  # breakout
            if c[i] > upv[i]: state = 1
            elif c[i] < lov[i]: state = -1
            elif state == 1 and c[i] < miv[i]: state = 0
            elif state == -1 and c[i] > miv[i]: state = 0
        pos[i] = state
    return pd.Series(pos, index=close.index)


def rsi_pos(close, period=14, low=30, high=70):
    r = rsi(close, period).values
    pos = np.zeros(len(close)); state = 0
    for i in range(len(close)):
        if state == 0:
            if r[i] < low: state = 1
            elif r[i] > high: state = -1
        elif state == 1 and r[i] >= 50: state = 0
        elif state == -1 and r[i] <= 50: state = 0
        pos[i] = state
    return pd.Series(pos, index=close.index)


def macd_pos(close, fast=12, slow=26, signal=9):
    macd, sig = macd_lines(close, fast, slow, signal)
    return pd.Series(np.sign((macd - sig).values), index=close.index)


def fib_pos(close, lookback=20, retr=0.5, trend=50, hold=5):
    """Fibonacci-retracement continuation: in an up/down trend (vs trend-SMA), enter
    when price pulls back to the `retr` retracement of the last `lookback`-bar swing;
    hold `hold` bars. Causal (rolling max/min exclude the future)."""
    sma = close.rolling(trend).mean().values
    hi = close.rolling(lookback).max().values
    lo = close.rolling(lookback).min().values
    c = close.values
    pos = np.zeros(len(close)); hold_left = 0; cur = 0
    for i in range(len(close)):
        if hold_left > 0:
            pos[i] = cur; hold_left -= 1; continue
        cur = 0
        if np.isnan(sma[i]) or np.isnan(hi[i]) or hi[i] == lo[i]:
            pos[i] = 0; continue
        rng = hi[i] - lo[i]
        up_level = hi[i] - retr * rng      # pullback level in an uptrend
        dn_level = lo[i] + retr * rng      # pullback level in a downtrend
        if c[i] > sma[i] and c[i] <= up_level:
            cur = 1; hold_left = hold - 1
        elif c[i] < sma[i] and c[i] >= dn_level:
            cur = -1; hold_left = hold - 1
        pos[i] = cur
    return pd.Series(pos, index=close.index)
