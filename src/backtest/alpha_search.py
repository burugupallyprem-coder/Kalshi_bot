"""Continuous alpha-search engine (Stage A+B+C). RESEARCH ONLY.

Each on-demand or weekly run:
  B) EXPANDS a pre-declared search space into a whole BATCH of hypotheses (dozens) and
     tests them all at once through the no-lookahead engine on a SEARCH window;
  A) applies MULTIPLE-TESTING correction (Deflated Sharpe) to pick a survivor - a raw
     "pass" among N tries is meaningless; only a deflated-Sharpe survivor qualifies;
  C) FORWARD-TESTS that survivor on a fresh, held-out window it never saw during the
     search. Only a candidate that clears BOTH gates is a real lead and pings Slack.

Everything is logged (full audit trail). Nothing deploys. `expand_hypotheses`,
`evaluate_search`, and `forward_verdict` are data-agnostic and unit-tested.
"""

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from src.backtest import multiple_testing as MT
except Exception:
    import multiple_testing as MT

ROOT = Path(__file__).resolve().parent.parent.parent


def expand_hypotheses(cfg):
    """Pre-declared search-space grids -> a flat batch of concrete hypotheses."""
    hyps = []
    for strat, grid in cfg["alpha_search"]["search_space"].items():
        keys = sorted(grid)
        for combo in itertools.product(*(grid[k] for k in keys)):
            params = dict(zip(keys, combo))
            name = f"{strat}[" + ", ".join(f"{k}={v}" for k, v in params.items()) + "]"
            hyps.append({"name": name, "strategy": strat, "params": params})
    return hyps


def evaluate_search(trials, dsr_threshold=0.95, min_trades=30):
    """Search-window verdict with multiple-testing (deflated-Sharpe) correction."""
    scored = []
    for t in trials:
        sr, n, sk, ku = MT.per_trade_sharpe(t.get("r_multiples", []))
        scored.append({"name": t["name"], "sharpe": round(sr, 4), "trades": n,
                       "skew": round(sk, 3), "kurt": round(ku, 3)})
    if not scored:
        return {"survivor": False, "why": "no hypotheses", "n_trials": 0, "best": None,
                "dsr": 0.0, "expected_max_null": 0.0, "all": [], "threshold": dsr_threshold}
    sharpes = [s["sharpe"] for s in scored]
    best = max(scored, key=lambda s: s["sharpe"])
    dsr, sr0 = MT.deflated_sharpe_ratio(best["sharpe"], best["trades"], sharpes,
                                        best["skew"], best["kurt"])
    survivor = bool(dsr >= dsr_threshold and best["sharpe"] > 0 and best["trades"] >= min_trades)
    why = ("clears deflated-Sharpe bar" if survivor else
           f"DSR {dsr:.3f} < {dsr_threshold} after correcting for {len(scored)} trials")
    return {"survivor": survivor, "why": why, "dsr": round(dsr, 4),
            "expected_max_null": round(sr0, 4), "n_trials": len(scored), "best": best,
            "all": scored, "threshold": dsr_threshold}


def forward_verdict(r_multiples, min_trades=20):
    """Confirm gate: a survivor must be positive on FRESH held-out data it never saw."""
    sr, n, _, _ = MT.per_trade_sharpe(r_multiples)
    mean = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0
    confirmed = bool(n >= min_trades and sr > 0 and mean > 0)
    return {"confirmed": confirmed, "trades": n, "sharpe": round(sr, 4),
            "expectancy_r": round(mean, 4)}


def _quarantine(name, params, search, forward):
    q = ROOT / "data" / "quarantine.json"
    q.parent.mkdir(exist_ok=True)
    try:
        rec = json.loads(q.read_text())
    except Exception:
        rec = []
    rec.append({"found_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "name": name, "params": params,
                "search_dsr": search["dsr"], "search_sharpe": search["best"]["sharpe"],
                "forward": forward,
                "status": ("CONFIRMED on fresh data - awaiting your review"
                           if forward["confirmed"] else
                           "DSR survivor but FAILED forward test - discarded")})
    q.write_text(json.dumps(rec, indent=2))


