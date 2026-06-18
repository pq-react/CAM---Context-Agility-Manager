# CAM (Context Agility Manager) — Briefing for LLM-driven Documentation

> Source-of-truth briefing intended to be fed verbatim into an LLM so it can produce a deliverable-grade description and architecture document for the CAM repository. All facts in this file are extracted from the repository's own READMEs and source files; nothing is inferred or speculated. Where the README is ambiguous it is flagged explicitly.

Repository: `CAM---Context-Agility-Manager`  (PQ-REACT framework, Horizon Europe project)
GitHub origin: scrubbed in docs as `<github>/CAM---Context-Agility-Manager`

---

## 1. What CAM is

**CAM (Context Agility Manager)** is the PQ-REACT framework's component for **cryptographic agility** — selecting and configuring post-quantum and hybrid cryptographic algorithms based on operational context. The repository's stated objectives:

- Automatically reason about which cryptographic configuration suits a given operational context (regulation, security level, available algorithms, resource constraints).
- Mitigate common cryptographic misconfigurations by automating choices of algorithm types, key sizes, and security levels.
- Provide measurement, visualisation and (eventually) closed-loop adaptation of cryptographic algorithms used between server and client machines on the testbed.

**Current implementation status (as stated in the root `README.md`)**: CAM does not yet *dynamically* select the most suitable cryptographic configurations. It can loop through the available post-quantum, classical and hybrid encryption algorithms exposed by the QUJATA framework and visualise the performance and security impact in real time through Grafana dashboards. The pieces required to close the loop (recommendation, application, verification) exist as optional add-ons in `pqreact_hooks/` (Phases 1, 2, 5).

**Demonstrator scope**: CAM has been used in the QUJATA testbed (PQ-REACT framework) to measure handshake performance across PQC, classical and hybrid algorithms and to feed those measurements into the PQ-REACT MCP server's MariaDB so the project's chat agent can compare CAM data against other measurement sources.

---

## 2. Repository layout

```
CAM---Context-Agility-Manager/
├── README.md                          ← top-level setup guide (InfluxDB+Telegraf+Grafana+Qujata)
├── performance_test.py                ← original CAM loop: walk algorithms, POST /curl
├── W_T_retrieval.py                   ← Telegraf-side script: read temps/power, push to InfluxDB
├── metrics_dashboard-1728313377372.json ← Grafana dashboard JSON for NUC metrics
├── requirements.txt                   ← runtime deps for the root scripts
├── images/                            ← README screenshots
├── CAM_details_screeshots.pdf         ← project-level screenshot collection
├── PQREACT_CAM_Handshake_Evaluation.docx ← evaluation deliverable (added in 2026-05)
├── Portal Testing/                    ← portal-level integration tests
│   ├── Portaltesting.md
│   └── portal_testing.py
├── Unit Testing/                      ← unit tests for the root scripts
│   ├── Performance_unit_testing.md
│   ├── W_T_retrieval Unit_Testing.md
│   ├── unittesting.py
│   ├── test_performance_test.py
│   ├── test_performance_edge_cases.py
│   ├── test_get_temperatures.py
│   ├── test_get_power_consumption.py
│   ├── test_send_to_influxdb.py
│   └── test_main_loop_integration.py
└── pqreact_hooks/                     ← OPTIONAL bridge to the wider PQ-REACT testbed
    ├── README.md
    ├── .env.example
    ├── requirements.txt               ← pymysql
    ├── mcp_hook.py                    ← Phase 1 — write CAM measurements to PQ-REACT MariaDB
    ├── chat_advisor.py                ← Phase 2 — ask the chat to recommend / rank
    ├── cam_runner.py                  ← orchestrator — sweep → recommend → re-sweep
    ├── closed_loop.py                 ← Phase 5 — sweep → recommend → apply → verify → verdict
    ├── deploy-to-qujata-vm.sh         ← deployment helper
    └── cam_demo_panel/                ← single-VM PQC handshake demo (FastAPI + nginx + curl + Grafana)
        ├── README.md
        ├── docker-compose.yml         ← 4 containers: panel + nginx + curl + Grafana
        ├── .env.example
        ├── panel/                     ← FastAPI panel image
        │   ├── Dockerfile
        │   ├── requirements.txt
        │   ├── api.py                 ← routes (/api/runs etc.)
        │   ├── runner.py              ← driver: docker exec curl, SSE fan-out, optional InfluxDB+MariaDB writes
        │   ├── algorithms.py          ← PQC + classical algorithm registry
        │   └── web/                   ← single-page UI (index.html + panel.css + panel.js + pq-console.css)
        ├── nginx/                     ← OQS-OpenSSL nginx image + TLS-1.3 config exposing every OQS group
        ├── curl/                      ← OQS-OpenSSL curl image (long-lived, docker-exec'd per run)
        └── grafana/                   ← provisioning + dashboards (cam-demo-server.json, cam-demo-client.json)
```

