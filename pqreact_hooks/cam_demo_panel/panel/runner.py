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
