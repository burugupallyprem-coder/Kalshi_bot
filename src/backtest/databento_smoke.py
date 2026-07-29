"""Minimal Databento probe - prints EXACTLY what the API returns for MES so we can
fix the Stage 2 loader without guessing. RESEARCH ONLY. Tiny ~2-day pull (near $0).

Tries several symbology styles side by side. Whichever returns rows is the one the
loader should use, and its columns/price tell us the exact shape + scale.

Run: python -m src.backtest.databento_smoke
"""

import os
import traceback


def _probe(client, label, kw, start, end, schema):
    import databento as db  # noqa
    try:
        cost = client.metadata.get_cost(dataset="GLBX.MDP3", schema=schema,
                                        start=start, end=end, **kw)
    except Exception as e:
        return f"{label}: get_cost ERROR {type(e).__name__}: {e}"
    try:
        data = client.timeseries.get_range(dataset="GLBX.MDP3", schema=schema,
                                           start=start, end=end, **kw)
        df = data.to_df()
    except Exception as e:
        traceback.print_exc()
        return f"{label}: get_range ERROR {type(e).__name__}: {e} (cost was ${float(cost):.4f})"
    msg = f"{label}: cost=${float(cost):.4f} rows={len(df)} cols={list(df.columns)[:9]}"
    if len(df):
        r = df.reset_index().iloc[0]
        msg += (f" | first: ts_event={r.get('ts_event')} symbol={r.get('symbol')} "
                f"open={r.get('open')} close={r.get('close')} volume={r.get('volume')}")
    return msg


def run():
    import databento as db
    print("databento version:", getattr(db, "__version__", "?"), flush=True)
    client = db.Historical(os.environ["DATABENTO_API_KEY"])
    start, end = "2025-06-02T00:00", "2025-06-04T00:00"   # a couple of weekdays with data
    trials = [
        ("A continuous MES.c.0 1m", dict(symbols=["MES.c.0"], stype_in="continuous"), "ohlcv-1m"),
        ("B parent MES.FUT 1m",     dict(symbols=["MES.FUT"], stype_in="parent"),     "ohlcv-1m"),
        ("C continuous MES.c.0 1d", dict(symbols=["MES.c.0"], stype_in="continuous"), "ohlcv-1d"),
        ("D continuous MES.v.0 1m", dict(symbols=["MES.v.0"], stype_in="continuous"), "ohlcv-1m"),
    ]
    lines = []
    for label, kw, schema in trials:
        m = _probe(client, label, kw, start, end, schema)
        print(m, flush=True)
        lines.append(m)
    try:
        from src import slackbot
        slackbot.post("*[DATABENTO-SMOKE]* which symbology returns rows?\n" + "\n".join(lines))
    except Exception as e:
        print("slack post failed:", e, flush=True)


if __name__ == "__main__":
    run()