def run():
    import pandas as pd
    from src import data as data_mod, slackbot
    from src.backtest import research, metrics
    from src.strategies import momentum, orb, vwap_revert
    mods = {"orb": orb, "vwap_revert": vwap_revert, "momentum": momentum}
    cfg = research.load_config()
    a = cfg["alpha_search"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cfg["universe"] = a["universe"]
    fwd_end = a.get("forward_end") or (pd.Timestamp.now("UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    bars = data_mod.fetch_bars(a["universe"], a["search_start"], fwd_end,
                               timeframe=cfg["backtest"]["timeframe"], feed=cfg["backtest"]["feed"])
    if bars.empty:
        slackbot.post(f"[ALPHA-SEARCH] {ts} FAILED: no bars from Alpaca."); return
    bars = data_mod.rth_only(bars)
    s_end = pd.to_datetime(a["search_end"]).date()
    f_start = pd.to_datetime(a["forward_start"]).date()
    search_groups = research.day_groups(bars[bars["date"] <= s_end])
    fwd_groups = research.day_groups(bars[bars["date"] >= f_start])
    search_ctx = research.build_context(search_groups, cfg)
    fwd_ctx = research.build_context(fwd_groups, cfg)

    hyps = expand_hypotheses(cfg)
    trials = []
    for h in hyps:
        strat = mods[h["strategy"]]
        params = {**dict(cfg["strategies"].get(h["strategy"], {})), **h["params"]}
        m = metrics.summarize(research.run_config(search_groups, strat, params, cfg, h["strategy"], search_ctx))
        trials.append({"name": h["name"], "r_multiples": m["df"]["r_multiple"].tolist() if m.get("trades", 0) else []})

    res = evaluate_search(trials, float(a.get("dsr_threshold", 0.95)), int(a.get("min_trades", 30)))

    fwd = None
    if res["survivor"]:
        h = next(x for x in hyps if x["name"] == res["best"]["name"])
        strat = mods[h["strategy"]]
        params = {**dict(cfg["strategies"].get(h["strategy"], {})), **h["params"]}
        fm = metrics.summarize(research.run_config(fwd_groups, strat, params, cfg, h["strategy"], fwd_ctx))
        fwd = forward_verdict(fm["df"]["r_multiple"].tolist() if fm.get("trades", 0) else [],
                              int(a.get("forward_min_trades", 20)))
        _quarantine(h["name"], h["params"], res, fwd)

    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    L = [f"# Alpha-search cycle - {ts}", "", "RESEARCH ONLY. Multiple-testing controlled + forward-tested.",
         f"search {a['search_start']}->{a['search_end']} | forward {a['forward_start']}->{fwd_end}",
         f"hypotheses tested this batch: **{res['n_trials']}** | DSR threshold {res['threshold']}",
         f"best: {res['best']['name'] if res['best'] else '-'} | search Sharpe "
         f"{res['best']['sharpe'] if res['best'] else 0} ({res['best']['trades'] if res['best'] else 0} trades)",
         f"luck bar (expected max Sharpe under null): {res['expected_max_null']}",
         f"**Deflated Sharpe: {res['dsr']}**"]
    if res["survivor"] and fwd:
        L.append(f"forward test: {'CONFIRMED' if fwd['confirmed'] else 'FAILED'} "
                 f"(Sharpe {fwd['sharpe']}, expectancy {fwd['expectancy_r']}R, {fwd['trades']} trades)")
    L += ["", "## All hypotheses by search Sharpe"]
    for s in sorted(res["all"], key=lambda x: x["sharpe"], reverse=True)[:40]:
        L.append(f"- {s['name']}: {s['sharpe']} ({s['trades']} trades)")
    (out / f"alpha_search_{stamp}.md").write_text("\n".join(L), encoding="utf-8")

    if res["survivor"] and fwd and fwd["confirmed"]:
        slackbot.post(
            f"*[ALPHA-SEARCH] CONFIRMED CANDIDATE* {ts}\n"
            f"'{res['best']['name']}' cleared BOTH gates: deflated Sharpe {res['dsr']} across "
            f"{res['n_trials']} tested, AND positive on fresh forward data "
            f"(Sharpe {fwd['sharpe']}, {fwd['expectancy_r']}R, {fwd['trades']} trades).\n"
            f"Quarantined for your review - NOT deployed. This one is worth a look.\n"
            f"Detail: reports/alpha_search_{stamp}.md")
    elif res["survivor"]:
        slackbot.post(
            f"[ALPHA-SEARCH] {ts} - a hypothesis passed the deflated-Sharpe bar but FAILED the "
            f"forward test (fresh data). Correctly discarded. {res['n_trials']} tested.\n"
            f"Detail: reports/alpha_search_{stamp}.md")
    else:
        slackbot.post(
            f"[ALPHA-SEARCH] {ts} - {res['n_trials']} hypotheses tested, no edge "
            f"(best DSR {res['dsr']} < {res['threshold']}). Still searching.\n"
            f"Detail: reports/alpha_search_{stamp}.md")


if __name__ == "__main__":
    run()
