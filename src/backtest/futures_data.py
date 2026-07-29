"""Databento loader for Stage 2 - continuous front-month futures, resampled to the
strategy timeframe, RTH only. RESEARCH ONLY.

FIRST-RUN VERIFICATION (I could not test the live API here): on the first real run,
eyeball one MES bar against a known chart to confirm (a) prices are in index POINTS
(databento to_df default pretty_px=True), and (b) timestamps land in the RTH window
after the UTC->ET conversion. If a bar looks off by 1e9 or by hours, fix the scale/tz
here before trusting any result.

Needs the DATABENTO_API_KEY secret. Fetches ohlcv-1m and resamples to 5-min so the
LOCKED momentum config (confirm_bar=12 == ~10:30 ET on 5-min bars) stays faithful.
"""

import os

import pandas as pd

from src import data as data_mod


def _client(key=None):
    import databento as db
    return db.Historical(key or os.environ["DATABENTO_API_KEY"])


def _fetch_1m(client, symbols, cfg):
    fs = cfg["futures_stage2"]
    dbt = fs["databento"]
    conts = [f"{s}{dbt.get('continuous_suffix', '.c.0')}" for s in symbols]
    data = client.timeseries.get_range(
        dataset=dbt.get("dataset", "GLBX.MDP3"),
        symbols=conts, stype_in="continuous",
        schema=dbt.get("schema", "ohlcv-1m"),
        start=fs["start"], end=fs.get("end"))
    df = data.to_df().reset_index()
    # map continuous symbol (e.g. 'MES.c.0') back to root ('MES')
    root = {f"{s}{dbt.get('continuous_suffix', '.c.0')}": s for s in symbols}
    df["symbol"] = df["symbol"].map(lambda x: root.get(x, str(x).split(".")[0]))
    ts_col = "ts_event" if "ts_event" in df.columns else df.columns[0]
    out = pd.DataFrame({
        "symbol": df["symbol"],
        "ts": pd.to_datetime(df[ts_col], utc=True),
        "open": df["open"].astype(float), "high": df["high"].astype(float),
        "low": df["low"].astype(float), "close": df["close"].astype(float),
        "volume": df["volume"].astype(float)})
    return out


def resample(df_1m, timeframe="5Min"):
    """1-min -> timeframe OHLCV per symbol (UTC bins), keep 'ts' UTC for rth_only."""
    frames = []
    for sym, g in df_1m.groupby("symbol"):
        g = g.set_index("ts").sort_index()
        r = g.resample(timeframe, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        r = r.dropna(subset=["open"])
        r["symbol"] = sym
        r["ts"] = r.index
        frames.append(r.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True) if frames else df_1m


def load(symbols, cfg):
    """Returns {symbol: RTH DataFrame} ready for the engine (symbol/o/h/l/c/v/et/date)."""
    tf = cfg["futures_stage2"].get("timeframe", "5Min")
    client = _client()
    df1 = _fetch_1m(client, symbols, cfg)
    dfN = resample(df1, tf)
    rth = data_mod.rth_only(dfN)   # adds 'et' + 'date', keeps 09:30-16:00 ET
    return {sym: g.reset_index(drop=True) for sym, g in rth.groupby("symbol")}
