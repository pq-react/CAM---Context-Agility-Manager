"""PQC handshake runner.

Drives `docker exec <curl-container> curl …` against the local PQC nginx,
parses curl's verbose output for per-handshake timing, and exposes both
- a real-time line stream (consumed by the SSE endpoint in api.py)
- aggregated metrics (handshake count, mean/p95 KEM-time, transfer rate)

Optionally writes per-handshake samples to InfluxDB so the Grafana
dashboards plot algorithm-tagged points alongside Telegraf's host metrics.

Design choices that matter:
  - One subprocess per algorithm iteration (curl --tlsv1.3 --curves <algo>).
    Cheap, simple, no curl-multi orchestration. Worst case at 1000 iter is
    ~10 s of cumulative process startup at ~10 ms each — acceptable.
  - All log lines fan out via an asyncio.Queue per run. The SSE endpoint
    consumes the queue with a back-pressure-safe pattern (drop-oldest if
    the browser falls behind by > 1024 lines).
  - Run state is held in-memory (a dict keyed by run_id). The panel is
    intentionally single-process / single-replica — survives container
    restart by losing in-flight runs only, not history.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional

import httpx


# ── data shapes ──────────────────────────────────────────────────────────


@dataclass
class RunSpec:
    algorithm: str
    iterations: int
    payload_bytes: int


@dataclass
class HandshakeSample:
    """One curl handshake's measured timing, parsed from -w output."""
    algorithm: str
    namelookup_ms: float
    connect_ms: float
    appconnect_ms: float       # this is where the PQC handshake cost lives
    pretransfer_ms: float
    starttransfer_ms: float
    total_ms: float
    bytes_in: int
    bytes_out: int
    http_code: int


@dataclass
class RunState:
    run_id: str
    spec: RunSpec
    started_at: float
    status: str = "queued"         # queued | running | done | failed | cancelled
    finished_at: Optional[float] = None
    samples: list[HandshakeSample] = field(default_factory=list)
    error: Optional[str] = None

    # Live log fan-out. SSE clients subscribe to .queue.
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2048))
    # Recent N lines for replay when a client connects mid-run.
    recent_lines: deque = field(default_factory=lambda: deque(maxlen=512))
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def public_dict(self) -> dict:
        s = asdict(self.spec)
        return {
            "run_id":      self.run_id,
            "spec":        s,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "status":      self.status,
            "n_samples":   len(self.samples),
            "error":       self.error,
            "summary":     summarise(self.samples),
        }


# ── public registry of runs ──────────────────────────────────────────────

_RUNS: dict[str, RunState] = {}


def get_run(run_id: str) -> Optional[RunState]:
    return _RUNS.get(run_id)


def list_runs() -> list[dict]:
    """Recent runs, newest first. The panel UI shows the last ~20."""
    return [r.public_dict() for r in sorted(
        _RUNS.values(), key=lambda r: r.started_at, reverse=True
    )]


# ── runner ───────────────────────────────────────────────────────────────

# `curl -w` format string — produces ONE JSON line per request. Easier and
# less brittle than parsing -v stderr. Comma-separated keys must match
# HandshakeSample fields below.
_CURL_W_FMT = (
    '{"namelookup_ms":%{time_namelookup},'
    '"connect_ms":%{time_connect},'
    '"appconnect_ms":%{time_appconnect},'
    '"pretransfer_ms":%{time_pretransfer},'
    '"starttransfer_ms":%{time_starttransfer},'
    '"total_ms":%{time_total},'
    '"bytes_in":%{size_download},'
    '"bytes_out":%{size_upload},'
    '"http_code":%{http_code}}\\n'
)


async def start_run(spec: RunSpec) -> RunState:
    """Spawn an asyncio task that runs `iterations` handshakes against the
    nginx container with `algorithm` and pushes per-line + per-sample data
    to the run's queue. Returns immediately with the run state."""
    run = RunState(
        run_id     = uuid.uuid4().hex[:12],
        spec       = spec,
        started_at = time.time(),
    )
    _RUNS[run.run_id] = run
    asyncio.create_task(_drive_run(run))
    return run


