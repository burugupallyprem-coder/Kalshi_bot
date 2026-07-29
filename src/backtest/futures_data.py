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


def preflight_cost(client, symbols, cfg):
    """Ask Databento the EXACT $ cost of this query BEFORE downloading. Returns the
    cost in USD. Never surprises you with a bill."""
    fs = cfg["futures_stage2"]
    dbt = fs["databento"]
    conts = [f"{s}{dbt.get('continuous_suffix', '.c.0')}" for s in symbols]
    return float(client.metadata.get_cost(
        dataset=dbt.get("dataset", "GLBX.MDP3"), symbols=conts, stype_in="continuous",
        schema=dbt.get("schema", "ohlcv-1m"), start=fs["start"], end=fs.get("end")))


def load(symbols, cfg):
    """Returns {symbol: RTH DataFrame} ready for the engine (symbol/o/h/l/c/v/et/date)."""
    fs = cfg["futures_stage2"]
    tf = fs.get("timeframe", "5Min")
    client = _client()
    cap = float(fs.get("max_cost_usd", 20.0))
    if not fs.get("skip_cost_check", False):
        try:
            cost = preflight_cost(client, symbols, cfg)
        except Exception as e:
            raise RuntimeError(f"Databento cost preview failed ({e}); "
                               f"set futures_stage2.skip_cost_check: true to override.")
        print(f"[futures_data] Databento estimated cost for this pull: ${cost:.2f} "
              f"(cap ${cap:.2f}, free credit $125)", flush=True)
        if cost > cap:
            raise RuntimeError(f"Databento cost ${cost:.2f} exceeds cap ${cap:.2f} - "
                               f"aborting before spending. Raise futures_stage2.max_cost_usd to proceed.")
    df1 = _fetch_1m(client, symbols, cfg)
    print(f"[futures_data] fetched {len(df1):,} raw 1-min records for {symbols}", flush=True)
    if df1.empty:
        raise RuntimeError(
            "Databento returned 0 records. Most likely the CME/GLBX.MDP3 dataset is not "
            "enabled on your account - open the Databento portal -> Datasets -> "
            "CME Globex MDP 3.0 and ACCEPT THE CME LICENSE, then re-run. "
            "(Other possibilities: continuous symbol format, or start date before data coverage.)")
    dfN = resample(df1, tf)
    print(f"[futures_data] {len(dfN):,} bars after resample to {tf}; "
          f"symbols seen: {sorted(dfN['symbol'].unique())}", flush=True)
    rth = data_mod.rth_only(dfN)   # adds 'et' + 'date', keeps 09:30-16:00 ET
    print(f"[futures_data] {len(rth):,} bars after RTH filter", flush=True)
    if rth.empty:
        raise RuntimeError(
            f"fetched {len(df1):,} 1-min records but 0 survived the RTH filter - a timezone or "
            "price-scale issue in _fetch_1m; verify the ts conversion against a known bar.")
    out = {sym: g.reset_index(drop=True) for sym, g in rth.groupby("symbol")}
    print(f"[futures_data] loaded symbols: {sorted(out)}", flush=True)
    return out
