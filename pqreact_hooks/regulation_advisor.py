"""CAM → PQ-REACT regulatory advisor.

Closes the loop opened by Phase 1 of the recommendation engine. The
chat agent on the GPU VM has three new [REGULATIONS] tools and four
[INVENTORY] tools backed by curated obligation data + (eventually)
CBOM-derived inventory. This script fires natural-language queries
that route the agent to those tools and prints the response, so a
CAM sweep can finish with a regulatory readout.

Three subcommands, one per primary use case:

    compliance   "Where am I non-compliant in sector X for the
                  algorithms I just measured?"
                  Auto-pulls the latest CAM-tagged algorithm names
                  from MCP MariaDB if --algorithms isn't supplied.

    timeline     "What's the PQC migration timeline for sector X?"

    prioritize   "Recommend a migration priority for sector X"
                  Marquee tool — single-call inventory + regulations +
                  performance_test synthesis.

Connection (set in .env, gitignored):
    CHAT_URL    http://<chat-ui-host>:8081
    MCP_DB_*    only required for `compliance` without --algorithms

Examples:
    python3 regulation_advisor.py compliance --sector telco
    python3 regulation_advisor.py compliance --sector health \\
            --algorithms ECDHE-secp256r1,ECDSA-P256,AES-128-GCM
    python3 regulation_advisor.py timeline   --sector energy
    python3 regulation_advisor.py prioritize --sector financial
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULTS = {
    "CHAT_URL":         "",   # required — set in .env
    "CAM_SOURCE_TAG":   "cam-context-agility",
    "MCP_DB_HOST":      "",
    "MCP_DB_PORT":      "3307",
    "MCP_DB_USER":      "root",
    "MCP_DB_PASSWORD":  "",
    "MCP_DB_NAME":      "PQREACT",
}

VALID_SECTORS = ("energy", "telco", "health", "financial",
                 "cross-sector", "public")


def env(key: str) -> str:
    return os.environ.get(key, DEFAULTS.get(key, ""))


def chat(query: str, timeout: int = 180) -> dict:
    """POST one query to the chat UI's /chat endpoint. Returns the
    parsed JSON: {response, tool_calls?}."""
    if not env("CHAT_URL"):
        sys.exit("CHAT_URL is required (set in .env, e.g. http://<host>:8081)")
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        env("CHAT_URL").rstrip("/") + "/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _latest_cam_algorithms(limit: int = 10) -> list[str]:
    """Pull the most-recently-measured CAM-tagged algorithm names from
    MCP MariaDB. Returns an empty list on any failure (caller falls back
    to a generic 'classical' / 'rsa' / 'ecdh' query)."""
    if not env("MCP_DB_HOST") or not env("MCP_DB_PASSWORD"):
        return []
    try:
        import pymysql
    except ImportError:
        return []
    try:
        conn = pymysql.connect(
            host=env("MCP_DB_HOST"),
            port=int(env("MCP_DB_PORT")),
            user=env("MCP_DB_USER"),
            password=env("MCP_DB_PASSWORD"),
            database=env("MCP_DB_NAME"),
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT algorithm_name FROM performance_test "
                "WHERE source = %s ORDER BY algorithm_name LIMIT %s",
                (env("CAM_SOURCE_TAG"), int(limit)),
            )
            rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def cmd_compliance(sector: str, algorithms: list[str]) -> dict:
    """Ask the agent for a compliance gap; expected to route to
    [REGULATIONS] get_compliance_gap."""
    if not algorithms:
        algorithms = _latest_cam_algorithms() or [
            "classical", "rsa", "ecdh", "ecdsa",
        ]
    alg_list = ", ".join(f"'{a}'" for a in algorithms)
    q = (
        f"Compliance gap analysis for the {sector} sector when we deploy "
        f"these algorithms: [{alg_list}]. Use the get_compliance_gap tool "
        f"with sector='{sector}' and current_algorithms=[{alg_list}]. "
        f"Forward the resulting markdown table verbatim."
    )
    return chat(q)


def cmd_timeline(sector: str) -> dict:
    """Ask the agent for the PQC migration timeline; expected to route
    to [REGULATIONS] get_pqc_timeline."""
    q = (
        f"Show me the PQC migration timeline for the {sector} sector. "
        f"Use the get_pqc_timeline tool with sector='{sector}'. "
        f"Forward the markdown table verbatim — do not paraphrase deadlines."
    )
    return chat(q)


def cmd_prioritize(sector: str) -> dict:
    """Ask the agent for migration priority; expected to route to
    [INVENTORY] recommend_migration_priority (single-tool synthesis
    that joins inventory + obligations + perf benchmarks)."""
    q = (
        f"What should I migrate first in the {sector} sector? "
        f"Call recommend_migration_priority with sector='{sector}' and "
        f"forward the response verbatim. Don't paraphrase the deadline, "
        f"the recommended algorithm families, or the perf numbers."
    )
    return chat(q)


def _print_response(resp: dict) -> None:
    """Pretty-print a chat response with its tool_calls trace."""
    calls = resp.get("tool_calls") or []
    if calls:
        print("─── tool_calls ───", file=sys.stderr)
        for c in calls:
            name = c.get("name", "?")
            args = c.get("arguments") or c.get("args") or {}
            print(f"  {name}({args})", file=sys.stderr)
        print("─" * 18, file=sys.stderr)
    print(resp.get("response", "(no response)"))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="CAM regulatory + inventory advisor — fires NL queries "
                    "that route to the [REGULATIONS] / [INVENTORY] MCP tools "
                    "added in Phase 1 of the recommendation engine.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("compliance",
                        help="get_compliance_gap for a sector")
    pc.add_argument("--sector", required=True, choices=VALID_SECTORS)
    pc.add_argument("--algorithms",
                    help="comma-separated algorithm names; if omitted, "
                         "the latest CAM-tagged algorithms are pulled "
                         "from MCP MariaDB")

    pt = sub.add_parser("timeline",
                        help="get_pqc_timeline for a sector")
    pt.add_argument("--sector", required=True, choices=VALID_SECTORS)

    pp = sub.add_parser("prioritize",
                        help="recommend_migration_priority for a sector")
    pp.add_argument("--sector", required=True, choices=VALID_SECTORS)

    args = p.parse_args(argv)

    try:
        if args.cmd == "compliance":
            algs = []
            if args.algorithms:
                algs = [a.strip() for a in args.algorithms.split(",") if a.strip()]
            resp = cmd_compliance(args.sector, algs)
        elif args.cmd == "timeline":
            resp = cmd_timeline(args.sector)
        else:
            resp = cmd_prioritize(args.sector)
    except urllib.error.URLError as e:
        sys.exit(f"chat unreachable at {env('CHAT_URL')}: {e}")

    _print_response(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
