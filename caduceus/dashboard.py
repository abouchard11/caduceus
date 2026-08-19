"""Static HTML status dashboard - command-center style, zero dependencies.

Reads: ledger.db, runs/, guard.log.jsonl, per-profile gateway_state.json,
kanban.db (best-effort). Writes one self-contained HTML file.
"""
from __future__ import annotations

import html
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .config import SEATS
from .ledger import Ledger

CSS = """
:root{--bg:#0b0e14;--panel:#12161f;--line:#1e2530;--txt:#d7dde8;--dim:#7a8699;
--ok:#3fb68b;--warn:#e0af68;--bad:#f7768e;--acc:#7aa2f7}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:14px/1.5 -apple-system,'SF Mono',Menlo,monospace;padding:28px}
h1{font-size:20px;letter-spacing:.06em} h1 .snake{color:var(--acc)}
.sub{color:var(--dim);margin:4px 0 24px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--dim);margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{padding:5px 8px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)} .dim{color:var(--dim)}
.badge{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;border:1px solid var(--line)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--acc)}
.memo{border-left:2px solid var(--acc);padding:6px 10px;margin:8px 0;font-size:12.5px}
.memo .q{color:var(--txt)} .memo .m{color:var(--dim);font-size:11px}
code{color:var(--acc)}
footer{margin-top:24px;color:var(--dim);font-size:11px}
"""


def _gateway_state(seat_name: str) -> str:
    p = config.hermes_home() / "profiles" / seat_name / "gateway_state.json"
    if not p.exists():
        return "down"
    try:
        data = json.loads(p.read_text())
        return str(data.get("gateway_state") or "unknown")
    except Exception:
        return "unknown"


def _kanban_snapshot() -> Optional[Dict[str, int]]:
    db = config.hermes_home() / "kanban.db"
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()
        conn.close()
        return {status: n for status, n in rows}
    except sqlite3.Error:
        return None


def _guard_tail(n: int = 8) -> List[Dict]:
    p = config.guard_log_path()
    if not p.exists():
        return []
    lines = p.read_text().splitlines()[-n:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _recent_memos(n: int = 6) -> List[Dict]:
    out = []
    for p in sorted(config.runs_dir().glob("*.json"), reverse=True)[:n]:
        try:
            blob = json.loads(p.read_text())
            out.append({
                "run_id": blob.get("run_id", p.stem),
                "question": blob.get("question", "")[:110],
                "mode": blob.get("mode", ""),
                "ranked": blob.get("ranked", []),
                "memo": blob.get("memo", ""),
            })
        except Exception:
            continue
    return out


def build() -> str:
    led = Ledger()
    table = led.table()
    unsettled = led.runs(unsettled_only=True)
    led.close()

    def esc(s) -> str:
        return html.escape(str(s))

    from .models import effective_seat
    seats_rows = []
    for name in SEATS:
        seat = effective_seat(name)
        gw = _gateway_state(name)
        cls = "ok" if gw == "running" else ("dim" if gw == "down" else "warn")
        glb = [r for r in table if r["seat"] == name]
        b = round(sum(r["believability"] for r in glb) / len(glb), 3) if glb else 0.5
        seats_rows.append(
            f"<tr><td><b>{esc(seat.display)}</b></td>"
            f"<td class='dim'>{esc(seat.model)}</td>"
            f"<td><span class='badge {cls}'>{esc(gw)}</span></td>"
            f"<td><div class='bar'><i style='width:{int(b*100)}%'></i></div></td>"
            f"<td>{b:.3f}</td></tr>"
        )

    ledger_rows = "".join(
        f"<tr><td>{esc(r['seat'])}</td><td>{esc(r['domain'])}</td>"
        f"<td>{r['win']}/{r['mixed']}/{r['loss']}</td>"
        f"<td>{r['believability']:.3f} <span class='dim'>({esc(r['basis'])})</span></td></tr>"
        for r in table[:14]
    ) or "<tr><td colspan=4 class='dim'>no settled outcomes yet - councils run, reality settles</td></tr>"

    memo_html = "".join(
        f"<div class='memo'><div class='q'>{esc(m['question'])}</div>"
        f"<div class='m'>{esc(m['run_id'])} - {esc(m['mode'])} - lead: "
        f"{esc(m['ranked'][0][0] if m['ranked'] else '?')}</div></div>"
        for m in _recent_memos()
    ) or "<div class='dim'>no council runs yet - try: <code>cad council ask \"...\"</code></div>"

    unsettled_html = "".join(
        f"<div class='memo'><div class='q'>{esc(u['question'][:90])}</div>"
        f"<div class='m'><code>cad ledger settle {esc(u['run_id'])} --winner &lt;seat&gt;</code></div></div>"
        for u in unsettled[:5]
    ) or "<div class='dim'>nothing awaiting settlement</div>"

    guard_rows = "".join(
        f"<tr><td class='{'bad' if 'block' in g.get('action','') else 'warn'}'>"
        f"{esc(g.get('action'))}</td><td>{esc(g.get('rule'))}</td>"
        f"<td class='dim'>{esc(g.get('cmd',''))[:60]}</td></tr>"
        for g in _guard_tail()
    ) or "<tr><td colspan=3 class='dim'>no guard events</td></tr>"

    kb = _kanban_snapshot()
    if kb:
        kb_html = " ".join(f"<span class='badge'>{esc(k)}: {v}</span>" for k, v in kb.items())
    else:
        kb_html = "<span class='dim'>no kanban.db found (hermes kanban init)</span>"

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>CADUCEUS - engine status</title><style>{CSS}</style></head><body>
<h1><span class="snake">&#9741;</span> CADUCEUS <span class="dim">- multi-seat engine on Hermes</span></h1>
<div class="sub">generated {ts} - refresh with <code>cad dashboard</code></div>
<div class="grid">
<div class="card"><h2>Seats</h2><table>
<tr><th>seat</th><th>model</th><th>gateway</th><th colspan=2>believability</th></tr>
{''.join(seats_rows)}</table></div>
<div class="card"><h2>Believability ledger</h2><table>
<tr><th>seat</th><th>domain</th><th>w/m/l</th><th>score</th></tr>
{ledger_rows}</table></div>
<div class="card"><h2>Recent councils</h2>{memo_html}</div>
<div class="card"><h2>Awaiting settlement</h2>{unsettled_html}</div>
<div class="card"><h2>Guard - last events</h2><table>
<tr><th>action</th><th>rule</th><th>command</th></tr>{guard_rows}</table></div>
<div class="card"><h2>Kanban</h2>{kb_html}</div>
</div>
<footer>caduceus - the operator is the Shaper; the seats are the staff. Unsettled advice never improves the ledger.</footer>
</body></html>"""


def write(out_path: Optional[Path] = None) -> Path:
    p = out_path or (config.repo_root() / "outputs" / "caduceus.html")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build())
    return p
