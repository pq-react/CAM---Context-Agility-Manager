// CAM PQC demo panel — UI logic.
//
// Responsibilities:
//   1. Populate the algorithm dropdown from /api/algorithms
//   2. POST /api/runs on Run; track the run id
//   3. Open an EventSource for /api/runs/{id}/stream and append lines
//   4. Stop button → POST /api/runs/{id}/stop
//   5. Quick sweep button → run defaults_quick algorithms back-to-back
//   6. iframe refresh buttons re-set src= with a cache-buster

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const elAlgo     = $("#algo");
const elIter     = $("#iterations");
const elPay      = $("#payload");
const elForm     = $("#run-form");
const elStart    = $("#start-btn");
const elStop     = $("#stop-btn");
const elQuick    = $("#quick-btn");
const elStatus   = $("#status-line");
const elSummary  = $("#summary");
const elLog      = $("#log");
const elClear    = $("#clear-log");
const elIfSrv    = $("#iframe-server");
const elIfCli    = $("#iframe-client");

let currentRunId = null;
let currentSse   = null;
let quickQueue   = [];          // remaining algos in a quick sweep
let quickInProg  = false;

// ── 1. populate dropdown ─────────────────────────────────────────────────

async function loadAlgorithms() {
  const r = await fetch("/api/algorithms");
  const d = await r.json();
  elAlgo.innerHTML = "";
  // Group by family for visual clarity.
  const groups = new Map();
  for (const a of d.algorithms) {
    if (!groups.has(a.family)) groups.set(a.family, []);
    groups.get(a.family).push(a);
  }
  for (const [fam, list] of groups) {
    const og = document.createElement("optgroup");
    og.label = fam.toUpperCase();
    for (const a of list) {
      const o = document.createElement("option");
      o.value = a.id;
      o.textContent = `${a.display}${a.nist_l ? ` · L${a.nist_l}` : ""}`;
      og.appendChild(o);
    }
    elAlgo.appendChild(og);
  }
  // Default selection: ML-KEM-768 if present (matches the QA-battery 1200B baseline).
  const def = "mlkem768";
  if (d.algorithms.find(a => a.id === def)) elAlgo.value = def;
  elIter.value = d.default_iterations;
  elPay.value  = d.default_payload_bytes;
  // Stash the quick-sweep list for the button.
  elQuick.dataset.algos = JSON.stringify(d.defaults_quick);
}

// ── 2. start a run ───────────────────────────────────────────────────────

async function startRun(spec) {
  resetForNewRun();
  elStart.disabled = true; elStop.disabled = false; elQuick.disabled = quickInProg;
  setStatus("starting…", "running");

  const r = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  if (!r.ok) {
    const t = await r.text();
    setStatus(`start failed: ${t}`, "failed");
    elStart.disabled = false; elStop.disabled = true; elQuick.disabled = false;
    quickQueue = []; quickInProg = false;
    return;
  }
  const j = await r.json();
  currentRunId = j.run_id;
  setStatus(`run ${currentRunId} · ${spec.algorithm} · iter=${spec.iterations}`, "running");
  attachSse(currentRunId);
}

elForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const spec = {
    algorithm:     elAlgo.value,
    iterations:    parseInt(elIter.value, 10),
    payload_bytes: parseInt(elPay.value, 10),
  };
  startRun(spec);
});

// ── 3. SSE log stream ────────────────────────────────────────────────────

function attachSse(runId) {
  if (currentSse) { currentSse.close(); currentSse = null; }
  const es = new EventSource(`/api/runs/${runId}/stream`);
  currentSse = es;

  es.addEventListener("log", (ev) => appendLog(ev.data));
  es.addEventListener("end", () => {
    es.close(); currentSse = null;
    fetchSummary(runId);
    onRunFinished();
  });
  es.addEventListener("ping", () => {});  // heartbeat — ignore
  es.onerror = () => {
    // EventSource auto-retries on transient errors. Only treat as terminal
    // if the connection is permanently closed.
    if (es.readyState === EventSource.CLOSED) {
      currentSse = null;
      onRunFinished();
    }
  };
}

