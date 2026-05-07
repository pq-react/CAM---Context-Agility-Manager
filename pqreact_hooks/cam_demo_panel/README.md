# CAM PQC handshake demo — single-page panel + 2 containers + Grafana

Self-contained backup of the original two-VM QUJATA demo. Brings the
nginx (PQC TLS server) and curl (PQC TLS client) onto the **same VM** as
CAM, drives them from a single web page, and embeds two Grafana
dashboards (server + client) as iframes alongside the test-execution
form and live algorithm log.

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

## What's in the box

| Component | Container | Purpose |
|---|---|---|
| Control panel | `pqreact-cam-demo-panel` | FastAPI on `:8083` — single-page UI + `/api/runs/*` endpoints + SSE log stream |
| PQC TLS server | `pqreact-cam-pqc-nginx` | nginx + OQS-OpenSSL on `:4433` — accepts every PQC group QUJATA exposes |
| PQC TLS client | `pqreact-cam-pqc-curl` | curl + OQS-OpenSSL — long-lived; panel `docker exec`s into it for each handshake |
| Local Grafana | `pqreact-cam-grafana` | OSS 11.2 on `:3001` — pre-provisioned with the two demo dashboards. Anonymous Viewer enabled, embedding allowed |

## Quick start

```bash
# 1. From the CAM repo root, on the CAM host:
cd pqreact_hooks/cam_demo_panel/
cp .env.example .env
# Edit .env: set CAM_PUBLIC_HOST + INFLUX_TOKEN.

# 2. Bring it up:
docker compose up -d --build

# 3. Open the panel:
open http://<cam-host>:8083/

# (The same URL is hit from any browser on the testbed VPN.)
```

When everything is healthy the panel page shows:

- **Top bar**: target nginx address + curl container name + Grafana link.
- **Left column**:
  - "Run a handshake sweep" form (algorithm dropdown grouped by family,
    iterations, payload bytes). **Run** kicks off the test;
    **Stop** cancels mid-flight; **Quick sweep** runs the four default
    algorithms back-to-back.
  - "Latest run status" — current state + p50/p95 appconnect_ms +
    bytes-in summary, refreshed at each run boundary.
  - "Live algorithm log" — every line from the runner streamed over
    SSE, including the `[n/N] mlkem768  http=200 appconnect=  4.7ms
    total=  9.1ms bytes_in=…` per-handshake summary.
- **Right column** — two iframes:
  - "nginx Server" dashboard
    (`http://<cam-host>:3001/d/cam-demo-server/?kiosk=tv`)
  - "Curl Client" dashboard
    (`http://<cam-host>:3001/d/cam-demo-client/?kiosk=tv`)
  - Each has a **refresh** button next to its iframe header that
    cache-busts the iframe `src` to force a reload (useful after a
    long quick sweep).

## Configuration knobs

All in `.env` (or set on the docker-compose command line). Defaults are
sensible for a single-VM CAM deployment.

| Var | Default | What |
|---|---|---|
| `CAM_PUBLIC_HOST` | `localhost` | Hostname/IP used in iframe `src=` URLs the **browser** fetches. Must be reachable from whatever machine opens the panel. |
| `INFLUX_URL` | `http://host.docker.internal:8086` | CAM's existing InfluxDB. The panel writes per-handshake samples there; Grafana reads from it. |
| `INFLUX_ORG` | `pqreact` | InfluxDB org. |
| `INFLUX_BUCKET` | `NUC_metrics` | Bucket Telegraf is already writing into. |
| `INFLUX_TOKEN` | _empty_ | Required if you want per-handshake samples to land in InfluxDB. Empty disables — host metrics still flow via Telegraf. |
| `GRAFANA_ADMIN_PASSWORD` | `pqreact-cam-demo` | For the `admin` login. Anonymous Viewer is on regardless. |
| `QUJATA_API_BASE` | _empty_ | When set, the panel will offer a "run on QUJATA" toggle that fans the curl loop out to the remote QUJATA stack instead of the local containers. Off by default — this stack IS the local backup. |

## API reference

The panel exposes the endpoints below. Useful for scripting or for
integrating the demo into a wider workflow (e.g. CAM's `closed_loop.py`
could in principle drive `/api/runs` instead of QUJATA directly).

| Method | Path | Purpose |
|---|---|---|
| GET  | `/`                          | The single-page UI (HTML). |
| GET  | `/api/health`                | Liveness probe (used by the docker healthcheck). |
| GET  | `/api/algorithms`            | List of supported PQC + classical algorithms with NIST level. |
| GET  | `/api/iframe-urls`           | Resolved Grafana iframe URLs (so callers can re-embed). |
| GET  | `/api/runs`                  | Recent runs, newest first. |
| POST | `/api/runs`                  | Start a run. Body: `{algorithm, iterations, payload_bytes}`. Returns `{run_id, status, stream}`. |
| GET  | `/api/runs/{id}`             | Status + summary for one run. |
| POST | `/api/runs/{id}/stop`        | Request cancel. |
| GET  | `/api/runs/{id}/stream`      | SSE log stream — lines tagged `event: log` for content, `event: ping` heartbeat, `event: end` on completion. |

Example:

