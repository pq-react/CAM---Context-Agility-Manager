"""FastAPI control panel for the CAM-local PQC handshake demo.

Endpoints:
  GET  /                       — single-page UI (form + log + 2 Grafana iframes)
  GET  /api/algorithms         — list of supported PQC + classical algorithms
  GET  /api/runs               — recent runs + status
  POST /api/runs               — start a run; body: {algorithm, iterations, payload_bytes}
  POST /api/runs/{id}/stop     — request cancel
  GET  /api/runs/{id}          — status + summary for one run
  GET  /api/runs/{id}/stream   — SSE: live log lines, replays recent_lines first
  GET  /api/health             — liveness probe (used by docker compose)
  GET  /api/iframe-urls        — what the SPA should put in its <iframe src=…>

The page itself is templated server-side so the iframe URLs (which depend
on env vars set at deploy time) are resolved before the browser sees them.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

import algorithms
import runner


# ── env-driven config (resolved once at process start) ───────────────────

GRAFANA_BASE   = os.getenv("GRAFANA_BASE", "http://localhost:3001").rstrip("/")
DASH_SERVER    = os.getenv("GRAFANA_DASH_SERVER", "cam-demo-server")
DASH_CLIENT    = os.getenv("GRAFANA_DASH_CLIENT", "cam-demo-client")
DEFAULT_RANGE  = os.getenv("GRAFANA_DEFAULT_RANGE", "now-5m")

CURL_CONTAINER = os.getenv("CURL_CONTAINER", "pqreact-cam-pqc-curl")
NGINX_HOST     = os.getenv("NGINX_HOST",     "172.30.0.10")
NGINX_PORT     = os.getenv("NGINX_PORT",     "4433")


# ── app ──────────────────────────────────────────────────────────────────

app = FastAPI(title="CAM PQC Demo Panel", version="1.0.0")

# Static assets (panel.css, panel.js).
WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# Jinja templates (only one — index.html — but using the env keeps options
# open if we ever want to split it).
_jinja = Environment(
    loader=FileSystemLoader(str(WEB_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _iframe_url(uid: str) -> str:
    """Compose a Grafana 'kiosk-tv' embed URL. kiosk=tv hides chrome but
    keeps the timepicker; refresh=10s polls; theme=dark matches the panel."""
    return (
        f"{GRAFANA_BASE}/d/{uid}"
        f"?orgId=1&refresh=10s&kiosk=tv&theme=dark&from={DEFAULT_RANGE}&to=now"
    )


# ── routes ───────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"ok": True, "version": app.version}


@app.get("/api/algorithms")
async def list_algorithms():
    return {
        "algorithms": algorithms.as_dicts(),
        "defaults_quick": algorithms.DEFAULT_ALGOS_QUICK,
        "defaults_full":  algorithms.DEFAULT_ALGOS_FULL,
        "default_iterations": algorithms.DEFAULT_ITERATIONS,
        "default_payload_bytes": algorithms.DEFAULT_PAYLOAD_BYTES,
    }


@app.get("/api/iframe-urls")
async def iframe_urls():
    return {
        "server": _iframe_url(DASH_SERVER),
        "client": _iframe_url(DASH_CLIENT),
        "grafana_base": GRAFANA_BASE,
    }


class RunRequest(BaseModel):
    algorithm: str = Field(..., examples=["mlkem768"])
    iterations: int = Field(
        default=algorithms.DEFAULT_ITERATIONS, ge=1, le=10000,
        description="Number of curl invocations.",
    )
    payload_bytes: int = Field(
        default=algorithms.DEFAULT_PAYLOAD_BYTES, ge=0, le=10 * 1024 * 1024,
        description="Size of the body POSTed to nginx, in bytes.",
    )


@app.post("/api/runs")
async def post_run(req: RunRequest):
    if req.algorithm not in algorithms.BY_ID:
        raise HTTPException(400, f"unknown algorithm '{req.algorithm}'. "
                                  f"Use GET /api/algorithms to see the list.")
    spec = runner.RunSpec(
        algorithm     = req.algorithm,
        iterations    = req.iterations,
        payload_bytes = req.payload_bytes,
    )
    run = await runner.start_run(spec)
    return {
        "run_id": run.run_id,
        "status": run.status,
        "stream": f"/api/runs/{run.run_id}/stream",
        "config": {
            "curl_container": CURL_CONTAINER,
            "nginx":          f"{NGINX_HOST}:{NGINX_PORT}",
        },
    }


@app.get("/api/runs")
async def get_runs():
    return {"runs": runner.list_runs()}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    r = runner.get_run(run_id)
    if not r:
        raise HTTPException(404, f"run '{run_id}' not found")
    return r.public_dict()


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str):
    ok = await runner.cancel_run(run_id)
    if not ok:
        raise HTTPException(409, "run not running or already finished")
    return {"run_id": run_id, "status": "cancelling"}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    """SSE log stream. Replays the last 512 lines first so a client that
    connects mid-run sees context, then tails the queue. Terminates when
    the runner publishes the sentinel '__END__'."""
    r = runner.get_run(run_id)
    if not r:
        raise HTTPException(404, f"run '{run_id}' not found")

    async def event_stream():
        # Replay buffered context first.
        for ln in list(r.recent_lines):
            if ln == "__END__":
                continue
            yield {"event": "log", "data": ln}

        # Live tail until __END__ or client disconnects.
        while True:
            if await request.is_disconnected():
                return
            try:
                line = await asyncio.wait_for(r.queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                # Heartbeat — keeps the EventSource alive across HTTP idle
                # timeouts on flaky proxies.
                yield {"event": "ping", "data": ""}
                continue
            if line == "__END__":
                yield {"event": "end", "data": "__END__"}
                return
            yield {"event": "log", "data": line}

    return EventSourceResponse(event_stream())


# ── single-page UI ───────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    tpl = _jinja.get_template("index.html")
    html = tpl.render(
        grafana_base = GRAFANA_BASE,
        iframe_server = _iframe_url(DASH_SERVER),
        iframe_client = _iframe_url(DASH_CLIENT),
        nginx_target  = f"{NGINX_HOST}:{NGINX_PORT}",
        curl_container = CURL_CONTAINER,
    )
    return HTMLResponse(html, status_code=200)


@app.get("/favicon.ico")
async def favicon():
    p = WEB_DIR / "favicon.ico"
    if p.exists():
        return FileResponse(str(p))
    # 1×1 transparent png as a graceful no-favicon fallback.
    return JSONResponse({"ok": True}, status_code=204)