function appendLog(line) {
  let cls = "";
  if (line.startsWith("===")) cls = "l-meta";
  else if (line.includes(" http=2") || line.includes(" http=20")) cls = "l-ok";
  else if (line.includes("FAILED") || line.includes("ERROR")) cls = "l-err";

  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = line + "\n";
  elLog.appendChild(span);

  // Auto-scroll to bottom unless user has scrolled up.
  const nearBottom = (elLog.scrollHeight - elLog.scrollTop - elLog.clientHeight) < 80;
  if (nearBottom) elLog.scrollTop = elLog.scrollHeight;
}

async function fetchSummary(runId) {
  const r = await fetch(`/api/runs/${runId}`);
  if (!r.ok) return;
  const d = await r.json();
  setStatus(
    `${d.status} · ${d.spec.algorithm} · ${d.summary.n || 0} handshakes`,
    d.status,
  );
  renderSummary(d.summary);
}

function renderSummary(s) {
  if (!s || !s.n) { elSummary.innerHTML = ""; return; }
  elSummary.innerHTML = `
    <div class="stat"><span class="k">handshakes</span><span class="v">${s.n} (${s.ok} ok)</span></div>
    <div class="stat"><span class="k">appconnect p50/p95</span><span class="v">${s.appconnect_ms_p50} / ${s.appconnect_ms_p95} ms</span></div>
    <div class="stat"><span class="k">total p50/p95</span><span class="v">${s.total_ms_p50} / ${s.total_ms_p95} ms</span></div>
    <div class="stat"><span class="k">bytes in</span><span class="v">${s.bytes_in_total.toLocaleString()}</span></div>`;
}

// ── 4. stop ──────────────────────────────────────────────────────────────

elStop.addEventListener("click", async () => {
  if (!currentRunId) return;
  elStop.disabled = true;
  await fetch(`/api/runs/${currentRunId}/stop`, { method: "POST" });
  setStatus(`stopping ${currentRunId}…`, "cancelled");
  quickQueue = []; quickInProg = false;
});

// ── 5. quick sweep (run defaults_quick back-to-back) ─────────────────────

elQuick.addEventListener("click", () => {
  if (quickInProg) return;
  const algos = JSON.parse(elQuick.dataset.algos || "[]");
  if (!algos.length) return;
  quickQueue = [...algos]; quickInProg = true;
  elQuick.disabled = true;
  // Reduce iter count for a quick demo; user can override afterwards.
  elIter.value = Math.min(parseInt(elIter.value, 10), 50);
  appendLog(`### quick sweep: ${algos.join(", ")}\n`);
  runNextInQueue();
});

function runNextInQueue() {
  if (!quickQueue.length) {
    quickInProg = false;
    elQuick.disabled = false;
    appendLog("### quick sweep complete\n");
    return;
  }
  const next = quickQueue.shift();
  elAlgo.value = next;
  startRun({
    algorithm:     next,
    iterations:    parseInt(elIter.value, 10),
    payload_bytes: parseInt(elPay.value, 10),
  });
}

function onRunFinished() {
  elStart.disabled = false;
  elStop.disabled  = true;
  if (quickInProg) {
    setTimeout(runNextInQueue, 600);
  } else {
    elQuick.disabled = false;
  }
}

// ── 6. iframe refresh + log clear ────────────────────────────────────────

$$('button[data-refresh]').forEach((btn) => {
  btn.addEventListener("click", () => {
    const which = btn.dataset.refresh;
    const f = which === "server" ? elIfSrv : elIfCli;
    const sep = f.src.includes("?") ? "&" : "?";
    f.src = f.src.split("&_t=")[0] + sep + "_t=" + Date.now();
  });
});
elClear.addEventListener("click", () => { elLog.textContent = ""; });

// ── helpers ──────────────────────────────────────────────────────────────

function resetForNewRun() {
  elLog.textContent = "";
  elSummary.innerHTML = "";
}
function setStatus(text, klass) {
  elStatus.textContent = text;
  elStatus.className = "status-line " + (klass || "");
}

// Boot.
loadAlgorithms().catch((e) => setStatus("failed to load algorithms: " + e, "failed"));
