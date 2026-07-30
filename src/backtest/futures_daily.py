"""Daily diversified futures loader for TSMOM - Databento PARENT symbology + LOCAL roll.
RESEARCH ONLY.

Why parent, not continuous: Databento's server-side continuous (.v.0) roll-resolution
over 16 years is brutally slow (~25 min/symbol). Parent ('ES.FUT') returns every raw
contract's daily bars in SECONDS. We then build the volume-continuous series ourselves:
per day pick the most-liquid contract, and chain WITHIN-CONTRACT returns so roll gaps
don't fake trends. Fast, cheap, and identical in spirit to a volume-roll continuous.

Returns a DataFrame indexed by date, one roll-adjusted price column per market.
"""

import os
import numpy as np
import pandas as pd


def _with_retry(fn, tries=3, sleep=4):
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[futures_daily] attempt {i+1}/{tries} failed ({e}); retrying...", flush=True)
            time.sleep(sleep * (i + 1))
    raise last


def _client(key=None):
    import databento as db
    return db.Historical(key or os.environ["DATABENTO_API_KEY"])


def _roll_adjusted_prices(active):
    """active: rows (date, close, instrument_id) for the most-liquid contract each day.
    Chain within-contract returns; skip the return across a roll (instrument change)."""
    d = active.sort_values("date").reset_index(drop=True)
    ret = d["close"] / d["close"].shift(1) - 1.0
    same = d["instrument_id"] == d["instrument_id"].shift(1)
    ret = ret.where(same, 0.0)
    ret.iloc[0] = 0.0
    price = 100.0 * (1.0 + ret).cumprod()
    return pd.Series(price.values, index=pd.to_datetime(d["date"]))


def load(universe, cfg):
    ts = cfg["tsmom"]
    dbt = ts["databento"]
    dataset = dbt.get("dataset", "GLBX.MDP3")
    end = ts.get("end") or (pd.Timestamp.utcnow() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    client = _client()
    start = ts["start"]
    try:   # never request before the dataset's available start
        rng = client.metadata.get_dataset_range(dataset=dataset)
        avail = str(rng.get("start", rng) if isinstance(rng, dict) else rng)[:10]
        if avail and avail > start:
            print(f"[futures_daily] clamping start {start} -> {avail}", flush=True)
            start = avail
    except Exception as e:
        print(f"[futures_daily] dataset-range check skipped ({e})", flush=True)

    parents = [f"{m}.FUT" for m in universe]
    if not ts.get("skip_cost_check", False):
        cost = float(_with_retry(lambda: client.metadata.get_cost(
            dataset=dataset, symbols=parents, stype_in="parent",
            schema="ohlcv-1d", start=start, end=end)))
        cap = float(ts.get("max_cost_usd", 10.0))
        print(f"[futures_daily] Databento estimated cost: ${cost:.4f} (cap ${cap}, credit $125)", flush=True)
        if cost > cap:
            raise RuntimeError(f"cost ${cost:.2f} exceeds cap ${cap} - aborting")

    cols = {}
    for mkt in universe:
        try:
            df = _with_retry(lambda p=f"{mkt}.FUT": client.timeseries.get_range(
                dataset=dataset, symbols=[p], stype_in="parent",
                schema="ohlcv-1d", start=start, end=end).to_df())
        except Exception as e:
            print(f"[futures_daily] {mkt}: giving up ({e}) - skipping", flush=True)
            continue
        if df is None or len(df) == 0:
            print(f"[futures_daily] {mkt}: 0 rows - skipping", flush=True)
            continue
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["ts_event"]).dt.date
        # per day, the active contract = the one with the most volume (volume-continuous)
        active_idx = df.groupby("date")["volume"].idxmax()
        active = df.loc[active_idx, ["date", "close", "instrument_id"]]
        cols[mkt] = _roll_adjusted_prices(active)
        print(f"[futures_daily] {mkt}: {len(df):,} rows -> {len(active):,} daily (active contract)", flush=True)
    if not cols:
        raise RuntimeError("no markets loaded - all per-symbol requests failed")
    prices = pd.DataFrame(cols).sort_index().ffill().dropna(how="all")
    print(f"[futures_daily] price panel: {prices.shape[0]} days x {prices.shape[1]} markets", flush=True)
    return prices