async def cancel_run(run_id: str) -> bool:
    run = _RUNS.get(run_id)
    if not run or run.status not in ("queued", "running"):
        return False
    run.cancel_event.set()
    return True


async def _drive_run(run: RunState) -> None:
    run.status = "running"
    await _publish(run, f"=== run {run.run_id} starting · "
                        f"alg={run.spec.algorithm} · "
                        f"iter={run.spec.iterations} · "
                        f"payload={run.spec.payload_bytes}B ===")

    container = os.getenv("CURL_CONTAINER", "pqreact-cam-pqc-curl")
    nginx_host = os.getenv("NGINX_HOST", "172.30.0.10")
    nginx_port = os.getenv("NGINX_PORT", "4433")
    payload = "x" * max(0, run.spec.payload_bytes)

    # The actual curl command. -k because we use a self-signed cert in the
    # demo; --curves selects the PQC group; -w prints our JSON line.
    # The payload is sent as a body so nginx logs a real POST (matches the
    # screenshot's "POST / HTTP/1.1 200" lines).
    curl_cmd = [
        "curl", "-sS", "-k",
        "--tlsv1.3",
        "--curves", run.spec.algorithm,
        "-X", "POST",
        "-H", "Content-Type: application/octet-stream",
        "--data-binary", f"@-",
        "-o", "/dev/null",
        "-w", _CURL_W_FMT,
        f"https://{nginx_host}:{nginx_port}/",
    ]

    try:
        for i in range(1, run.spec.iterations + 1):
            if run.cancel_event.is_set():
                run.status = "cancelled"
                await _publish(run, f"=== cancelled at iter {i-1}/{run.spec.iterations} ===")
                break

            sample = await _one_handshake(container, curl_cmd, payload, run.spec.algorithm)
            if sample is None:
                # _one_handshake already logged the error.
                continue
            run.samples.append(sample)
            await _publish(
                run,
                f"[{i:4d}/{run.spec.iterations}] {run.spec.algorithm:<22} "
                f"http={sample.http_code} "
                f"appconnect={sample.appconnect_ms*1000:6.1f}ms "
                f"total={sample.total_ms*1000:6.1f}ms "
                f"bytes_in={sample.bytes_in}",
            )
            await _maybe_emit_influx(sample, run)
        else:
            run.status = "done"
            await _publish(run, f"=== run {run.run_id} done · "
                                f"{len(run.samples)} handshakes ===")
            # Persist one summary row per (algorithm, payload_bytes) to the
            # PQ-REACT MariaDB so the chat's `source='cam-context-agility'`
            # query sees the new data. Before this hook the panel only
            # wrote per-handshake samples to InfluxDB (Grafana path) and
            # never reached MariaDB — discovered 2026-05 when a BIKE-L1
            # panel sweep with 100/100 OK didn't surface in the chat's
            # "Compare CAM measurements to campaign-b-qujata-live" reply.
            await _maybe_emit_mariadb(run)
    except Exception as e:
        run.status = "failed"
        run.error = repr(e)
        await _publish(run, f"=== FAILED: {e!r} ===")
    finally:
        run.finished_at = time.time()
        # Mark queue-end so any SSE clients can disconnect cleanly.
        await _publish(run, "__END__")


