"""CAM → PQ-REACT LLM chat advisor.

Asks the chat UI on .159:8081 to recommend an algorithm given a context
(use-case description, security floor, payload size, energy budget).
The chat agent reads from the same MCP MariaDB the CAM hook writes to,
so its recommendation is grounded in real CAM measurements.

Two modes:

  recommend
      "Given my context, what algorithm should I run next?"
      Returns: {"algorithm": "<name>", "rationale": "<why>"}

  rank
      "Rank the algorithms I just ran by <metric> for <context>."
      Returns: ordered list of {algorithm, score, why}

This is the Phase 2 piece — wired AFTER mcp_hook.py has populated the
DB with fresh CAM measurements. Together they close the agility loop:
sweep → store → ask LLM → re-sweep just the recommended algorithm.

Connection:
  CHAT_URL = http://10.160.101.159:8081  (default)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULTS = {
    "CHAT_URL":         "http://10.160.101.159:8081",
    "CAM_SOURCE_TAG":   "cam-context-agility",
}


def env(key: str) -> str:
    return os.environ.get(key, DEFAULTS.get(key, ""))


def chat(query: str, timeout: int = 120) -> dict:
    """POST one query to the chat UI's /chat endpoint. Returns the parsed
    JSON, which always has at least 'response'; on patched servers it also
    has 'tool_calls' (the list of MCP tools the agent invoked, see patch
    12 in the KatanaSliceManagerv2 mcp-server/patches/ tree)."""
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        env("CHAT_URL") + "/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def recommend(use_case: str, security_floor: int = 3,
              payload_size: int = 1000, energy_budget: str = "balanced") -> dict:
    """Return {"algorithm": ..., "rationale": ..., "raw": <chat response>}."""
    q = (
        f"Given the use case '{use_case}', NIST security level >= {security_floor}, "
        f"payload size {payload_size} bytes, and an energy budget of '{energy_budget}', "
        f"query the performance_test table (filter source='{env('CAM_SOURCE_TAG')}' "
        f"so we only consider CAM measurements) and recommend ONE algorithm. "
        f"Reply in this exact format on the first line: ALG=<algorithm_name>. "
        f"Then a one-sentence rationale on the next line."
    )
    resp = chat(q)
    text = resp.get("response", "")
    m = re.search(r"ALG=([A-Za-z0-9_+]+)", text)
    alg = m.group(1) if m else None
    # Rationale = everything after the ALG= line (or the whole response)
    rationale = text.split("\n", 1)[1].strip() if "\n" in text else text.strip()
    return {"algorithm": alg, "rationale": rationale, "raw": resp}


def rank(metric: str = "duration", security_floor: int = 3,
         payload_size: int = 1000) -> dict:
    """Ask the LLM to rank CAM-tagged algorithms by a metric."""
    q = (
        f"From the performance_test table, filter source='{env('CAM_SOURCE_TAG')}' "
        f"AND security_level>={security_floor} AND message_size={payload_size}. "
        f"Rank the algorithms by {metric} (ascending=better for duration/energy/power, "
        f"descending=better for throughput). Return a markdown table with columns: "
        f"rank, algorithm, {metric}, security_level."
    )
    return chat(q)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("recommend", help="get a single algorithm recommendation")
    rec.add_argument("--use-case",       default="general")
    rec.add_argument("--security-floor", type=int, default=3)
    rec.add_argument("--payload-size",   type=int, default=1000)
    rec.add_argument("--energy-budget",  default="balanced",
                     choices=["min", "balanced", "max"])

    rk = sub.add_parser("rank", help="rank CAM-tagged algorithms by a metric")
    rk.add_argument("--metric",          default="duration",
                    choices=["duration", "energy_joules", "power_watts", "cpu_util_pct"])
    rk.add_argument("--security-floor",  type=int, default=3)
    rk.add_argument("--payload-size",    type=int, default=1000)

    args = p.parse_args(argv)

    try:
        if args.cmd == "recommend":
            r = recommend(args.use_case, args.security_floor,
                          args.payload_size, args.energy_budget)
            print(json.dumps({"algorithm": r["algorithm"],
                              "rationale": r["rationale"]}, indent=2))
        else:
            r = rank(args.metric, args.security_floor, args.payload_size)
            print(r.get("response", "(no response)"))
    except urllib.error.URLError as e:
        sys.exit(f"chat unreachable at {env('CHAT_URL')}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
