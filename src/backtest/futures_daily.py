"""Daily diversified futures loader (Databento PARENT + LOCAL roll) with caching + a
choice of roll rule. RESEARCH ONLY.

Parent symbology returns raw contracts fast; we build the volume-continuous series
locally. Roll rules:
  naive  - each day, use the single most-liquid contract (jittery; can inject noise)
  smooth - only switch contracts after a challenger has led volume for `min_roll_days`
           consecutive days (reduces roll jitter)
Prices are cached to data/ so repeat experiments cost $0.
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


def _resolve_window(client, ts, dataset):
    end = ts.get("end") or (pd.Timestamp.utcnow() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    start = ts["start"]
    try:
        rng = client.metadata.get_dataset_range(dataset=dataset)
        avail = str(rng.get("start", rng) if isinstance(rng, dict) else rng)[:10]
        if avail and avail > start:
            print(f"[futures_daily] clamping start {start} -> {avail}", flush=True)
            start = avail
    except Exception as e:
        print(f"[futures_daily] dataset-range check skipped ({e})", flush=True)
    return start, end


def fetch_raw(universe, cfg):
    """{mkt: DataFrame[date, close, instrument_id, volume]} - every contract, per market."""
    ts = cfg["tsmom"]; dbt = ts["databento"]
    dataset = dbt.get("dataset", "GLBX.MDP3")
    client = _client()
    start, end = _resolve_window(client, ts, dataset)
    parents = [f"{m}.FUT" for m in universe]
    if not ts.get("skip_cost_check", False):
        cost = float(_with_retry(lambda: client.metadata.get_cost(
            dataset=dataset, symbols=parents, stype_in="parent", schema="ohlcv-1d",
            start=start, end=end)))
        cap = float(ts.get("max_cost_usd", 32.0))
        print(f"[futures_daily] Databento estimated cost: ${cost:.4f} (cap ${cap}, credit $125)", flush=True)
        if cost > cap:
            raise RuntimeError(f"cost ${cost:.2f} exceeds cap ${cap} - aborting")
    raw = {}
    for mkt in universe:
        try:
            df = _with_retry(lambda p=f"{mkt}.FUT": client.timeseries.get_range(
                dataset=dataset, symbols=[p], stype_in="parent", schema="ohlcv-1d",
                start=start, end=end).to_df())
        except Exception as e:
            print(f"[futures_daily] {mkt}: giving up ({e}) - skipping", flush=True); continue
        if df is None or len(df) == 0:
            print(f"[futures_daily] {mkt}: 0 rows - skipping", flush=True); continue
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["ts_event"]).dt.date
        raw[mkt] = df[["date", "close", "instrument_id", "volume"]].copy()
        print(f"[futures_daily] {mkt}: {len(df):,} raw rows", flush=True)
    if not raw:
        raise RuntimeError("no markets loaded")
    return raw


def active_series(dfm, roll="naive", min_roll_days=3):
    """Reduce all-contracts rows to ONE active (date, close, instrument_id) per day."""
    daily_max = dfm.loc[dfm.groupby("date")["volume"].idxmax()].sort_values("date")
    if roll == "naive":
        return daily_max[["date", "close", "instrument_id"]].reset_index(drop=True)
    close_by = dfm.set_index(["date", "instrument_id"])["close"]
    cur = None; streak_id = None; streak = 0; rows = []
    for _, r in daily_max.iterrows():
        d, top = r["date"], r["instrument_id"]
        if cur is None:
            cur = top
        if top == cur:
            streak_id, streak = None, 0
        else:
            streak = streak + 1 if top == streak_id else 1
            streak_id = top
            if streak >= min_roll_days:
                cur, streak_id, streak = top, None, 0
        try:
            c = float(close_by.loc[(d, cur)])
        except Exception:
            c, cur = float(r["close"]), top          # cur delisted -> follow the leader
        rows.append((d, c, cur))
    return pd.DataFrame(rows, columns=["date", "close", "instrument_id"])


def _roll_adjusted_prices(active):
    d = active.sort_values("date").reset_index(drop=True)
    ret = d["close"] / d["close"].shift(1) - 1.0
    ret = ret.where(d["instrument_id"] == d["instrument_id"].shift(1), 0.0)
    ret.iloc[0] = 0.0
    return pd.Series((100.0 * (1.0 + ret).cumprod()).values, index=pd.to_datetime(d["date"]))


def build_panel(raw, roll="naive", min_roll_days=3):
    cols = {m: _roll_adjusted_prices(active_series(dfm, roll, min_roll_days))
            for m, dfm in raw.items()}
    return pd.DataFrame(cols).sort_index().ffill().dropna(how="all")


def load(universe, cfg):
    ts = cfg["tsmom"]
    roll = ts.get("roll", "naive")
    cache = ts.get("cache_path")
    if cache:
        from pathlib import Path
        p = Path(cache)
        if p.exists() and not ts.get("force_refetch", False):
            print(f"[futures_daily] loading cached panel {cache} ($0)", flush=True)
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            return df
    raw = fetch_raw(universe, cfg)
    panel = build_panel(raw, roll, int(ts.get("min_roll_days", 3)))
    print(f"[futures_daily] price panel: {panel.shape[0]} days x {panel.shape[1]} markets", flush=True)
    return panel