The repository is **upstream-pristine** with respect to the core CAM scripts: the PQ-REACT bridge lives entirely in `pqreact_hooks/` and never modifies any of the original CAM files.

---

## 3. Core CAM (standalone)

The root README documents an end-to-end setup that runs CAM stand-alone — i.e. without the PQ-REACT MCP server — using only InfluxDB, Grafana, Telegraf and a Qujata testbed.

### 3.1 `performance_test.py` — the algorithm-sweep loop

What it does (as documented at the top of the file and in `README.md` Step 6):
- Iterates over a list of cryptographic algorithm names (PQC, classical, hybrid).
- For each algorithm, POSTs a request to a Qujata endpoint that wraps the OQS-OpenSSL stack and times handshakes.
- Captures the per-algorithm response, used downstream for dashboards and (optionally) the PQ-REACT bridge.

Canonical algorithm list (as of 2026-05 update, post-FIPS-203 / ML-KEM rename — the file's own comment block explains the rename and the dropped names):

| Family | Algorithms |
|---|---|
| Classical | `prime256v1`, `secp384r1` |
| ML-KEM (FIPS 203) | `mlkem512`, `mlkem768`, `mlkem1024` |
| ML-KEM hybrids | `p256_mlkem512`, `p384_mlkem768`, `X25519MLKEM768` |
| FrodoKEM | `frodo640aes`, `frodo640shake`, `frodo976aes`, `frodo976shake`, `frodo1344aes`, `frodo1344shake` |
| BIKE | `bikel1`, `bikel3`, `bikel5` |

Notes recorded in the file:
- The original list used pre-FIPS-203 names (`kyber*`, `hqc*`, `x25519_kyber768`, …); the current `openquantumsafe/openssl-3` + `oqs-provider` build dropped those, causing curl exit 59 ("failed setting curves list: '<name>'") or TLS handshake_failure (exit 35).
- HQC is intentionally absent because the current `oqs-provider` does not ship it.
- The list of supported names is authoritative against `openssl list -kem-algorithms` on the demo host.

### 3.2 `W_T_retrieval.py` — Telegraf-side environment metrics

Reads system temperatures (`sensors` command output) and power consumption (Telegraf `[[inputs.execd]]` powerstat reader), parses them, and pushes the values to InfluxDB. Required env vars (set at runtime, not at import — so unit tests can import the module without raising):

| Env var | Purpose |
|---|---|
| `CAM_INFLUXDB_URL` | InfluxDB v2 write API URL |
| `CAM_INFLUXDB_TOKEN` | InfluxDB v2 token |
| `CAM_INFLUXDB_ORG` | Org (default `pqreact`) |
| `CAM_INFLUXDB_BUCKET` | Bucket (default `metrics`) |

This script's role is to provide CPU thermal + power-consumption data alongside the handshake measurements, so the Grafana dashboards can correlate cryptographic load with energy/thermal behaviour.

### 3.3 InfluxDB schema

The dashboards expect data in the `NUC_metrics` bucket (or whatever bucket is configured) using Telegraf's standard measurements plus a few custom ones:

| Measurement | Source | Fields used |
|---|---|---|
| `cpu` | Telegraf `[[inputs.cpu]]` | `usage_user`, tag `cpu="cpu-total"` |
| `mem` | Telegraf `[[inputs.mem]]` | `used` |
| `net` | Telegraf `[[inputs.net]]` | `bytes_recv`, `bytes_sent` |
| `temp` | Telegraf `[[inputs.temp]]` | `temp` |
| `cpufreq` | Telegraf `[[inputs.cpufreq]]` | `current` |
| `powerstat` | custom — Telegraf `[[inputs.execd]]` powerstat reader (see CAM's `telegraf.conf`) | `system_w`, `cores_w`, `package_w` |
| `cam_demo_handshake` | The demo panel's `runner.py` writes this directly via the InfluxDB v2 write API | `appconnect_ms`, `total_ms`, `bytes_in`, `http_code`; tags: `algorithm`, `run_id` |

### 3.4 Grafana dashboards

- `metrics_dashboard-1728313377372.json` — the original NUC-metrics dashboard (CPU, memory, network, temperature, power).
- `pqreact_hooks/cam_demo_panel/grafana/dashboards/cam-demo-server.json` — nginx-side panel for the bundled demo.
- `pqreact_hooks/cam_demo_panel/grafana/dashboards/cam-demo-client.json` — curl-client-side panel for the bundled demo.

The README explicitly notes the `metrics_dashboard.json` assumes username `node-1`, network interface `enp86s0`, bucket `NUC_metrics` — change those values to match your setup.

### 3.5 Standalone setup steps (from `README.md`)

1. **Install / configure InfluxDB 2.7.6** on a server VM; create the `NUC_metrics` bucket; record the access token.
2. **Install / configure Telegraf** on both server and client machines; configure the InfluxDB output plugin; add the standard CPU/mem/net/temp/cpufreq inputs and the custom powerstat `execd` input.
3. **Configure a Python script for CPU metrics recovery** — this is `W_T_retrieval.py` running on the Telegraf hosts.
4. **Verify Telegraf** is writing to InfluxDB (browser-side check on `:8086`).
5. **Install Grafana via Docker**.
6. **Configure Grafana data source** to point at InfluxDB.
7. **Import the dashboards** (`metrics_dashboard.json`).
8. **Install and configure the QUJATA testbed** (separate stack — provides the OQS-OpenSSL nginx + curl that `performance_test.py` exercises).
9. **Run `performance_test.py`** with `CAM_QUJATA_URL=http://<host>:3010/curl` set to the QUJATA legacy curl endpoint.

The setup is deliberately bare-metal-friendly: InfluxDB + Grafana on separate VMs, Telegraf + QUJATA on physical NUCs.

---

## 4. The PQ-REACT MCP bridge — `pqreact_hooks/`

This subdirectory is **optional** — CAM is standalone-by-default. The bridge connects CAM to:
- The PQ-REACT MCP server's MariaDB (`PQREACT.performance_test` table, with a `source` column to tag the origin).
- The PQ-REACT chat UI (FastAPI + Ollama, llama3.1:8b on NVIDIA L4), so LLM queries can see CAM measurements alongside other PQ-REACT sources.

### 4.1 `mcp_hook.py` — MariaDB writer (Phase 1)

What it does:
- Loops the same algorithm list `performance_test.py` uses.
- POSTs each algorithm to the QUJATA legacy `/curl` endpoint.
- UPSERTs one row per algorithm into `PQREACT.performance_test`, tagged `source='cam-context-agility'` (override via `CAM_SOURCE_TAG`).

CLI:
```
python3 mcp_hook.py                              # full sweep, ~5 min
python3 mcp_hook.py --algos kyber768 mlkem768    # specific algorithms
python3 mcp_hook.py --dry-run                    # hit QUJATA but don't write
```

### 4.2 `chat_advisor.py` — LLM advisor (Phase 2)

Two interaction shapes:

- `recommend` — "Given my use case, security floor, payload size, and energy budget, pick ONE algorithm." The chat agent runs SQL against `performance_test WHERE source='cam-context-agility'` and replies with `ALG=<name>` plus one-sentence rationale.
- `rank` — "Rank CAM-tagged algorithms by `<metric>` at security level ≥ N." Returns a Markdown table.

CLI:
```
python3 chat_advisor.py recommend --use-case banking --security-floor 5
python3 chat_advisor.py recommend --use-case iot-sensor --security-floor 1 --energy-budget min
python3 chat_advisor.py rank --metric energy_joules --security-floor 3
```

### 4.3 `cam_runner.py` — agility loop orchestrator

Closes the original CAM design loop in 4 phases:
```
[1/4] wide sweep  — every algorithm, 50 iterations each → MCP DB
[2/4] recommend   — chat picks ONE algorithm given context
[3/4] re-measure  — narrow sweep on just the chosen algorithm at 200 iters
[4/4] verdict     — JSON line with chosen, rationale, deltas
```

CLI:
```
python3 cam_runner.py --use-case "banking"    --security-floor 5
python3 cam_runner.py --use-case "iot-sensor" --security-floor 1 --energy-budget min
python3 cam_runner.py --skip-wide --use-case "general"
```

### 4.4 `closed_loop.py` — CAM Phase 5 self-configuring orchestrator

Adds two phases beyond `cam_runner.py` (apply + verify) so the loop hits the PQ-REACT MCP `apply_pqc_configuration` tool and (optionally) drives a real QUJATA experiment:

```
[1/5] CAM sweep      — refresh source='cam-context-agility' rows
[2/5] Recommend      — chat picks an algorithm (recommend_migration_priority or query_by_security_level when CAM_TARGET=db)
[3/5] Apply          — call apply_pqc_configuration via the chat; records the decision in pqc_configurations; with target_type='qujata-experiment', kicks a real iperf run
[4/5] Verify         — poll the latest QUJATA test_suite for the suite_id from step 3
[5/5] Verdict        — emit a single JSON line for downstream tooling (cron / CI / dashboards)
```

Required environment:
- `CHAT_URL=http://<chat-host>:8081`
- `MCP_DB_*` — only used to read the latest CAM-tagged algorithm name as a fallback when the chat doesn't return `ALG=<name>`.

CLI examples:
```
python3 closed_loop.py --sector telco                                    # dry-run
python3 closed_loop.py --sector telco --apply qujata-experiment          # real iperf run; needs KATANA_ALLOW_CONFIGURE=true on MCP
python3 closed_loop.py --sector energy --skip-sweep --apply audit
```

### 4.5 Configuration env vars (bridge)

| Var | Default | Used by | Purpose |
|---|---|---|---|
| `MCP_DB_HOST` | required | `mcp_hook` | MCP MariaDB host |
| `MCP_DB_PORT` | `3307` | `mcp_hook` | MCP MariaDB port |
| `MCP_DB_USER` | `root` | `mcp_hook` | MCP MariaDB user |
| `MCP_DB_PASSWORD` | required | `mcp_hook` | random root password from `pqreact-mcp-mariadb` env |
| `MCP_DB_NAME` | `PQREACT` | `mcp_hook` | database name |
| `QUJATA_BASE` | required (if used) | reserved | newer iperf-shape API base URL |
| `QUJATA_LEGACY` | optional | `mcp_hook` | older curl-shape endpoint URL |
| `CHAT_URL` | required | `chat_advisor`, `cam_runner`, `closed_loop` | chat UI base URL |
| `CAM_SOURCE_TAG` | `cam-context-agility` | all three | `source` column tag |

### 4.6 Integration diagram (from `pqreact_hooks/README.md`)

```
┌─────────────────────────────────────────────────────────────┐
│  CAM (this repo)                                            │
│    performance_test.py   W_T_retrieval.py                   │
│         ↓                    ↓                              │
│       /curl              InfluxDB                           │
└───────────┬─────────────────────────────────────────────────┘
            │
            │  pqreact_hooks/mcp_hook.py  ─── push CAM rows ──┐
            │                                                 ↓
┌─────────────────────────────────────────────────────────────┐
│  PQ-REACT MCP server  (host: $MCP_DB_HOST)                  │
│   pqreact-mcp-mariadb (PQREACT.performance_test, 255+ rows) │
│   pqreact-mcp-server  (FastMCP SSE :5040, 19+ tools)        │
└────────────────────────────────────────┬────────────────────┘
                                         │ SSE
┌────────────────────────────────────────┴────────────────────┐
│  Chat UI  (host: $CHAT_URL)                                 │
│   FastAPI + Ollama (llama3.1:8b on NVIDIA L4)               │
│   chat_advisor.py ──► /chat ◄── any browser tab             │
└─────────────────────────────────────────────────────────────┘
```

Once `mcp_hook.py` has run, the chat UI's broad questions ("Show me the 5 fastest algorithms across all message sizes") return answers that **mix `upstream`, `campaign-b-qujata-live` and `cam-context-agility` rows** — CAM measurements participate in cross-source comparisons.

---

## 5. CAM PQC handshake demo — `pqreact_hooks/cam_demo_panel/`

A **self-contained backup of the original two-VM QUJATA demo**, bundled as four Docker containers on a single VM (the CAM host).

### 5.1 Architecture

```
                 ┌────────────────────────────────────────┐
                 │  http://<cam-host>:8083/  (panel)      │
                 │ ┌─ form ─┐ ┌─ log ─────────┐           │
                 │ │ algo   │ │ [n] alg http= │           │
                 │ │ iter   │ │     appconn=  │           │
                 │ │ payload│ │     total=    │           │
                 │ └────────┘ └───────────────┘           │
                 │ ┌─ iframe nginx Server ───────────────┐│
                 │ │ Bandwidth · Power · CPU · Temp ...  ││
                 │ └─────────────────────────────────────┘│
                 │ ┌─ iframe Curl Client ────────────────┐│
                 │ │ p50/p95 · throughput · histogram    ││
                 │ └─────────────────────────────────────┘│
                 └────────────────────────────────────────┘
                                │
                ┌───────────────┼─────────────────┐
                ▼               ▼                 ▼
        pqreact-cam-      pqreact-cam-     pqreact-cam-
        pqc-nginx :4433   pqc-curl         grafana :3001
                          (sleep ∞,         (provisioned
                          docker-exec'd     dashboards)
                          for each run)
                                            │
                                            ▼
                              CAM InfluxDB :8086
                              (bucket=NUC_metrics)
                              ← Telegraf (host metrics)
                              ← panel runner (per-handshake samples)
```

### 5.2 Container roles

| Container | Image | Role |
|---|---|---|
| `pqreact-cam-demo-panel` | `pqreact/cam-demo-panel:1.0.0` (FastAPI on `:8083`) | Single-page UI, `/api/runs/*` endpoints, SSE log stream, optional InfluxDB+MariaDB writers |
| `pqreact-cam-pqc-nginx` | `pqreact/cam-pqc-nginx:1.0.0` (`openquantumsafe/nginx` base) on `:4433` | PQC TLS server, accepts every OQS group QUJATA exposes |
| `pqreact-cam-pqc-curl` | `pqreact/cam-pqc-curl:1.0.0` (`openquantumsafe/curl` base) | Long-lived (`sleep infinity`); panel `docker exec`s curl into it for each handshake |
| `pqreact-cam-grafana` | `grafana/grafana-oss:11.2.0` on `:3001` | Pre-provisioned with the two demo dashboards; anonymous Viewer enabled; iframe embedding allowed |

All four containers share an internal Docker bridge network `cam-demo-net` on subnet `172.30.0.0/24`. nginx is reachable at `172.30.0.10:4433` from inside the network; curl is at `172.30.0.20`.

### 5.3 Panel REST API

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Single-page UI (HTML). |
| GET | `/api/health` | Liveness probe (used by docker healthcheck). |
| GET | `/api/algorithms` | List of supported PQC + classical algorithms with NIST level (read from `algorithms.py`). |
| GET | `/api/iframe-urls` | Resolved Grafana iframe URLs (so callers can re-embed). |
| GET | `/api/runs` | Recent runs, newest first. |
| POST | `/api/runs` | Start a run. Body: `{algorithm, iterations, payload_bytes}`. Returns `{run_id, status, stream}`. |
| GET | `/api/runs/{id}` | Status + summary for one run. |
| POST | `/api/runs/{id}/stop` | Request cancel. |
| GET | `/api/runs/{id}/stream` | SSE log stream — `event: log` for content, `event: ping` heartbeat, `event: end` on completion. |

Example:
```bash
curl -sS -X POST http://<cam-host>:8083/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"mlkem768","iterations":100,"payload_bytes":1200}'
# {"run_id":"a1b2c3d4e5f6","status":"running","stream":"/api/runs/a1b2c3d4e5f6/stream", ... }
```

### 5.4 Panel algorithm registry (`panel/algorithms.py`)

Declares the algorithms the panel offers, each tagged with id (= curl `--curves` value), family, display label, NIST PQC level (1 / 3 / 5; `null` for classical). Currently exposes 17 algorithms: classical(2) + ML-KEM(3) + hybrid(3) + Frodo(6) + BIKE(3). The previous `kyber512`/`768`/`1024` entries were removed in May 2026 because the current OQS-OpenSSL build no longer exposes those TLS group names (see also §6 of the panel README).

A "Quick sweep" preset runs four algorithms back-to-back. The default preset is `["mlkem768", "p256_mlkem512", "X25519MLKEM768", "prime256v1"]` (the previous `kyber768` member was replaced by `X25519MLKEM768` in the same May 2026 update).

### 5.5 Panel configuration env vars

| Var | Default | Purpose |
|---|---|---|
| `CAM_PUBLIC_HOST` | `localhost` | Hostname/IP used in iframe `src=` URLs the browser fetches. Must be reachable from the operator's machine. |
| `INFLUX_URL` | `http://host.docker.internal:8086` | CAM's existing InfluxDB. The panel writes per-handshake samples there; Grafana reads from it. |
| `INFLUX_ORG` | `pqreact` | InfluxDB org. |
| `INFLUX_BUCKET` | `NUC_metrics` | Bucket Telegraf is already writing into. |
| `INFLUX_TOKEN` | empty | Required if you want per-handshake samples to land in InfluxDB. Empty disables; host metrics still flow via Telegraf. |
| `GRAFANA_ADMIN_PASSWORD` | `pqreact-cam-demo` | For the `admin` login. Anonymous Viewer is on regardless. |
| `QUJATA_API_BASE` | empty | When set, the panel offers a "run on QUJATA" toggle that fans the curl loop out to the remote QUJATA stack instead of the local containers. Off by default — this stack IS the local backup. |
| `MARIADB_HOST` / `MARIADB_PORT` / `MARIADB_USER` / `MARIADB_PASSWORD` / `MARIADB_NAME` | empty / `3307` / `pqreact` / empty / `PQREACT` | When `MARIADB_HOST` + `MARIADB_PASSWORD` set, the panel writes one summary row per completed run into `PQREACT.performance_test` (UPSERT, source=`cam-context-agility`). |
| `CAM_SOURCE_TAG` | `cam-context-agility` | Tag for the MariaDB summary rows. |

### 5.6 Differences vs the original two-VM QUJATA setup

| | Original (QUJATA) | This (CAM-local backup) |
|---|---|---|
| Where | 2 VMs (nginx host + curl host) | 1 VM (CAM host) |
| Power metrics | per-VM, isolated | shared host-level (both dashboards read the same powerstat — trade-off of single-VM) |
| Driver UI | QUJATA portal NestJS app | this FastAPI panel |
| Algorithm matrix | identical (same OQS groups) | identical |
| Test format | curl POST to nginx :4433 | identical |
| Storage | QUJATA's MySQL `qujata.test_suites` | CAM's InfluxDB `cam_demo_handshake` measurement (cheaper, time-series-native) |
| Failure mode | needs both VMs | runs anywhere Docker runs |

The panel is intentionally **not** trying to be a full QUJATA portal replacement — it is a single-page focused demo for showing the handshake matrix end-to-end on one machine, with the same visual shape as the original (test execution + two Grafana dashboards on the same screen).

### 5.7 Panel runtime architecture (`panel/runner.py`)

Per-run flow:
1. `POST /api/runs` allocates a `RunState` keyed by a 12-hex `run_id` and stores it in an in-memory dict (single-replica, single-process).
2. An asyncio task is spawned that runs `iterations` × `curl --tlsv1.3 --curves <algorithm> ...` invocations via `docker exec` into the curl container.
3. `curl -w` emits a single JSON line per handshake with `{namelookup_ms, connect_ms, appconnect_ms, pretransfer_ms, starttransfer_ms, total_ms, bytes_in, bytes_out, http_code}`.
4. Each parsed handshake produces a `HandshakeSample`; the line is published to:
   - the run's `asyncio.Queue` (consumed by the SSE endpoint, back-pressure-safe with drop-oldest if a browser falls behind by >1024 lines),
   - the run's `recent_lines` deque (last 512 lines, for SSE replay).
5. Per-handshake telemetry optionally lands in InfluxDB (`cam_demo_handshake` measurement) when `INFLUX_URL` + `INFLUX_TOKEN` are set.
6. At end-of-run, a single summary row is optionally UPSERTed into `PQREACT.performance_test` via `pymysql` (when `MARIADB_HOST` + `MARIADB_PASSWORD` are set).
7. Final state: `status ∈ {queued, running, done, failed, cancelled}`, summary with `n`, `ok`, `appconnect_ms_p50`, `appconnect_ms_p95`, `total_ms_p50`, `total_ms_p95`, `bytes_in_total`.

The MariaDB UPSERT uses `ON DUPLICATE KEY UPDATE` keyed on `(algorithm_name, message_size, size_kind, source)` — pre-existing CAM rows with NULL `duration` (from a prior pipeline that didn't measure) get overwritten with real values.

---

## 6. Testing

### 6.1 `Unit Testing/`

Unit tests for the root scripts (`performance_test.py`, `W_T_retrieval.py`):
- `test_performance_test.py`, `test_performance_edge_cases.py`
- `test_get_temperatures.py`, `test_get_power_consumption.py`, `test_send_to_influxdb.py`, `test_main_loop_integration.py`
- Markdown specs: `Performance_unit_testing.md`, `W_T_retrieval Unit_Testing.md`
- Runner: `unittesting.py`

### 6.2 `Portal Testing/`

Higher-level integration coverage exercising the panel-side stack:
- `portal_testing.py`, `Portaltesting.md`

---

## 7. Configuration-knob summary

Standalone CAM:
```
CAM_INFLUXDB_URL   CAM_INFLUXDB_TOKEN   CAM_INFLUXDB_ORG   CAM_INFLUXDB_BUCKET
CAM_QUJATA_URL                                      (→ QUJATA legacy /curl)
```

`pqreact_hooks/` bridge:
```
MCP_DB_HOST   MCP_DB_PORT   MCP_DB_USER   MCP_DB_PASSWORD   MCP_DB_NAME
QUJATA_BASE   QUJATA_LEGACY
CHAT_URL
CAM_SOURCE_TAG
```

Demo panel:
```
CAM_PUBLIC_HOST   QUJATA_API_BASE
INFLUX_URL   INFLUX_ORG   INFLUX_BUCKET   INFLUX_TOKEN
GRAFANA_ADMIN_PASSWORD   GRAFANA_DASH_SERVER   GRAFANA_DASH_CLIENT   GRAFANA_DEFAULT_RANGE
MARIADB_HOST   MARIADB_PORT   MARIADB_USER   MARIADB_PASSWORD   MARIADB_NAME
CAM_SOURCE_TAG
CURL_CONTAINER   NGINX_HOST   NGINX_PORT
```

No secret is hardcoded — all secrets and IPs come from `.env`.

---

## 8. External integration points

| External system | Mechanism | Direction | Used by |
|---|---|---|---|
| QUJATA testbed (`legacy /curl` and newer iperf-shape API) | HTTP POST | CAM → QUJATA | `performance_test.py`, `mcp_hook.py` |
| InfluxDB v2 | HTTP write API | CAM → InfluxDB | `W_T_retrieval.py`, demo panel `runner.py` |
| Telegraf | InfluxDB output plugin | Telegraf → InfluxDB | host metrics |
| Grafana | data-source-provisioning | Grafana → InfluxDB | dashboards |
| PQ-REACT MCP MariaDB (`PQREACT.performance_test`) | `pymysql` UPSERT | CAM → MCP MariaDB | `mcp_hook.py`, demo panel `runner.py` |
| PQ-REACT chat UI | HTTP POST `/chat` | CAM → chat | `chat_advisor.py`, `cam_runner.py`, `closed_loop.py` |
| OQS-OpenSSL nginx + curl | `docker exec` curl | panel → containers | demo panel `runner.py` |
| MCP `apply_pqc_configuration` tool | chat-mediated | CAM → MCP | `closed_loop.py` |

---

## 9. Versioning / state of the code

- `performance_test.py` and `panel/algorithms.py` were updated in **May 2026** to drop pre-FIPS-203 names (`kyber*`, `hqc*`, `x25519_kyber768`) — the current `openquantumsafe/oqs-provider` build no longer accepts them as TLS group names. The standardised ML-KEM identifiers are the replacement.
- `pqreact_hooks/` was added as the PQ-REACT bridge and is **opt-in**; the directory can be deleted without affecting standalone CAM.
- The demo panel (`cam_demo_panel/`) is a separate subsystem that bundles the QUJATA scenario into a single VM. Its visual identity was unified with the rest of the PQ-REACT testbed (the "PQ-REACT console" light skin in `pq-console.css`) in May 2026.

---

## 10. Guidance for the documentation author (the LLM consuming this briefing)

Suggested structure for the deliverable:

1. **Purpose and context** — what CAM is, why the PQ-REACT framework needs it, the gap between current state ("loop and visualise") and design goal ("dynamically select the optimal configuration").
2. **High-level architecture** — three layers: (a) measurement (CAM standalone), (b) data plane (InfluxDB, Grafana, MariaDB), (c) recommendation / agility (chat-mediated, closed-loop).
3. **Standalone CAM data flow** — `performance_test.py` → QUJATA → InfluxDB → Grafana; `W_T_retrieval.py` + Telegraf → InfluxDB.
4. **PQ-REACT bridge** — `mcp_hook.py` ⇒ MariaDB; `chat_advisor.py` ⇒ chat; `cam_runner.py` ⇒ 4-phase loop; `closed_loop.py` ⇒ 5-phase self-configuring loop with apply + verify.
5. **Demo panel** — four-container bundle, FastAPI UI, REST + SSE, OQS-OpenSSL nginx/curl, embedded Grafana iframes; per-handshake samples land in InfluxDB and a summary row optionally in MariaDB.
6. **Testing** — unit and portal coverage.
7. **Configuration model** — `.env`-driven, no hardcoded testbed addresses, separation between standalone and bridge knobs.
8. **Limitations and roadmap** — current implementation does not yet dynamically select algorithms; the closed-loop logic is implemented (`closed_loop.py`) but requires `KATANA_ALLOW_CONFIGURE=true` on the MCP for the apply step; HQC unsupported by current OQS provider.

Recommended figures:
- **Figure 1** — the system map from §4.6 (CAM → MCP MariaDB → chat UI).
- **Figure 2** — the demo panel architecture from §5.1.
- **Figure 3** — `closed_loop.py` 5-phase flow (the design-intent loop CAM was built to close).

Recommended tables:
- The algorithm matrix (§3.1).
- The InfluxDB measurement schema (§3.3).
- The demo panel REST API (§5.3).
- The configuration-env-var summary (§7).

---

*End of briefing. Authoritative repository sources for fact-checking: `README.md`, `pqreact_hooks/README.md`, `pqreact_hooks/cam_demo_panel/README.md`, `performance_test.py` (header comment), `W_T_retrieval.py` (header comment), `pqreact_hooks/closed_loop.py` (module docstring), `pqreact_hooks/cam_demo_panel/panel/algorithms.py` (header comment), `pqreact_hooks/cam_demo_panel/panel/runner.py`.*
