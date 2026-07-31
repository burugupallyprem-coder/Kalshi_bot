"""Continuous alpha-search engine (minimal, honest). RESEARCH ONLY.

Runs a PRE-DECLARED hypothesis set, corrects for MULTIPLE TESTING with the Deflated
Sharpe Ratio, quarantines any survivor for a fresh out-of-sample forward test, writes a
full audit trail, and Slack-alerts ONLY when a candidate clears the honest bar.

Why it's honest: a raw "pass" among N tries means nothing - the best of many random
strategies always looks good. Only a Deflated-Sharpe survivor (then a fresh forward test)
is a real lead. Between findings it just heartbeats "still searching - no edge yet".

`evaluate_search(trials, ...)` is data-agnostic and unit-tested; run() wires in the data +
existing research harness + Slack.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from src.backtest import multiple_testing as MT
except Exception:
    import multiple_testing as MT

ROOT = Path(__file__).resolve().parent.parent.parent


def evaluate_search(trials, dsr_threshold=0.95, min_trades=30):
    """trials: [{name, r_multiples}]. Returns the deflated-significance verdict."""
    scored = []
    for t in trials:
        sr, n, sk, ku = MT.per_trade_sharpe(t.get("r_multiples", []))
        scored.append({"name": t["name"], "sharpe": round(sr, 4), "trades": n,
                       "skew": round(sk, 3), "kurt": round(ku, 3)})
    if not scored:
        return {"survivor": False, "why": "no hypotheses tested", "n_trials": 0,
                "best": None, "dsr": 0.0, "all": []}
    sharpes = [s["sharpe"] for s in scored]
    best = max(scored, key=lambda s: s["sharpe"])
    dsr, sr0 = MT.deflated_sharpe_ratio(best["sharpe"], best["trades"], sharpes,
                                        best["skew"], best["kurt"])
    survivor = bool(dsr >= dsr_threshold and best["sharpe"] > 0 and best["trades"] >= min_trades)
    why = ("clears the deflated-Sharpe bar" if survivor else
           f"DSR {dsr:.3f} < {dsr_threshold} after correcting for {len(scored)} trials")
    return {"survivor": survivor, "why": why, "dsr": round(dsr, 4),
            "expected_max_null": round(sr0, 4), "n_trials": len(scored),
            "best": best, "all": scored, "threshold": dsr_threshold}


def quarantine_survivor(res, params):
    """Record a survivor for a FRESH forward test before it can ever be trusted/promoted."""
    q = ROOT / "data" / "quarantine.json"
    q.parent.mkdir(exist_ok=True)
    try:
        rec = json.loads(q.read_text())
    except Exception:
        rec = []
    rec.append({"found_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "name": res["best"]["name"], "params": params,
                "dsr": res["dsr"], "sharpe": res["best"]["sharpe"], "trades": res["best"]["trades"],
                "status": "PENDING forward test - not trusted until it survives a fresh OOS window"})
    q.write_text(json.dumps(rec, indent=2))


def run():
    import pandas as pd
    from src import data as data_mod, slackbot
    from src.backtest import research, metrics
    from src.strategies import momentum, orb, vwap_revert
    mods = {"orb": orb, "vwap_revert": vwap_revert, "momentum": momentum}
    cfg = research.load_config()
    a = cfg["alpha_search"]
    rs = cfg["research"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    val_end = rs.get("val_end") or (pd.Timestamp.utcnow() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cfg["universe"] = a["universe"]

    bars = data_mod.fetch_bars(a["universe"], rs["val_start"], val_end,
                               timeframe=cfg["backtest"]["timeframe"], feed=cfg["backtest"]["feed"])
    if bars.empty:
        slackbot.post(f"[ALPHA-SEARCH] {ts} FAILED: no bars from Alpaca."); return
    bars = data_mod.rth_only(bars)
    groups = research.day_groups(bars)
    ctx = research.build_context(groups, cfg)

    trials = []
    for h in a["hypotheses"]:
        strat = mods[h["strategy"]]
        params = {**dict(cfg["strategies"].get(h["strategy"], {})), **h.get("params", {})}
        m = metrics.summarize(research.run_config(groups, strat, params, cfg, h["strategy"], ctx))
        rms = m["df"]["r_multiple"].tolist() if m.get("trades", 0) else []
        trials.append({"name": h["name"], "r_multiples": rms})

    res = evaluate_search(trials, float(a.get("dsr_threshold", 0.95)),
                          int(a.get("min_trades", 30)))

    # full audit trail (every hypothesis, its Sharpe, and the deflated verdict)
    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    lines = [f"# Alpha-search cycle - {ts}", "", "RESEARCH ONLY. Multiple-testing controlled.",
             f"hypotheses tested: {res['n_trials']} | DSR threshold: {res['threshold']}",
             f"best: {res['best']['name'] if res['best'] else '-'} | per-trade Sharpe "
             f"{res['best']['sharpe'] if res['best'] else 0} over {res['best']['trades'] if res['best'] else 0} trades",
             f"expected max Sharpe under null (luck bar): {res['expected_max_null']}",
             f"**Deflated Sharpe: {res['dsr']}** -> {'SURVIVOR' if res['survivor'] else 'no edge'} ({res['why']})",
             "", "## All hypotheses (per-trade Sharpe)"]
    for s in sorted(res["all"], key=lambda x: x["sharpe"], reverse=True):
        lines.append(f"- {s['name']}: Sharpe {s['sharpe']} ({s['trades']} trades)")
    (out / f"alpha_search_{stamp}.md").write_text("\n".join(lines), encoding="utf-8")

    if res["survivor"]:
        params = next((h.get("params", {}) for h in a["hypotheses"] if h["name"] == res["best"]["name"]), {})
        quarantine_survivor(res, params)
        slackbot.post(
            f"*[ALPHA-SEARCH] CANDIDATE FOUND* {ts}\n"
            f"'{res['best']['name']}' cleared the deflated-Sharpe bar: DSR {res['dsr']} "
            f"(Sharpe {res['best']['sharpe']}, {res['best']['trades']} trades, {res['n_trials']} tested)\n"
            f"QUARANTINED for a fresh forward test - NOT trusted yet. Your call on next steps.\n"
            f"Detail: reports/alpha_search_{stamp}.md")
    else:
        slackbot.post(
            f"[ALPHA-SEARCH] {ts} - still searching, no edge. {res['n_trials']} hypotheses, "
            f"best DSR {res['dsr']} (< {res['threshold']}). Detail: reports/alpha_search_{stamp}.md")


if __name__ == "__main__":
    run()
