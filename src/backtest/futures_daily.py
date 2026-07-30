"""Daily diversified futures loader for TSMOM - Databento continuous, roll-aware.
RESEARCH ONLY.

Roll handling matters for trend signals: a naive continuous close has price JUMPS at
each contract roll that would fake a trend. So we chain WITHIN-CONTRACT daily returns
(detecting rolls via instrument_id changes) and rebuild a clean synthetic price series.
Cheap: daily bars cost ~nothing.

Returns a DataFrame indexed by date, one column of roll-adjusted prices per market.
"""

import os
import numpy as np
import pandas as pd


def _client(key=None):
    import databento as db
    return db.Historical(key or os.environ["DATABENTO_API_KEY"])


def _roll_adjusted_prices(df_market):
    """df_market: rows with ts_event(date), close, instrument_id for ONE market, sorted.
    Skip the return across a roll (instrument_id change) so roll gaps aren't fake trends."""
    d = df_market.sort_values("date").reset_index(drop=True)
    ret = d["close"] / d["close"].shift(1) - 1.0
    same_contract = d["instrument_id"] == d["instrument_id"].shift(1)
    ret = ret.where(same_contract, 0.0)          # roll day -> no return
    ret.iloc[0] = 0.0
    price = 100.0 * (1.0 + ret).cumprod()
    return pd.Series(price.values, index=pd.to_datetime(d["date"]))


def load(universe, cfg):
    ts = cfg["tsmom"]
    dbt = ts["databento"]
    # historical plan does not serve the most recent ~day (needs live sub); end a
    # week back to stay safely inside the historical window (irrelevant over 16 yrs).
    end = ts.get("end") or (pd.Timestamp.utcnow() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    conts = [f"{s}{dbt.get('continuous_suffix', '.v.0')}" for s in universe]
    client = _client()
    start = ts["start"]
    try:   # best-effort: never request before the dataset's available start
        rng = client.metadata.get_dataset_range(dataset=dbt.get("dataset", "GLBX.MDP3"))
        avail = str(rng.get("start", rng) if isinstance(rng, dict) else rng)[:10]
        if avail and avail > start:
            print(f"[futures_daily] clamping start {start} -> dataset start {avail}", flush=True)
            start = avail
    except Exception as e:
        print(f"[futures_daily] dataset-range check skipped ({e})", flush=True)
    if not ts.get("skip_cost_check", False):
        cost = float(client.metadata.get_cost(
            dataset=dbt.get("dataset", "GLBX.MDP3"), symbols=conts, stype_in="continuous",
            schema="ohlcv-1d", start=start, end=end))
        cap = float(ts.get("max_cost_usd", 5.0))
        print(f"[futures_daily] Databento estimated cost: ${cost:.4f} (cap ${cap}, credit $125)", flush=True)
        if cost > cap:
            raise RuntimeError(f"cost ${cost:.2f} exceeds cap ${cap} - aborting")
    data = client.timeseries.get_range(
        dataset=dbt.get("dataset", "GLBX.MDP3"), symbols=conts, stype_in="continuous",
        schema="ohlcv-1d", start=start, end=end)
    raw = data.to_df().reset_index()
    root = {f"{s}{dbt.get('continuous_suffix', '.v.0')}": s for s in universe}
    raw["mkt"] = raw["symbol"].map(lambda x: root.get(x, str(x).split(".")[0]))
    raw["date"] = pd.to_datetime(raw["ts_event"]).dt.date
    print(f"[futures_daily] fetched {len(raw):,} daily rows, markets: {sorted(raw['mkt'].unique())}", flush=True)
    cols = {}
    for mkt, g in raw.groupby("mkt"):
        cols[mkt] = _roll_adjusted_prices(g[["date", "close", "instrument_id"]])
    prices = pd.DataFrame(cols).sort_index()
    prices = prices.ffill().dropna(how="all")
    print(f"[futures_daily] price panel: {prices.shape[0]} days x {prices.shape[1]} markets", flush=True)
    return prices
