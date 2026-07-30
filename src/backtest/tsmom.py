"""Time-series momentum (diversified trend-following) - the ONE futures approach with
real, peer-reviewed + live evidence (Moskowitz, Ooi & Pedersen 2012). RESEARCH ONLY.

Pure, works in RETURN space -> fully unit-testable offline, independent of contract
multipliers (those matter for live sizing, not for measuring the risk-adjusted edge):
  signal : sign of each market's trailing `lookback`-day return (+1 long / -1 short)
  sizing : inverse-volatility (each market scaled to a target vol -> equal risk;
           diversification is where the Sharpe comes from)
  lag    : signal & vol lagged one day -> no lookahead
  costs  : charged on turnover (|weight change|) each day
"""

import numpy as np
import pandas as pd

ANN = 252


def trailing_sign(prices, lookback):
    ret = prices / prices.shift(lookback) - 1.0
    return np.sign(ret)


def realized_vol(daily_returns, window):
    return daily_returns.rolling(window).std() * np.sqrt(ANN)


def market_weights(prices, daily_returns, lookback, vol_window, target_vol):
    sig = trailing_sign(prices, lookback)
    rv = realized_vol(daily_returns, vol_window).replace(0.0, np.nan)
    w = sig * (target_vol / rv)
    return w.shift(1)   # trade on yesterday's info


def backtest(prices_df, lookback=252, vol_window=60, target_vol=0.10,
             cost_per_turnover=0.0, portfolio_vol_target=None):
    rets = prices_df.pct_change()
    weights = {m: market_weights(prices_df[m], rets[m], lookback, vol_window, target_vol)
               for m in prices_df.columns}
    w = pd.DataFrame(weights)
    active = w.notna().sum(axis=1).replace(0, np.nan)
    gross = (w * rets).sum(axis=1) / active
    turnover = w.diff().abs().sum(axis=1) / active
    net = (gross - turnover.fillna(0.0) * cost_per_turnover).fillna(0.0)
    if portfolio_vol_target:
        realized = net.rolling(vol_window).std() * np.sqrt(ANN)
        scale = (portfolio_vol_target / realized).shift(1).clip(upper=5.0).fillna(1.0)
        net = net * scale
    return net, w


def metrics(daily_returns):
    r = pd.Series(daily_returns).dropna()
    if len(r) < 2 or r.std() == 0:
        return {"days": len(r), "sharpe": 0.0, "ann_return": 0.0, "ann_vol": 0.0,
                "max_drawdown": 0.0, "hit_rate": 0.0}
    sharpe = r.mean() / r.std() * np.sqrt(ANN)
    ann_return = (1 + r).prod() ** (ANN / len(r)) - 1
    ann_vol = r.std() * np.sqrt(ANN)
    equity = (1 + r).cumprod()
    max_dd = float((equity / equity.cummax() - 1.0).min())
    return {"days": int(len(r)), "sharpe": round(float(sharpe), 3),
            "ann_return": round(float(ann_return), 4), "ann_vol": round(float(ann_vol), 4),
            "max_drawdown": round(max_dd, 4), "hit_rate": round(float((r > 0).mean()), 3)}


def yearly(daily_returns):
    r = pd.Series(daily_returns).dropna()
    if r.empty:
        return {}
    r.index = pd.to_datetime(r.index)
    return {str(y): round(float((1 + g).prod() - 1), 4) for y, g in r.groupby(r.index.year)}
