# CAM host base stack (InfluxDB + Telegraf)

Snapshot of the compose project that ran at `/opt/cam` on the CAM testbed
host before it was decommissioned (2026-11-10). On that host the layout was:

| Testbed path | Repo path |
|---|---|
| `/opt/cam/docker-compose.yml`, `/opt/cam/telegraf.conf` | `deploy/cam-host/` (this directory) |
| `/opt/cam/cam_demo_panel/` | `pqreact_hooks/cam_demo_panel/` |
| `/opt/cam/pqreact_hooks/` | `pqreact_hooks/` |

Services:

| Container | Image | Purpose |
|---|---|---|
| `cam-influxdb` | `influxdb:2.7` | Bucket `NUC_metrics` (168 h retention), `:8086` |
| `cam-telegraf` | `telegraf:1.31` | Host metrics (cpu, mem, disk, diskio, kernel, processes, system, net) every 1 s |

## Run

```bash
cd deploy/cam-host
cp .env.example .env          # set INFLUX_PASSWORD and INFLUX_TOKEN
docker compose up -d
```

Then bring up `pqreact_hooks/cam_demo_panel` with the same `INFLUX_TOKEN`.

Differences from the testbed copy: credentials moved to `.env` (they were
hard-coded), and `telegraf.conf` is mounted relative to this directory
instead of from `/opt/cam`.