async def _one_handshake(container: str, curl_cmd: list[str],
                         payload: str, algorithm: str) -> Optional[HandshakeSample]:
    """Run a single curl invocation inside the curl container.

    docker exec -i <container> curl … <<<payload
    """
    docker_cmd = ["docker", "exec", "-i", container, *curl_cmd]
    proc = await asyncio.create_subprocess_exec(
        *docker_cmd,
        stdin =asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(payload.encode())
    if proc.returncode != 0:
        return None  # caller continues
    line = out.decode().strip().splitlines()[-1] if out else ""
    try:
        d = json.loads(line)
    except Exception:
        return None
    return HandshakeSample(algorithm=algorithm, **d)


async def _publish(run: RunState, line: str) -> None:
    run.recent_lines.append(line)
    try:
        run.queue.put_nowait(line)
    except asyncio.QueueFull:
        # Drop the oldest queued line — slow client shouldn't stall the run.
        try:
            run.queue.get_nowait()
        except Exception:
            pass
        try:
            run.queue.put_nowait(line)
        except Exception:
            pass


# ── optional InfluxDB emission ───────────────────────────────────────────

# Cached httpx client so we don't reopen a connection per sample.
_INFLUX_CLIENT: Optional[httpx.AsyncClient] = None


async def _maybe_emit_influx(sample: HandshakeSample, run: RunState) -> None:
    """Best-effort write of one Influx Line Protocol point. Silently no-op
    when INFLUX_TOKEN is empty (the default — useful for laptops)."""
    url   = os.getenv("INFLUX_URL", "")
    token = os.getenv("INFLUX_TOKEN", "")
    org   = os.getenv("INFLUX_ORG", "pqreact")
    bucket = os.getenv("INFLUX_BUCKET", "NUC_metrics")
    if not (url and token):
        return
    line = (
        f"cam_demo_handshake,algorithm={sample.algorithm},run_id={run.run_id} "
        f"appconnect_ms={sample.appconnect_ms*1000},"
        f"total_ms={sample.total_ms*1000},"
        f"bytes_in={sample.bytes_in}i,"
        f"http_code={sample.http_code}i "
        f"{int(time.time() * 1e9)}"
    )
    global _INFLUX_CLIENT
    if _INFLUX_CLIENT is None:
        _INFLUX_CLIENT = httpx.AsyncClient(
            base_url=url, timeout=httpx.Timeout(2.0),
            headers={"Authorization": f"Token {token}"},
        )
    try:
        await _INFLUX_CLIENT.post(
            "/api/v2/write",
            params={"org": org, "bucket": bucket, "precision": "ns"},
            content=line.encode(),
        )
    except Exception:
        # Don't let InfluxDB hiccups break the panel — host metrics from
        # Telegraf will still flow.
        pass


# ── PQ-REACT MariaDB write (end-of-run summary row) ──────────────────────
#
# Optional — fires only when MARIADB_HOST + MARIADB_PASSWORD are set
# (the same gate pattern as _maybe_emit_influx). Inserts one row into
# PQREACT.performance_test with the run's p50 handshake time as
# `duration`, tagged source='cam-context-agility' so the chat's
# regulation/performance specialists can compare it against
# campaign-b-qujata, upstream, etc.
#
# Connects via pymysql lazily — no global pool, the panel does ≤ one
# write per completed run so the per-write connect overhead doesn't
# matter. Silent best-effort: connection failures must NEVER mark a
# successful handshake run as failed.

_MARIADB_KEEP_ALIVE_S = 60.0  # noqa: F841 — reserved for future pool
_NIST_BY_ID: dict = {}        # filled on first call

def _nist_level_for(algo_id: str) -> int | None:
    """Look up the algorithm's NIST PQC security level (1, 3, 5) so the
    performance_test row carries it. Falls back to None for purely
    classical entries (prime256v1 / secp384r1 have no NIST PQC level)."""
    global _NIST_BY_ID
    if not _NIST_BY_ID:
        try:
            from panel.algorithms import BY_ID
            _NIST_BY_ID = {a_id: a.nist_l for a_id, a in BY_ID.items()}
        except Exception:
            _NIST_BY_ID = {}
    return _NIST_BY_ID.get(algo_id)


async def _maybe_emit_mariadb(run: RunState) -> None:
    """Insert one row into PQREACT.performance_test for the completed run.
    No-op when MARIADB_HOST / MARIADB_PASSWORD are unset (laptops, dev).
    """
    host = os.getenv("MARIADB_HOST", "")
    pwd  = os.getenv("MARIADB_PASSWORD", "")
    if not (host and pwd):
        await _publish(run,
            "(MariaDB not configured — set MARIADB_HOST and "
            "MARIADB_PASSWORD on the panel container to mirror summary "
            "rows into PQREACT.performance_test.)")
        return
    if not run.samples:
        await _publish(run, "(no samples — skipping MariaDB insert)")
        return

    s = summarise(run.samples)
    # `duration` in performance_test is seconds (QUJATA convention).
    # We use total_ms_p50 → seconds; appconnect would be more PQC-pure
    # but the existing rows from QUJATA use total time so we match.
    duration_s = s.get("total_ms_p50", 0.0) / 1000.0

    port = int(os.getenv("MARIADB_PORT", "3307"))
    user = os.getenv("MARIADB_USER", "pqreact")
    db   = os.getenv("MARIADB_NAME", "PQREACT")
    tag  = os.getenv("CAM_SOURCE_TAG", "cam-context-agility")
    sec  = _nist_level_for(run.spec.algorithm)

    def _do_upsert():
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, user=user, password=pwd, database=db,
            connect_timeout=5, read_timeout=5, write_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                # ON DUPLICATE KEY UPDATE because the table has a UNIQUE
                # constraint on (algorithm_name, message_size, size_kind,
                # source) — without this, the second run for the same
                # tuple hits IntegrityError 1062 and the new measurement
                # is lost. The pre-existing CAM rows often have NULL
                # duration from a prior pipeline that didn't measure; the
                # UPSERT path overwrites those NULLs with real values.
                cur.execute(
                    "INSERT INTO performance_test "
                    "(algorithm_name, message_size, duration, "
                    " security_level, source, size_kind) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE "
                    " duration       = VALUES(duration), "
                    " security_level = COALESCE(security_level, VALUES(security_level))",
                    (run.spec.algorithm, run.spec.payload_bytes,
                     duration_s, sec, tag, "payload"),
                )
                rows = cur.rowcount  # 1 = inserted, 2 = updated, 0 = no change
            conn.commit()
            return rows
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_do_upsert)
        action = {1: "inserted", 2: "updated"}.get(rows, "no-op")
        msg = (f"=== MariaDB: row {action} "
               f"(algorithm={run.spec.algorithm}, "
               f"message_size={run.spec.payload_bytes}, "
               f"duration={duration_s:.4f}s, source={tag}) ===")
        # print() so docker logs sees it; _publish() so SSE clients see it.
        print(f"[runner.mariadb] {msg}", flush=True)
        await _publish(run, msg)
    except Exception as e:
        # Don't break a successful sweep over a DB write hiccup. The
        # operator's data is still in InfluxDB + memory.
        msg = f"(MariaDB write skipped: {type(e).__name__}: {e})"
        print(f"[runner.mariadb] {msg}", flush=True)
        await _publish(run, msg)


# ── summary stats over the samples (for the public_dict roll-up) ─────────

def summarise(samples: list[HandshakeSample]) -> dict:
    if not samples:
        return {"n": 0}
    appconnects = sorted(s.appconnect_ms for s in samples)
    totals      = sorted(s.total_ms      for s in samples)
    n = len(samples)

    def pct(xs, p):
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return xs[idx] * 1000.0  # seconds → ms

    return {
        "n":                  n,
        "ok":                 sum(1 for s in samples if 200 <= s.http_code < 300),
        "appconnect_ms_p50":  round(pct(appconnects, 0.50), 2),
        "appconnect_ms_p95":  round(pct(appconnects, 0.95), 2),
        "total_ms_p50":       round(pct(totals,      0.50), 2),
        "total_ms_p95":       round(pct(totals,      0.95), 2),
        "bytes_in_total":     sum(s.bytes_in for s in samples),
    }