```bash
# Kick off 100 ML-KEM-768 handshakes:
curl -sS -X POST http://<cam-host>:8083/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"mlkem768","iterations":100,"payload_bytes":1200}'
# {"run_id":"a1b2c3d4e5f6","status":"running","stream":"/api/runs/a1b2c3d4e5f6/stream", ... }

# Tail the log over SSE:
curl -N http://<cam-host>:8083/api/runs/a1b2c3d4e5f6/stream
```

## Telegraf / InfluxDB integration

The dashboards expect these measurements in `NUC_metrics`:

| Measurement | Source | Fields used |
|---|---|---|
| `cpu`        | Telegraf default `[[inputs.cpu]]`        | `usage_user`, with tag `cpu="cpu-total"` |
| `mem`        | Telegraf default `[[inputs.mem]]`        | `used` |
| `net`        | Telegraf default `[[inputs.net]]`        | `bytes_recv`, `bytes_sent` |
| `temp`       | Telegraf `[[inputs.temp]]`               | `temp` |
| `cpufreq`    | Telegraf `[[inputs.cpufreq]]`            | `current` |
| `powerstat`  | _custom_ — see CAM's existing `telegraf.conf` for the `[[inputs.execd]]` powerstat reader | `system_w`, `cores_w`, `package_w` |
| `cam_demo_handshake` | The panel writes this directly via the InfluxDB v2 write API | `appconnect_ms`, `total_ms`, `bytes_in`, `http_code`; tags: `algorithm`, `run_id` |

Grafana's data source is provisioned (no manual setup) — see
`grafana/provisioning/datasources/influxdb.yaml`. If your Telegraf uses
different measurement names, edit the dashboard JSONs in
`grafana/dashboards/`; they'll hot-reload on save (the provisioning
provider scans every 30 s).

## Difference vs the original two-VM QUJATA setup

| | Original (QUJATA) | This (CAM-local backup) |
|---|---|---|
| Where | 2 VMs (nginx host + curl host) | 1 VM (CAM host) |
| Power metrics | per-VM, isolated | shared host-level (both dashboards read the same powerstat — that's the trade-off of single-VM) |
| Driver UI | QUJATA portal NestJS app | this FastAPI panel |
| Algorithm matrix | identical (same OQS groups) | identical |
| Test format | curl POST to nginx :4433 | identical |
| Storage | QUJATA's MySQL `qujata.test_suites` | CAM's InfluxDB `cam_demo_handshake` measurement (cheaper, time-series-native) |
| Failure mode | needs both VMs | runs anywhere Docker runs |

The panel is intentionally **not** trying to be a full QUJATA portal
replacement — it's a single-page focused demo for showing the
handshake matrix end-to-end on one machine, with the same visual
shape as the original (test execution + two Grafana dashboards on the
same screen).

## Troubleshooting

**iframes blank / "refused to connect":** Grafana blocks embedding by
default. The compose file sets `GF_SECURITY_ALLOW_EMBEDDING=true` and
`GF_AUTH_ANONYMOUS_ENABLED=true` to make it work. Verify with
`docker exec pqreact-cam-grafana env | grep -E '^GF_'`.

**`curl exited with code 1`** in the log: the curl container can't
reach nginx. Check `docker network inspect cam-demo_cam-demo-net` —
both containers should be on subnet `172.30.0.0/24`. Sanity:
```bash
docker exec pqreact-cam-pqc-curl curl -k --tlsv1.3 \
  --curves mlkem768 https://172.30.0.10:4433/healthz
```

**No per-handshake points on dashboards:** `INFLUX_TOKEN` not set.
Run `docker logs pqreact-cam-demo-panel | grep -i influx` to confirm
the runner is silently skipping writes. Host metrics from Telegraf
will still appear regardless.

**Panel page loads, but algorithm dropdown is empty:** check the
browser console; usually a CORS issue when serving the page from
something other than the panel itself. The panel's `/` and `/api/*`
must come from the same origin.

## Files

```
cam_demo_panel/
├── README.md                         ← you are here
├── docker-compose.yml                ← the 4-service stack
├── .env.example
├── panel/
│   ├── Dockerfile                    ← FastAPI image
│   ├── requirements.txt
│   ├── api.py                        ← routes
│   ├── runner.py                     ← docker exec curl + SSE fan-out
│   ├── algorithms.py                 ← PQC + classical registry
│   └── web/
│       ├── index.html                ← Jinja-templated single page
│       ├── panel.css                 ← dark theme, two-column grid
│       └── panel.js                  ← form, SSE log, iframe refresh
├── nginx/
│   ├── Dockerfile                    ← FROM openquantumsafe/nginx
│   └── nginx.conf                    ← TLS 1.3 + every OQS group + JSON access log
├── curl/
│   └── Dockerfile                    ← FROM openquantumsafe/curl, sleep ∞
└── grafana/
    ├── provisioning/
    │   ├── datasources/influxdb.yaml ← points at CAM's InfluxDB
    │   └── dashboards/dashboards.yaml← loads JSONs from /var/lib/grafana/dashboards
    └── dashboards/
        ├── cam-demo-server.json      ← "nginx Server" dashboard
        └── cam-demo-client.json      ← "Curl Client" dashboard
```
