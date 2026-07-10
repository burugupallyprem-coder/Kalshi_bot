"""Mission-control dashboard: renders dashboard.html with ALL data inlined
(no fetch calls, so it opens as a local file). Regenerated + committed by the
premarket / trade / research workflows on every run.

Also appends this run's outcome to data/status.json when WORKFLOW_NAME is set
(env: WORKFLOW_NAME, RUN_OUTCOME=success|failure|cancelled).

Run manually: python -m src.live.dashboard
"""

import csv
import glob
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
STATUS_PATH = ROOT / "data" / "status.json"


def append_status():
    wf = os.environ.get("WORKFLOW_NAME")
    if not wf:
        return
    outcome = os.environ.get("RUN_OUTCOME", "unknown")
    try:
        data = json.loads(STATUS_PATH.read_text()) if STATUS_PATH.exists() else {"runs": []}
    except Exception:
        data = {"runs": []}
    data["runs"].append({"wf": wf, "utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                         "ok": outcome == "success", "outcome": outcome})
    data["runs"] = data["runs"][-100:]
    STATUS_PATH.parent.mkdir(exist_ok=True)
    STATUS_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _load_status():
    try:
        runs = json.loads(STATUS_PATH.read_text()).get("runs", [])
    except Exception:
        runs = []
    latest = {}
    for r in runs:
        latest[r["wf"]] = r
    return latest, runs[-12:][::-1]


def _load_equity():
    path = ROOT / "data" / "paper_days.csv"
    rows = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    rows.append({"date": row["date"], "equity": float(row["equity"]),
                                 "pnl": float(row["day_pnl"])})
                except (KeyError, ValueError):
                    continue
    return rows


def _load_flags():
    try:
        return json.loads((ROOT / "data" / "premarket_flags.json").read_text())
    except Exception:
        return {}


def _load_research():
    files = sorted(glob.glob(str(ROOT / "reports" / "research_*.md")))
    if not files:
        return []
    out = []
    current = None
    for line in open(files[-1], encoding="utf-8"):
        line = line.strip()
        if line.startswith("## "):
            current = line[3:].split(":")[0].strip()
        elif line.startswith("**Winner on validation:") and current:
            verdict = line.replace("**Winner on validation:", "").replace("**", "").strip()
            out.append({"strategy": current, "verdict": verdict})
    return out


def render():
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    latest, recent = _load_status()
    equity = _load_equity()
    flags = _load_flags()
    research = _load_research()
    live = cfg.get("live", {})
    params = live.get("params", {})
    guard = (live.get("premarket") or {}).get("guard_mode", "log_only")

    def light(wf):
        r = latest.get(wf)
        if not r:
            return '<span class="dot gray"></span><span class="mut">no runs yet</span>'
        cls = "green" if r["ok"] else "red"
        return f'<span class="dot {cls}"></span><span class="mut">{r["utc"]}Z</span>'

    movers = sorted((flags.get("gaps") or {}).items(), key=lambda kv: -abs(kv[1]))[:6]
    eq_labels = json.dumps([r["date"] for r in equity])
    eq_values = json.dumps([r["equity"] for r in equity])
    last_eq = f"${equity[-1]['equity']:,.0f}" if equity else "$100,000"
    last_pnl = f"{equity[-1]['pnl']:+,.0f}" if equity else "--"
    total_pnl = f"{(equity[-1]['equity'] - 100000):+,.0f}" if equity else "--"

    research_rows = "".join(
        f'<tr><td>{html.escape(r["strategy"])}</td>'
        f'<td class="{ "ok" if "PASS" in r["verdict"] else "bad"}">{html.escape(r["verdict"])}</td></tr>'
        for r in research) or '<tr><td colspan="2" class="mut">no research reports parsed yet</td></tr>'

    recent_rows = "".join(
        f'<tr><td>{html.escape(r["wf"])}</td><td>{r["utc"]}Z</td>'
        f'<td class="{ "ok" if r["ok"] else "bad"}">{html.escape(r["outcome"])}</td></tr>'
        for r in recent) or '<tr><td colspan="3" class="mut">awaiting first tracked run</td></tr>'

    mover_html = " ".join(
        f'<span class="chip {"bad" if abs(g) >= 4 else ""}">{html.escape(s)} {g:+.1f}%</span>'
        for s, g in movers) or '<span class="mut">no pre-market data yet today</span>'

    flag_line = "NONE - normal session"
    if flags.get("halt_today"):
        flag_line = "WOULD HALT (SPY gap)" if guard == "log_only" else "SESSION HALTED"
    elif flags.get("skip_symbols"):
        verb = "would skip" if guard == "log_only" else "skipping"
        flag_line = f"{verb}: {', '.join(flags['skip_symbols'])}"

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>STOCK-TRADER-BOT // MISSION CONTROL</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  :root {{ --bg:#070b12; --panel:#0d1420; --line:#1c2a3f; --cyan:#28e0ff; --green:#2bff88; --red:#ff3b5b; --amber:#ffb347; --txt:#c9d7e8; --mut:#5b7186; }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ background:var(--bg); color:var(--txt); font:14px/1.5 'Cascadia Code','Consolas',monospace; padding:24px; }}
  body::after {{ content:""; position:fixed; inset:0; pointer-events:none; background:repeating-linear-gradient(0deg,transparent 0 2px,rgba(0,0,0,.12) 2px 4px); }}
  h1 {{ font-size:20px; letter-spacing:3px; color:var(--cyan); text-shadow:0 0 12px rgba(40,224,255,.5); }}
  .sub {{ color:var(--mut); margin:4px 0 20px; font-size:12px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px 18px; box-shadow:0 0 18px rgba(40,224,255,.05); }}
  .card h2 {{ font-size:12px; letter-spacing:2px; color:var(--cyan); margin-bottom:12px; }}
  .row {{ display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px dashed var(--line); }}
  .row:last-child {{ border-bottom:none; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; animation:pulse 2s infinite; }}
  .dot.green {{ background:var(--green); box-shadow:0 0 8px var(--green); }}
  .dot.red {{ background:var(--red); box-shadow:0 0 8px var(--red); }}
  .dot.gray {{ background:#444; animation:none; }}
  @keyframes pulse {{ 50% {{ opacity:.45; }} }}
  .big {{ font-size:26px; color:#fff; text-shadow:0 0 10px rgba(43,255,136,.35); }}
  .mut {{ color:var(--mut); font-size:12px; }}
  .ok {{ color:var(--green); }} .bad {{ color:var(--red); }} .warn {{ color:var(--amber); }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  td {{ padding:4px 6px; border-bottom:1px solid var(--line); }}
  .chip {{ display:inline-block; border:1px solid var(--line); border-radius:12px; padding:2px 9px; margin:2px; font-size:12px; }}
  .chip.bad {{ border-color:var(--red); color:var(--red); }}
  .banner {{ border:1px solid var(--amber); color:var(--amber); border-radius:8px; padding:8px 12px; margin-bottom:18px; font-size:12px; letter-spacing:1px; }}
</style></head><body>
<h1>STOCK-TRADER-BOT <span style="color:var(--mut)">//</span> MISSION CONTROL</h1>
<div class="sub">generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}Z · refresh: run dashboard.ps1 (git pull + reopen)</div>
<div class="banner">PAPER ACCOUNT ONLY · LIVE ENDPOINT CODE-LOCKED · champion: ORB (WEAK PASS - on trial) · premarket guard: {guard}</div>
<div class="grid">
  <div class="card"><h2>PIPELINE STATUS</h2>
    <div class="row"><span>premarket briefing</span><span>{light("premarket")}</span></div>
    <div class="row"><span>entry session</span><span>{light("trade-entry")}</span></div>
    <div class="row"><span>eod flatten</span><span>{light("trade-eod")}</span></div>
    <div class="row"><span>research sweep</span><span>{light("research")}</span></div>
  </div>
  <div class="card"><h2>ACCOUNT (PAPER)</h2>
    <div class="big">{last_eq}</div>
    <div class="row"><span>last day P&amp;L</span><span>{last_pnl}</span></div>
    <div class="row"><span>total since start</span><span>{total_pnl}</span></div>
    <canvas id="eq" height="110"></canvas>
  </div>
  <div class="card"><h2>TODAY // PRE-MARKET</h2>
    <div class="row"><span>risk flags</span><span class="warn">{html.escape(flag_line)}</span></div>
    <div style="margin-top:8px">{mover_html}</div>
  </div>
  <div class="card"><h2>CHAMPION CONFIG</h2>
    <div class="row"><span>strategy</span><span>ORB long-only</span></div>
    <div class="row"><span>opening range</span><span>{params.get("open_bars", 3)} x 5min</span></div>
    <div class="row"><span>reward:risk</span><span>{params.get("rr", 1.5)}</span></div>
    <div class="row"><span>entry cutoff</span><span>{params.get("cutoff_et", "10:30")} ET</span></div>
    <div class="row"><span>risk / trade</span><span>0.5% · max 3 positions</span></div>
  </div>
  <div class="card"><h2>LATEST RESEARCH VERDICTS</h2><table>{research_rows}</table></div>
  <div class="card"><h2>RECENT RUNS</h2><table>{recent_rows}</table></div>
</div>
<script>
try {{
  const ctx = document.getElementById("eq");
  new Chart(ctx, {{ type:"line",
    data: {{ labels: {eq_labels}, datasets: [{{ data: {eq_values}, borderColor:"#28e0ff",
      backgroundColor:"rgba(40,224,255,.08)", fill:true, tension:.3, pointRadius:2 }}] }},
    options: {{ plugins: {{ legend: {{ display:false }} }},
      scales: {{ x: {{ ticks: {{ color:"#5b7186" }}, grid: {{ color:"#1c2a3f" }} }},
                y: {{ ticks: {{ color:"#5b7186" }}, grid: {{ color:"#1c2a3f" }} }} }} }} }});
}} catch (e) {{ /* offline: chart lib unavailable, numbers above still valid */ }}
</script>
</body></html>"""
    (ROOT / "dashboard.html").write_text(page, encoding="utf-8")
    print(f"dashboard rendered: {len(page):,} bytes, {len(equity)} equity points")


def main():
    append_status()
    render()


if __name__ == "__main__":
    main()
