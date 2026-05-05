"""CAM ↔ LLM chat interface — a tiny Flask web app.

Sits on the QUJATA orchestrator VM (.247) on port 8082 and exposes:

  /                    — single-page UI with three buttons
  POST /api/recommend  — wraps chat_advisor.recommend() for one use case
  POST /api/rank       — wraps chat_advisor.rank() for a metric
  POST /api/measure    — fires a real `--use-analyze` sweep on demand
  GET  /api/cam-rows   — list current CAM-tagged rows in MCP MariaDB

The page is intentionally tiny — it's a CAM-flavored launcher rather than
a full chat. For free-form chat the user goes to the main UI on .159:8081.
This UI is for the standard CAM workflows: pick context → get a
recommendation grounded in CAM measurements → optionally re-run the
chosen algorithm.

Run:
    set -a; . ./.env; set +a
    .venv/bin/python cam_chat_ui.py     # listens on 0.0.0.0:8082
Then browse to http://10.160.101.247:8082/
"""
from __future__ import annotations

import json
import os
import sys

# Reuse the existing hooks
import chat_advisor
import mcp_hook

try:
    from flask import Flask, jsonify, request
except ImportError:
    sys.exit("missing dependency: pip install flask")

app = Flask(__name__)


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/>
<title>CAM — Context Agility Manager</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif;
         background: #0d1018; color: #c9d1d9; margin: 0; padding: 24px;
         max-width: 920px; margin-left: auto; margin-right: auto; }
  h1 { color: #c4b5e3; margin: 0 0 4px; font-size: 1.6rem; }
  h2 { color: #968db2; margin: 22px 0 8px; font-size: 1rem;
       text-transform: uppercase; letter-spacing: 0.5px; }
  .lead { color: #64748b; font-size: 0.9rem; margin: 0 0 24px;
          line-height: 1.5; }
  .panel { background: #161924; border: 1px solid #2d3148;
           border-radius: 8px; padding: 16px; margin: 12px 0; }
  label { display: inline-block; min-width: 130px; color: #968db2;
          font-size: 0.85rem; }
  select, input[type=text], input[type=number] {
    background: #1e2233; border: 1px solid #2d3148; color: #c9d1d9;
    padding: 6px 9px; border-radius: 5px; font-size: 0.85rem;
    font-family: inherit; min-width: 180px; }
  button { background: #2b4976; border: 1px solid #3a5a8a;
           color: #fff; padding: 8px 16px; border-radius: 6px;
           cursor: pointer; font-size: 0.85rem; font-weight: 600;
           font-family: inherit; margin-top: 10px; }
  button:hover { background: #355c91; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  .row { margin: 6px 0; }
  pre.out { background: #0f1218; border: 1px solid #2d3148;
            border-radius: 6px; padding: 12px; font-size: 0.78rem;
            line-height: 1.45; overflow-x: auto; min-height: 60px;
            white-space: pre-wrap; word-break: break-word; }
  .badge { display: inline-block; background: #1a1d27;
           border: 1px solid #2d3148; padding: 2px 7px; border-radius: 4px;
           font-size: 0.72rem; color: #968db2; margin-right: 6px; }
  a { color: #c4b5e3; }
  .note { font-size: 0.78rem; color: #64748b; margin-top: 6px; }
</style>
</head><body>
  <h1>CAM — Context Agility Manager</h1>
  <p class="lead">
    Crypto-agility decisions grounded in real PQ-REACT testbed measurements.
    Picks one of <span class="badge">classical</span>
    <span class="badge">mlkem512/768/1024</span>
    <span class="badge">p256_mlkem512</span>
    <span class="badge">p384_mlkem768</span>
    <span class="badge">X25519MLKEM768</span>
    given your context. Backed by the LLM chat at
    <a href="http://10.160.101.159:8081/" target="_blank">:8081</a>
    over the MCP server's <code>cam-context-agility</code> rows.
  </p>

  <div class="panel">
    <h2>Recommend an algorithm</h2>
    <div class="row"><label>Use case</label>
      <select id="use_case">
        <option>banking</option><option>iot-sensor</option>
        <option>medical</option><option>military</option>
        <option>chat</option><option>video-conf</option>
        <option>general</option>
      </select></div>
    <div class="row"><label>Security floor</label>
      <select id="security_floor">
        <option value="1">NIST L1</option>
        <option value="3" selected>NIST L3</option>
        <option value="5">NIST L5</option>
      </select></div>
    <div class="row"><label>Energy budget</label>
      <select id="energy_budget">
        <option>min</option><option selected>balanced</option><option>max</option>
      </select></div>
    <div class="row"><label>Payload (bytes)</label>
      <input type="number" id="payload_size" value="1200" min="64" max="65000"/></div>
    <button onclick="recommend()">Get recommendation</button>
    <pre class="out" id="rec_out">(idle)</pre>
  </div>

  <div class="panel">
    <h2>Rank CAM measurements</h2>
    <div class="row"><label>Metric</label>
      <select id="metric">
        <option value="duration">duration (lower=better)</option>
        <option value="energy_joules">energy_joules (lower=better)</option>
        <option value="power_watts">power_watts (lower=better)</option>
        <option value="cpu_util_pct">cpu_util_pct (lower=better)</option>
      </select></div>
    <button onclick="rank()">Rank</button>
    <pre class="out" id="rank_out">(idle)</pre>
  </div>

  <div class="panel">
    <h2>Trigger a real measurement</h2>
    <div class="row"><label>Algorithm</label>
      <select id="m_alg">
        <option>classical</option><option>mlkem512</option>
        <option selected>mlkem768</option><option>mlkem1024</option>
        <option>p256_mlkem512</option><option>p384_mlkem768</option>
        <option>X25519MLKEM768</option>
      </select></div>
    <div class="row"><label>Duration (s)</label>
      <input type="number" id="m_duration" value="10" min="3" max="60"/></div>
    <div class="row"><label>Bandwidth (kbps)</label>
      <input type="number" id="m_bandwidth" value="50000" min="1000" max="200000"/></div>
    <button onclick="measure()">Measure</button>
    <pre class="out" id="m_out">(idle)</pre>
    <div class="note">Hits <code>/qujata-api/analyze</code>, polls
      <code>qujata-mysql</code>, UPSERTs into <code>PQREACT.performance_test</code>.
      Takes ~15–25 s per run.</div>
  </div>

  <div class="panel">
    <h2>Current CAM rows in MCP MariaDB</h2>
    <button onclick="refreshRows()">Refresh</button>
    <pre class="out" id="rows_out">(click Refresh)</pre>
  </div>

<script>
async function postJSON(url, body) {
  const r = await fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  return r.json();
}
function setOut(id, txt) { document.getElementById(id).textContent = txt; }
function setBusy(id) { setOut(id, 'working…'); }

async function recommend() {
  setBusy('rec_out');
  const data = await postJSON('/api/recommend', {
    use_case:       document.getElementById('use_case').value,
    security_floor: parseInt(document.getElementById('security_floor').value),
    payload_size:   parseInt(document.getElementById('payload_size').value),
    energy_budget:  document.getElementById('energy_budget').value,
  });
  setOut('rec_out',
    'ALG = ' + (data.algorithm || '(no parse)') + '\\n\\n' +
    'WHY: ' + (data.rationale || '(no rationale)'));
}
async function rank() {
  setBusy('rank_out');
  const data = await postJSON('/api/rank', {
    metric: document.getElementById('metric').value,
  });
  setOut('rank_out', data.response || JSON.stringify(data, null, 2));
}
async function measure() {
  setBusy('m_out');
  const data = await postJSON('/api/measure', {
    algorithm:   document.getElementById('m_alg').value,
    duration_s:  parseInt(document.getElementById('m_duration').value),
    bandwidth_kbps: parseInt(document.getElementById('m_bandwidth').value),
  });
  setOut('m_out', JSON.stringify(data, null, 2));
}
async function refreshRows() {
  setBusy('rows_out');
  const r = await fetch('/api/cam-rows');
  const data = await r.json();
  let txt = data.summary + '\\n\\n';
  txt += data.rows.map(r =>
    [r.algorithm_name.padEnd(16),
     ('msg=' + r.message_size).padEnd(10),
     ('L' + (r.security_level === null ? '?' : r.security_level)).padEnd(4),
     'dur=' + (r.duration === null ? '-' : r.duration.toFixed(4) + 's')
    ].join('  ')).join('\\n');
  setOut('rows_out', txt);
}
</script>
</body></html>
"""


@app.route("/")
def index():
    return PAGE


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    j = request.get_json(silent=True) or {}
    r = chat_advisor.recommend(
        use_case=j.get("use_case", "general"),
        security_floor=int(j.get("security_floor", 3)),
        payload_size=int(j.get("payload_size", 1200)),
        energy_budget=j.get("energy_budget", "balanced"),
    )
    return jsonify({"algorithm": r.get("algorithm"),
                    "rationale": r.get("rationale")})


@app.route("/api/rank", methods=["POST"])
def api_rank():
    j = request.get_json(silent=True) or {}
    r = chat_advisor.rank(
        metric=j.get("metric", "duration"),
        security_floor=int(j.get("security_floor", 3)),
        payload_size=int(j.get("payload_size", 1200)),
    )
    return jsonify({"response": r.get("response", "")})


@app.route("/api/measure", methods=["POST"])
def api_measure():
    j   = request.get_json(silent=True) or {}
    alg = j.get("algorithm", "mlkem768")
    n   = mcp_hook.run_analyze_sweep(
        [alg],
        slice_id="mgmt",
        duration_s=int(j.get("duration_s", 10)),
        bandwidth_kbps=int(j.get("bandwidth_kbps", 50000)),
        msg_size=int(j.get("msg_size", 1200)),
    )
    return jsonify({"ok": True, "algorithm": alg, "rows_written": n})


@app.route("/api/cam-rows")
def api_cam_rows():
    """Return the current CAM-tagged rows directly from MCP MariaDB."""
    conn = mcp_hook.get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT algorithm_name, message_size, duration, security_level "
            "FROM performance_test WHERE source = %s "
            "ORDER BY algorithm_name, message_size",
            (mcp_hook.env("CAM_SOURCE_TAG"),),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) AS n, COUNT(duration) AS with_dur "
            "FROM performance_test WHERE source = %s",
            (mcp_hook.env("CAM_SOURCE_TAG"),),
        )
        s = cur.fetchone()
    conn.close()
    return jsonify({
        "summary": f"{s['n']} rows total ({s['with_dur']} with real measurements)",
        "rows":    [dict(r) for r in rows],
    })


if __name__ == "__main__":
    if not mcp_hook.env("MCP_DB_PASSWORD"):
        sys.exit("MCP_DB_PASSWORD env var is required (set in .env)")
    port = int(os.environ.get("CAM_UI_PORT", "8082"))
    print(f"CAM UI listening on http://0.0.0.0:{port}/")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
