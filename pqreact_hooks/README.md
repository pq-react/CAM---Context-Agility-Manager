# CAM ⇄ PQ-REACT MCP hooks

Three small Python scripts that bridge the **Context Agility Manager (CAM)** to the **PQ-REACT MCP server** (MariaDB on `10.160.101.247:3307`) and the **LLM chat pipeline** (`http://10.160.101.159:8081`) running in the *KatanaSliceManagerv2* testbed.

CAM is upstream-pristine — these hooks live in their own subdirectory (`pqreact_hooks/`) and don't touch any existing CAM file.

```
pqreact_hooks/
├── README.md              ← this file
├── .env.example           ← copy → .env and fill in MCP_DB_PASSWORD
├── requirements.txt       ← pymysql
├── mcp_hook.py            ← Phase 1: sweep QUJATA + push rows to MCP MariaDB
├── chat_advisor.py        ← Phase 2: ask the LLM to recommend / rank
└── cam_runner.py          ← orchestrator: sweep → recommend → re-sweep
```

---

## What each hook does

### `mcp_hook.py` — MCP MariaDB writer (Phase 1)

Loops the same 27 algorithm names CAM's `performance_test.py` uses (BIKE / FrodoKEM / HQC / Kyber / ML-KEM / classical / hybrids), POSTs each to your QUJATA legacy `/curl` endpoint, captures the per-algorithm response, and **UPSERTs one row per algorithm** into `PQREACT.performance_test` tagged `source='cam-context-agility'`.

That puts CAM measurements alongside the other PQ-REACT sources (`upstream`, `campaign-b-qujata-live`, `campaign-b-demo4`, …) so the chat UI can compare them with a single SQL query:

```sql
SELECT source, COUNT(*), AVG(duration), AVG(energy_joules)
FROM performance_test
GROUP BY source;
```

**Run:**
```bash
pip install -r requirements.txt
cp .env.example .env       # set MCP_DB_PASSWORD + IPs
set -a; . ./.env; set +a
python3 mcp_hook.py                              # full sweep, ~5 min
python3 mcp_hook.py --algos kyber768 mlkem768    # specific algorithms
python3 mcp_hook.py --dry-run                    # hit QUJATA but don't write
```

### `chat_advisor.py` — LLM advisor (Phase 2)

Asks the chat UI two kinds of questions, both grounded in the CAM rows you just inserted:

- **`recommend`** — *"Given my use case, security floor, payload size, and energy budget, pick ONE algorithm."* The chat agent runs SQL against `performance_test WHERE source='cam-context-agility'` and replies with `ALG=<name>` + one-sentence rationale.
- **`rank`** — *"Rank CAM-tagged algorithms by `<metric>` at security level >= N."* Returns a markdown table.

**Run:**
```bash
python3 chat_advisor.py recommend --use-case banking      --security-floor 5
python3 chat_advisor.py recommend --use-case iot-sensor   --security-floor 1 --energy-budget min
python3 chat_advisor.py rank      --metric energy_joules  --security-floor 3
```

### `cam_runner.py` — agility loop (orchestrator)

Closes the loop CAM was originally designed for:

```
[1/4] wide sweep  — every algorithm, 50 iterations each → MCP DB
[2/4] recommend   — chat picks ONE algorithm given context
[3/4] re-measure  — narrow sweep on just the chosen algorithm at 200 iters
[4/4] verdict     — JSON line with chosen, rationale, deltas
```

**Run:**
```bash
python3 cam_runner.py --use-case "banking"    --security-floor 5
python3 cam_runner.py --use-case "iot-sensor" --security-floor 1 --energy-budget min
python3 cam_runner.py --skip-wide --use-case "general"   # use existing rows
```

---

## How this plugs into the rest of the testbed

```
┌─────────────────────────────────────────────────────────────┐
│  CAM (this repo)                                            │
│    performance_test.py  W_T_retrieval.py                    │
│         ↓                    ↓                              │
│       /curl              InfluxDB                           │
└───────────┬─────────────────────────────────────────────────┘
            │
            │  pqreact_hooks/mcp_hook.py  ───────── push CAM rows ──┐
            │                                                       ↓
┌───────────────────────────────────────────────────────────────────┐
│  PQ-REACT MCP server (10.160.101.247)                             │
│   pqreact-mcp-mariadb (PQREACT.performance_test, 255+ rows)       │
│   pqreact-mcp-server  (FastMCP SSE :5040, 13 tools)               │
└────────────────────────────────────────┬──────────────────────────┘
                                         │ SSE
┌────────────────────────────────────────┴──────────────────────────┐
│  Chat UI (10.160.101.159:8081)                                    │
│   FastAPI + Ollama (llama3.1:8b on NVIDIA L4)                     │
│   pqreact_hooks/chat_advisor.py ──► /chat ◄── any browser tab     │
└───────────────────────────────────────────────────────────────────┘
```

Once `mcp_hook.py` has populated CAM rows, you can ask the chat UI in the browser — and any of the suggested questions will see CAM data alongside the other sources:

> *"Show me the 5 fastest algorithms across all message sizes."* → mixes `upstream`, `campaign-b-qujata-live`, and `cam-context-agility` rows in the answer.
>
> *"Which algorithms use the least energy at NIST L3?"* → CAM's measurements feed in directly.

---

## Configuration

All connection details come from environment variables — never hardcoded.

| Var | Default | Used by | What |
|-----|---------|---------|------|
| `MCP_DB_HOST` | `10.160.101.247` | `mcp_hook` | MCP MariaDB host |
| `MCP_DB_PORT` | `3307` | `mcp_hook` | MCP MariaDB port |
| `MCP_DB_USER` | `root` | `mcp_hook` | MCP MariaDB user |
| `MCP_DB_PASSWORD` | *(required)* | `mcp_hook` | the long random password from `pqreact-mcp-mariadb` env |
| `MCP_DB_NAME` | `PQREACT` | `mcp_hook` | database name |
| `QUJATA_BASE` | `http://10.160.101.247:3020/qujata-api` | (reserved) | newer iperf-shape API |
| `QUJATA_LEGACY` | `http://10.160.101.67:3010/curl` | `mcp_hook` | the older curl endpoint CAM was built around |
| `CHAT_URL` | `http://10.160.101.159:8081` | `chat_advisor`, `cam_runner` | chat UI base URL |
| `CAM_SOURCE_TAG` | `cam-context-agility` | all three | `source` column tag for CAM rows |

To find the MariaDB password on your testbed:
```bash
ssh localadmin@10.160.101.247 \
  "docker inspect pqreact-mcp-mariadb --format '{{range .Config.Env}}{{.}}{{\"\\n\"}}{{end}}' | grep ROOT"
```

---

## Verifying it worked

After `python3 mcp_hook.py` finishes, you should see CAM rows appear in MCP MariaDB:

```bash
ssh localadmin@10.160.101.247 \
  "docker exec pqreact-mcp-mariadb mysql -uroot -p'<PASSWORD>' -D PQREACT -e \
   \"SELECT source, COUNT(*) FROM performance_test GROUP BY source\""
```

Expected:
```
source                       COUNT(*)
upstream                     200
campaign-b-qujata-live        25
cam-context-agility           27   ← NEW from this hook
campaign-b-demo5-bench        14
campaign-b-demo4               8
…
```

The chat UI on .159:8081 will pick these up automatically — no restart needed; the agent reads the DB on every query.
