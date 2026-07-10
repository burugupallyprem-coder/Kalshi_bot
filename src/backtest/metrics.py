"""Honest performance metrics over a list of Trades."""

import pandas as pd


def summarize(trades):
    if not trades:
        return {"trades": 0}
    df = pd.DataFrame([t.__dict__ for t in trades])
    wins = df[df["pnl"] > 0]
    losses = df[df["pnl"] <= 0]
    gross_win = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    equity = df["pnl"].cumsum()
    max_dd = float((equity.cummax() - equity).max())
    q = pd.PeriodIndex(pd.to_datetime(df["date"]), freq="Q")
    quarterly = df.groupby(q)["pnl"].agg(["sum", "count"])
    return {
        "trades": len(df),
        "win_rate": round(len(wins) / len(df) * 100, 1),
        "avg_win": round(wins["pnl"].mean(), 2) if len(wins) else 0.0,
        "avg_loss": round(losses["pnl"].mean(), 2) if len(losses) else 0.0,
        "expectancy_usd": round(df["pnl"].mean(), 2),
        "expectancy_r": round(df["r_multiple"].mean(), 3),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else float("inf"),
        "net_pnl": round(df["pnl"].sum(), 2),
        "max_drawdown": round(max_dd, 2),
        "quarters_positive": int((quarterly["sum"] > 0).sum()),
        "quarters_total": int(len(quarterly)),
        "quarterly_table": quarterly,
        "df": df,
    }


def gate_verdict(m, gate):
    if m["trades"] < gate["min_trades"]:
        return "FAIL", f"only {m['trades']} trades (<{gate['min_trades']})"
    checks = []
    if m["expectancy_r"] < gate["min_expectancy_r"]:
        checks.append(f"expectancy {m['expectancy_r']}R < {gate['min_expectancy_r']}R")
    if m["profit_factor"] < gate["min_profit_factor"]:
        checks.append(f"PF {m['profit_factor']} < {gate['min_profit_factor']}")
    frac = m["quarters_positive"] / max(m["quarters_total"], 1)
    if frac < gate["min_quarters_positive_frac"]:
        checks.append(f"only {m['quarters_positive']}/{m['quarters_total']} quarters positive")
    return ("PASS", "all gate checks met") if not checks else ("FAIL", "; ".join(checks))
