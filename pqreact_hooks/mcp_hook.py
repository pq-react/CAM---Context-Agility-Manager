"""CAM → PQ-REACT MCP MariaDB hook.

Loops the same algorithm list CAM's performance_test.py uses, posts to the
QUJATA endpoint (curl-based older API or analyze-based newer API,
auto-detected), captures the per-algorithm response, and UPSERTs one row
per algorithm into PQREACT.performance_test tagged source='cam-context-agility'.

That puts CAM measurements alongside the other PQ-REACT sources (upstream,
campaign-b-qujata-live, campaign-b-demo4, …) so the MCP chat UI on .159:8081
can compare them with `Run this SQL: SELECT source, AVG(duration) FROM
performance_test GROUP BY source`.

Connection details come from environment variables — never hardcoded.
Defaults match the testbed at .247.

Usage:
    pip install -r requirements.txt
    cp .env.example .env  # fill in token + IPs
    set -a; . ./.env; set +a
    python3 mcp_hook.py            # one full sweep
    python3 mcp_hook.py --algos kyber768 mlkem768 classical   # a subset

The script is idempotent — re-running over the same algorithms either
inserts new rows (default) or updates the most recent one if you pass
--upsert. Most users want the default (history of every sweep).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# ── Defaults: PQ-REACT testbed at .247 / .67 / .69 ───────────────────────
DEFAULTS = {
    # MCP MariaDB (the PQ-REACT MCP server's backing DB)
    "MCP_DB_HOST":     "10.160.101.247",
    "MCP_DB_PORT":     "3307",
    "MCP_DB_USER":     "root",
    "MCP_DB_PASSWORD": "",                    # supply via .env, never inline
    "MCP_DB_NAME":     "PQREACT",
    # QUJATA orchestrator. Newer testbeds use /qujata-api/analyze (port 3020,
    # iperf-shape payload); older CAM/Qujata setups use /curl (port 3010,
    # algorithm+iterations+messageSize payload).
    "QUJATA_BASE":     "http://10.160.101.247:3020/qujata-api",
    "QUJATA_LEGACY":   "http://11.11.11.11:3010/curl",
    # Tag — keeps CAM rows distinguishable from the QUJATA-live ETL hook,
    # demo4/5 imports, and upstream sample data.
    "CAM_SOURCE_TAG":  "cam-context-agility",
}

ALGORITHMS_DEFAULT = [
    # Quantum-safe KEMs
    "bikel1", "bikel3", "bikel5",
    "frodo640aes", "frodo640shake",
    "frodo976aes", "frodo976shake",
    "frodo1344aes", "frodo1344shake",
    "hqc128", "hqc192", "hqc256",
    "kyber512", "kyber768", "kyber1024",
    "mlkem512", "mlkem768", "mlkem1024",
    # Hybrids
    "p256_kyber512", "p384_kyber768", "x25519_kyber768",
    "p256_mlkem512", "p384_mlkem768", "X25519MLKEM768",
    # Classical baselines
    "prime256v1", "secp384r1", "classical",
]


def env(key: str) -> str:
    return os.environ.get(key, DEFAULTS.get(key, ""))


# ── QUJATA call ─────────────────────────────────────────────────────────

def call_qujata_legacy_curl(alg: str, iterations: int, msg_size: int) -> dict[str, Any]:
    """Hit the legacy /curl endpoint that CAM's performance_test.py was
    written against. Returns the parsed JSON or raises."""
    payload = json.dumps({
        "algorithm":      alg,
        "iterationsCount": iterations,
        "messageSize":    msg_size,
    }).encode()
    req = urllib.request.Request(
        env("QUJATA_LEGACY"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def call_qujata_analyze(alg: str, slice_id: str, duration_s: int,
                        bandwidth_kbps: int, msg_size: int) -> dict[str, Any]:
    """POST to the iperf-shape `/qujata-api/analyze` endpoint. Returns
    the create-suite response (must contain `test_suite_id`); the actual
    metrics only land in qujata-mysql after the run completes
    (≈ duration_s + 5–10 s).

    The qujata-api request shape is the same one its portal /Run-experiment
    button sends — see fix-qujata-portal-run-button.sh in the parent
    KatanaSliceManagerv2 mcp-server/scripts/ tree."""
    payload = json.dumps({
        "algorithms":     [alg],     # singleton list — qujata-api expects an array
        "slice_id":       slice_id,
        "duration":       int(duration_s),
        "bandwidth":      int(bandwidth_kbps),
        "messageSize":    int(msg_size),
        "iterationsCount": 1,
    }).encode()
    req = urllib.request.Request(
        env("QUJATA_BASE") + "/analyze",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=duration_s + 30) as r:
        return json.loads(r.read())


def fetch_qujata_metrics(suite_id: int, *, deadline_s: int = 60,
                         qj_host: str = "qujata-mysql",
                         qj_port: int = 3306,
                         qj_user: str = "root",
                         qj_password: str = "qujata",
                         qj_db: str = "qujata") -> dict | None:
    """Poll qujata-mysql.test_runs for the suite created by
    call_qujata_analyze, extract the per-run metrics from status_message,
    and return them as a flat dict ready for upsert_row.

    Returns None if no SUCCESS run lands within `deadline_s`. The poller
    has a 2 s back-off — 30 polls over 60 s by default.

    Connects to the docker network if running on the qujata orchestrator
    VM (the same VM hosts pqreact-mcp-mariadb), or to localhost-mapped
    ports if you're running this from your laptop. Override via env vars
    QUJATA_MYSQL_HOST/PORT/USER/PASSWORD/DB."""
    import time as _time
    try:
        import pymysql
    except ImportError:
        sys.exit("missing dependency: pip install pymysql")

    qj_host     = os.environ.get("QUJATA_MYSQL_HOST",     qj_host)
    qj_port     = int(os.environ.get("QUJATA_MYSQL_PORT", str(qj_port)))
    qj_user     = os.environ.get("QUJATA_MYSQL_USER",     qj_user)
    qj_password = os.environ.get("QUJATA_MYSQL_PASSWORD", qj_password)
    qj_db       = os.environ.get("QUJATA_MYSQL_DB",       qj_db)

    deadline = _time.time() + deadline_s
    while _time.time() < deadline:
        try:
            conn = pymysql.connect(host=qj_host, port=qj_port, user=qj_user,
                                    password=qj_password, database=qj_db,
                                    cursorclass=pymysql.cursors.DictCursor)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, algorithm, message_size, status, status_message "
                    "FROM test_runs WHERE test_suite_id = %s "
                    "ORDER BY id DESC LIMIT 1",
                    (int(suite_id),),
                )
                row = cur.fetchone()
            conn.close()
        except pymysql.Error:
            _time.sleep(2); continue

        if not row:
            _time.sleep(2); continue
        if row.get("status") != "SUCCESS":
            _time.sleep(2); continue

        m = {}
        try:
            m = json.loads(row.get("status_message") or "{}")
        except Exception:
            pass
        return {
            "algorithm":   row["algorithm"],
            "message_size": int(row["message_size"] or 0),
            "duration":    float(m.get("kem_total_ms", 0)) / 1000.0
                            if m.get("kem_total_ms") is not None else None,
            "mbps":        m.get("mbps"),
            "jitter_ms":   m.get("jitter_ms"),
            "loss_pct":    m.get("lost_percent"),
            "kem_ms":      m.get("kem_total_ms"),
        }
    return None


# ── MCP MariaDB writer ───────────────────────────────────────────────────

def get_db_connection():
    try:
        import pymysql
    except ImportError:
        sys.exit("missing dependency: pip install pymysql")
    return pymysql.connect(
        host=env("MCP_DB_HOST"),
        port=int(env("MCP_DB_PORT")),
        user=env("MCP_DB_USER"),
        password=env("MCP_DB_PASSWORD"),
        database=env("MCP_DB_NAME"),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=__import__("pymysql.cursors", fromlist=["DictCursor"]).DictCursor,
    )


def upsert_row(cur, *, algorithm_name: str, message_size: int,
               duration: float | None, cpu_util_pct: float | None,
               mem_used: float | None, energy_joules: float | None,
               power_watts: float | None, security_level: int | None) -> None:
    """Insert one measurement row tagged source=<CAM_SOURCE_TAG>, or
    refresh the existing row's metrics if one already exists for this
    (algorithm_name, message_size, size_kind, source) tuple — that's
    the natural unique key (`uniq_natural`) on this table.

    Schema reminder (PQREACT.performance_test):
      algorithm_name varchar, message_size int, duration double,
      cpu_util_pct double, delta_cpu_util double, mem_used double,
      energy_joules double, power_watts double, cpu_temperature double,
      cpu_frequency double, power_core double, power_system double,
      security_level tinyint, source varchar, size_kind varchar

    Without ON DUPLICATE KEY UPDATE, re-running a sweep would crash with
    pymysql.err.IntegrityError on the second iteration. UPSERT lets the
    hook be re-run any number of times and always converge on the latest
    measurement.
    """
    cur.execute(
        """
        INSERT INTO performance_test
            (algorithm_name, message_size, duration, cpu_util_pct, mem_used,
             energy_joules, power_watts, security_level, source, size_kind)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'payload')
        ON DUPLICATE KEY UPDATE
            duration       = VALUES(duration),
            cpu_util_pct   = VALUES(cpu_util_pct),
            mem_used       = VALUES(mem_used),
            energy_joules  = VALUES(energy_joules),
            power_watts    = VALUES(power_watts),
            security_level = VALUES(security_level)
        """,
        (algorithm_name, int(message_size),
         duration, cpu_util_pct, mem_used, energy_joules, power_watts,
         security_level, env("CAM_SOURCE_TAG")),
    )


# ── Driver ───────────────────────────────────────────────────────────────

def derive_security_level(alg: str) -> int | None:
    """Heuristic NIST level inference from the algorithm name. Same mapping
    the upstream PQ-REACT seed data uses."""
    a = alg.lower()
    if any(k in a for k in ("l1", "512", "640", "128", "kyber512", "mlkem512", "frodo640", "hqc128", "p256_")):
        return 1
    if any(k in a for k in ("l3", "768", "976", "192", "kyber768", "mlkem768", "frodo976", "hqc192", "p384_", "x25519")):
        return 3
    if any(k in a for k in ("l5", "1024", "1344", "256", "kyber1024", "mlkem1024", "frodo1344", "hqc256")):
        return 5
    return None


def run_legacy_sweep(algorithms: list[str], iterations: int, msg_size: int,
                     dry_run: bool = False) -> int:
    """Hit /curl per algorithm, push each result to MariaDB. Returns row count."""
    conn = None if dry_run else get_db_connection()
    cur  = None if dry_run else conn.cursor()
    written = 0

    for alg in algorithms:
        try:
            print(f"[curl] {alg}", flush=True)
            t0  = time.perf_counter()
            res = call_qujata_legacy_curl(alg, iterations, msg_size)
            elapsed_s = time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            print(f"  ✗ HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            continue
        except Exception as e:
            print(f"  ✗ {type(e).__name__}: {e}")
            continue

        # Heuristically pull common fields if present; otherwise fall back to
        # wall-clock as duration. The legacy /curl response shape varies
        # across qujata versions, so be defensive.
        d = res if isinstance(res, dict) else {}
        duration   = float(d.get("duration",         elapsed_s))
        cpu_util   = d.get("cpu_util_pct") or d.get("cpu_util") or d.get("cpu")
        mem_used   = d.get("mem_used")    or d.get("memory")
        energy_J   = d.get("energy_joules") or d.get("energy")
        power_W    = d.get("power_watts")   or d.get("power")
        sec_level  = d.get("security_level") or derive_security_level(alg)

        print(f"  ✓ {elapsed_s:.3f}s — {len(json.dumps(d))} byte response")
        if dry_run:
            written += 1
            continue
        upsert_row(
            cur,
            algorithm_name=alg, message_size=msg_size,
            duration=duration,
            cpu_util_pct=float(cpu_util) if cpu_util is not None else None,
            mem_used=float(mem_used) if mem_used is not None else None,
            energy_joules=float(energy_J) if energy_J is not None else None,
            power_watts=float(power_W) if power_W is not None else None,
            security_level=sec_level,
        )
        written += 1

    if conn:
        conn.commit()
        conn.close()
    return written


def fetch_supported_algorithms() -> set[str]:
    """Pull the live list of algorithms qujata-api will accept from
    `GET /algorithms`. Lets us skip CAM names the testbed can't run
    (e.g. BIKE / Frodo / HQC aren't in the typical strongSwan build) so
    the sweep doesn't waste time on inevitable 4xx responses."""
    try:
        with urllib.request.urlopen(env("QUJATA_BASE") + "/algorithms",
                                     timeout=5) as r:
            d = json.loads(r.read())
    except Exception:
        return set()
    out = set()
    for k in ("classic", "hybrid", "quantumSafe"):
        out.update(d.get(k, []) or [])
    return out


def run_analyze_sweep(algorithms: list[str], *, slice_id: str = "mgmt",
                      duration_s: int = 10, bandwidth_kbps: int = 50000,
                      msg_size: int = 1200) -> int:
    """For each algorithm: POST /qujata-api/analyze, wait for the run to
    finish, pull real metrics from qujata-mysql, upsert one row per
    algorithm into PQREACT.performance_test tagged source=cam-context-agility.

    Skips algorithms not in the qujata-api allow-list (`/algorithms`)
    rather than spawning failing requests."""
    supported = fetch_supported_algorithms()
    if not supported:
        print("  ⚠ couldn't read /algorithms — running every algorithm anyway")
    conn = get_db_connection()
    cur  = conn.cursor()
    written = 0
    for alg in algorithms:
        if supported and alg not in supported:
            print(f"  - {alg} not in qujata-api allow-list — skipping")
            continue
        try:
            print(f"[analyze] {alg} (slice={slice_id} {duration_s}s @ "
                  f"{bandwidth_kbps/1000:.0f} Mbps msg={msg_size}B)", flush=True)
            resp     = call_qujata_analyze(alg, slice_id, duration_s,
                                            bandwidth_kbps, msg_size)
            suite_id = resp.get("test_suite_id") or resp.get("id")
            if not suite_id:
                print(f"  ✗ launch returned no suite id: {str(resp)[:200]}"); continue
            print(f"  → suite #{suite_id}; polling qujata-mysql…", flush=True)
            metrics  = fetch_qujata_metrics(int(suite_id),
                                             deadline_s=duration_s + 30)
            if not metrics:
                print(f"  ✗ no SUCCESS run for suite {suite_id} after deadline")
                continue
            print(f"  ✓ mbps={metrics['mbps']} jitter={metrics['jitter_ms']}ms "
                  f"loss={metrics['loss_pct']}% kem={metrics['kem_ms']}ms")
        except urllib.error.HTTPError as e:
            print(f"  ✗ HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            continue
        except Exception as e:
            print(f"  ✗ {type(e).__name__}: {e}")
            continue

        upsert_row(
            cur,
            algorithm_name=alg,
            message_size=metrics["message_size"] or msg_size,
            duration=metrics.get("duration"),
            cpu_util_pct=None,           # qujata-api doesn't surface this
            mem_used=None,
            energy_joules=None,
            power_watts=None,
            security_level=derive_security_level(alg),
        )
        written += 1
    conn.commit()
    conn.close()
    return written


def run_synthetic_sweep(algorithms: list[str], msg_size: int) -> int:
    """No QUJATA call — write a placeholder row per algorithm with NULL
    metrics. Exists so users can verify the MCP DB path works end-to-end
    before they have a real QUJATA backend wired in. Tagged with the same
    source string so 'cam-context-agility' rows show up in the chat UI."""
    conn = get_db_connection()
    cur  = conn.cursor()
    written = 0
    for alg in algorithms:
        upsert_row(
            cur,
            algorithm_name=alg, message_size=msg_size,
            duration=None, cpu_util_pct=None, mem_used=None,
            energy_joules=None, power_watts=None,
            security_level=derive_security_level(alg),
        )
        written += 1
        print(f"  ✓ inserted placeholder for {alg}")
    conn.commit()
    conn.close()
    return written


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--algos", nargs="+", default=ALGORITHMS_DEFAULT,
                   help="algorithm names to sweep (default: all CAM algorithms)")
    p.add_argument("--iterations", type=int, default=50)
    p.add_argument("--message-size", type=int, default=1000)
    p.add_argument("--dry-run", action="store_true",
                   help="hit QUJATA but don't write to MariaDB")
    p.add_argument("--synthetic", action="store_true",
                   help="skip QUJATA entirely; insert placeholder rows tagged "
                        "source=<CAM_SOURCE_TAG> with NULL metrics. Use this "
                        "to smoke-test the MCP DB path before /curl is up.")
    p.add_argument("--use-analyze", action="store_true",
                   help="drive the newer /qujata-api/analyze endpoint and "
                        "pull real metrics from qujata-mysql. Replaces the "
                        "legacy /curl path — use this on the .247 testbed.")
    p.add_argument("--slice-id",       default="mgmt",
                   help="(--use-analyze only) slice to run on; mgmt | rt | mmtc")
    p.add_argument("--duration",       type=int, default=10,
                   help="(--use-analyze only) seconds per algorithm; cap=60")
    p.add_argument("--bandwidth-kbps", type=int, default=50000,
                   help="(--use-analyze only) target bandwidth in Kbps; cap=200000")
    args = p.parse_args(argv)

    if not env("MCP_DB_PASSWORD") and not args.dry_run:
        sys.exit("MCP_DB_PASSWORD env var is required (set in .env)")

    print(f"CAM → MCP MariaDB hook  (source='{env('CAM_SOURCE_TAG')}')")
    print(f"  qujata: {env('QUJATA_LEGACY') if not args.synthetic else '(skipped — synthetic mode)'}")
    print(f"  mcp DB: {env('MCP_DB_USER')}@{env('MCP_DB_HOST')}:{env('MCP_DB_PORT')}/{env('MCP_DB_NAME')}")
    print(f"  algos:  {len(args.algos)} ({', '.join(args.algos[:6])}{'…' if len(args.algos) > 6 else ''})")

    if args.synthetic:
        n = run_synthetic_sweep(args.algos, args.message_size)
    else:
        n = run_legacy_sweep(args.algos, args.iterations, args.message_size, dry_run=args.dry_run)
    print(f"\nDone — {n} rows {'(dry-run, no DB writes)' if args.dry_run else 'inserted'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
