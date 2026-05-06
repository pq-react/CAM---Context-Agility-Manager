"""CAM closed-loop self-configuring crypto orchestrator (Phase 5).

End-to-end demonstration of the self-configuring loop the recommendation
engine was designed for:

    [1/5] CAM sweep         — refresh performance_test rows tagged
                              source='cam-context-agility'
    [2/5] Recommend         — ask the chat for recommend_migration_priority
                              (or query_by_security_level when CAM_TARGET=db)
                              and parse the top algorithm out of the response
    [3/5] Apply             — call apply_pqc_configuration via the chat,
                              recording the decision in pqc_configurations
                              and (when target_type='qujata-experiment')
                              kicking off a real iperf measurement on the
                              testbed
    [4/5] Verify            — poll the latest QUJATA test_suite for the
                              suite_id the apply step kicked off
    [5/5] Verdict           — print a single JSON line for downstream
                              tooling (cron, CI, dashboards)

Connection (set in .env, gitignored):
    CHAT_URL    http://<chat-host>:8081
    MCP_DB_*    optional — only used to read the latest CAM-tagged
                algorithm name as a fallback when the chat doesn't
                return ALG=<name>

Examples:
    # Dry-run (default — records the decision but doesn't touch QUJATA).
    python3 closed_loop.py --sector telco

    # Closed loop with verification — KATANA_ALLOW_CONFIGURE=true must
    # be set on the MCP server, otherwise the apply step refuses.
    python3 closed_loop.py --sector telco --apply qujata-experiment

    # Skip the wide CAM sweep (steps [1] and [4] become cheap).
    python3 closed_loop.py --sector energy --skip-sweep --apply audit
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULTS = {
    "CHAT_URL":         "",
    "CAM_SOURCE_TAG":   "cam-context-agility",
    "MCP_DB_HOST":      "",
    "MCP_DB_PORT":      "3307",
    "MCP_DB_USER":      "root",
    "MCP_DB_PASSWORD":  "",
    "MCP_DB_NAME":      "PQREACT",
}

VALID_SECTORS = ("energy", "telco", "health", "financial",
                 "cross-sector", "public")
VALID_TARGETS = ("audit", "qujata-experiment", "slice")


def env(key: str) -> str:
    return os.environ.get(key, DEFAULTS.get(key, ""))


def chat(query: str, timeout: int = 240) -> dict:
    if not env("CHAT_URL"):
        sys.exit("CHAT_URL is required in .env (e.g. http://<host>:8081)")
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        env("CHAT_URL").rstrip("/") + "/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── Step [1] — CAM sweep ──────────────────────────────────────────────────

def cam_sweep(payload_size: int, iterations: int) -> int:
    """Refresh the CAM-tagged rows in performance_test by re-running the
    full algorithm list through the legacy curl endpoint. Returns row count."""
    try:
        import mcp_hook  # local import — only needed when sweeping
    except ImportError:
        print("    ⚠ mcp_hook.py not importable; skipping sweep", file=sys.stderr)
        return 0
    return mcp_hook.run_legacy_sweep(
        mcp_hook.ALGORITHMS_DEFAULT, iterations, payload_size,
    )


# ── Step [2] — recommend ──────────────────────────────────────────────────

# Patterns to extract the chosen algorithm from a chat response. We look
# for the markers the recommend_migration_priority tool produces ("**ML-DSA-65**"
# or "top-perf at L3: `mldsa65`") plus a generic ALG= fallback.
_ALG_PATTERNS = [
    re.compile(r"top-perf at L3:\s*`([A-Za-z0-9_+\-]+)`", re.IGNORECASE),
    re.compile(r"`([A-Za-z0-9_+]{4,})`", re.IGNORECASE),
    re.compile(r"\*\*([A-Za-z0-9_+\-]{4,})\*\*"),
    re.compile(r"\bALG\s*=\s*([A-Za-z0-9_+\-]+)", re.IGNORECASE),
]


def parse_algorithm_from_response(text: str) -> str | None:
    """Pull a plausible algorithm token out of the chat response. We
    prefer matches near the start of the response (the recommendation
    summary) over matches buried in a per-row table."""
    head = text[:1500]
    for pat in _ALG_PATTERNS:
        for m in pat.finditer(head):
            cand = (m.group(1) or "").strip()
            if not cand:
                continue
            cl = cand.lower()
            # Skip tool/category tokens that match the pattern but aren't algos.
            if cl in {"db", "qujata", "katana", "regulations", "inventory",
                      "registry", "all", "true", "false", "none", "null",
                      "energy", "telco", "health", "financial", "public",
                      "cross-sector", "high", "low", "medium", "yes", "no",
                      "n/a", "ml-kem", "ml-dsa", "slh-dsa", "aes-256",
                      "sha-256"}:
                continue
            # Looks like an algorithm name — has digits or a hyphen+digits
            if re.search(r"\d", cand) or "+" in cand:
                return cand
    return None


def recommend(sector: str, top_n: int = 5) -> dict:
    """Step [2] — ask the chat for a sector migration plan. Parse the top
    algorithm + rationale out of the response."""
    q = (
        f"Recommend a migration priority for the {sector} sector with "
        f"the top {top_n} ranked assets. Use recommend_migration_priority"
        f"(sector='{sector}', top_n={top_n}). Forward the markdown table "
        f"verbatim including the score breakdown. End your response by "
        f"naming the SINGLE recommended algorithm in backticks "
        f"(e.g. `mldsa65`)."
    )
    resp = chat(q)
    text = resp.get("response", "") or ""
    alg = parse_algorithm_from_response(text)
    return {"algorithm": alg, "response": text, "tool_calls": resp.get("tool_calls", [])}


# ── Step [3] — apply ──────────────────────────────────────────────────────

def apply_configuration(sector: str, algorithm: str, target_type: str,
                        rationale: str, target_ref: str | None = None) -> dict:
    """Step [3] — ask the chat to call apply_pqc_configuration. Returns the
    parsed response containing the audit row id (and qujata_suite_id when
    target_type='qujata-experiment')."""
    extras = ""
    if target_ref:
        extras = f", target_ref='{target_ref}'"
    q = (
        f"Call apply_pqc_configuration with sector='{sector}', "
        f"algorithm='{algorithm}', target_type='{target_type}'"
        f"{extras}, rationale={json.dumps(rationale[:200])}, "
        f"requested_by='closed_loop'. Forward the response verbatim — "
        f"in particular the audit row id and any qujata_suite_id."
    )
    resp = chat(q)
    text = resp.get("response", "") or ""
    audit_match = re.search(r"audit\s*#(\d+)", text)
    suite_match = re.search(r"qujata_suite_id[^0-9]*(\d+)", text) or \
                  re.search(r"test\s*suite\s*#?(\d+)", text, re.IGNORECASE)
    return {
        "audit_id":   int(audit_match.group(1)) if audit_match else None,
        "suite_id":   int(suite_match.group(1)) if suite_match else None,
        "response":   text,
        "tool_calls": resp.get("tool_calls", []),
    }


# ── Step [4] — verify ─────────────────────────────────────────────────────

def verify(suite_id: int) -> dict:
    """Step [4] — pull the QUJATA results for the experiment we just kicked
    off. Polls a few times since QUJATA experiments take ~duration_s + 5s."""
    if suite_id is None:
        return {"suite_id": None, "response": "(no suite_id to verify)", "tool_calls": []}
    last = None
    for attempt in range(6):  # ~6 × 10 s = 60 s of patience
        q = (f"Forward the markdown table for query_test_suite("
             f"test_suite_id={suite_id}) verbatim. If the run hasn't "
             f"completed yet, just say so.")
        resp = chat(q)
        last = resp
        text = resp.get("response", "") or ""
        # Heuristic: if the response includes any "mbps=" / "kem=" / "ms" string
        # we have measurements; otherwise wait a beat and retry.
        if re.search(r"\bmbps\s*=", text) or "kem=" in text \
           or "RUNNING" not in text.upper():
            return {"suite_id": suite_id, "response": text,
                    "tool_calls": resp.get("tool_calls", [])}
        time.sleep(10)
    return {"suite_id": suite_id, "response": (last or {}).get("response", ""),
            "tool_calls": (last or {}).get("tool_calls", [])}


# ── Driver ────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sector", required=True, choices=VALID_SECTORS)
    p.add_argument("--apply", default="audit", choices=VALID_TARGETS,
                   help="target_type for apply_pqc_configuration "
                        "(default: 'audit' = dry-run)")
    p.add_argument("--top-n", type=int, default=5,
                   help="how many ranked assets to ask recommend for")
    p.add_argument("--skip-sweep", action="store_true",
                   help="skip [1] CAM sweep (use existing rows)")
    p.add_argument("--sweep-iterations", type=int, default=50)
    p.add_argument("--sweep-payload-size", type=int, default=1000)
    p.add_argument("--target-ref", default=None,
                   help="for --apply slice: slice id; for qujata-experiment: "
                        "QUJATA slice_id (mgmt/research/iot/video, default mgmt)")
    args = p.parse_args(argv)

    n_steps = 5
    print(f"=== CAM closed-loop  ·  sector={args.sector}  ·  apply={args.apply} ===")

    # [1] sweep
    wide_n = 0
    if args.skip_sweep:
        print(f"\n[1/{n_steps}] CAM sweep skipped (--skip-sweep)")
    else:
        print(f"\n[1/{n_steps}] CAM sweep ({args.sweep_iterations} iters, "
              f"msg={args.sweep_payload_size}B)")
        try:
            wide_n = cam_sweep(args.sweep_payload_size, args.sweep_iterations)
            print(f"      → {wide_n} rows refreshed in performance_test")
        except Exception as e:
            print(f"      ⚠ sweep failed ({type(e).__name__}: {e}); continuing")

    # [2] recommend
    print(f"\n[2/{n_steps}] asking chat for recommend_migration_priority"
          f"(sector='{args.sector}', top_n={args.top_n})")
    try:
        rec = recommend(args.sector, top_n=args.top_n)
    except urllib.error.URLError as e:
        sys.exit(f"chat unreachable at {env('CHAT_URL')}: {e}")
    if not rec["algorithm"]:
        print("      ⚠ could not parse a single algorithm from the response")
        print(f"      first 300 chars: {rec['response'][:300]}")
        print(json.dumps({"chosen": None, "stage": "recommend"}))
        return 2
    rationale = rec["response"][:300].replace("\n", " ").strip()
    print(f"      → recommended: **{rec['algorithm']}**")
    print(f"      → rationale: {rationale[:160]}…")

    # [3] apply
    print(f"\n[3/{n_steps}] apply_pqc_configuration"
          f"(target_type='{args.apply}')")
    try:
        appl = apply_configuration(args.sector, rec["algorithm"], args.apply,
                                   rationale=rationale,
                                   target_ref=args.target_ref)
    except urllib.error.URLError as e:
        sys.exit(f"chat unreachable at {env('CHAT_URL')}: {e}")
    if appl["audit_id"] is None:
        print("      ⚠ apply did not return an audit row id")
        print(f"      first 300 chars: {appl['response'][:300]}")
    else:
        print(f"      → audit row #{appl['audit_id']}")
    if appl["suite_id"]:
        print(f"      → qujata test_suite #{appl['suite_id']} kicked off")

    # [4] verify
    if args.apply == "qujata-experiment" and appl["suite_id"]:
        print(f"\n[4/{n_steps}] verify via query_test_suite(test_suite_id={appl['suite_id']})")
        try:
            ver = verify(appl["suite_id"])
        except urllib.error.URLError as e:
            sys.exit(f"chat unreachable at {env('CHAT_URL')}: {e}")
        print(ver["response"][:1500])
    else:
        print(f"\n[4/{n_steps}] verify skipped (target_type={args.apply!r})")
        ver = {"suite_id": None, "response": "skipped"}

    # [5] verdict
    print(f"\n[5/{n_steps}] verdict")
    print(json.dumps({
        "sector":      args.sector,
        "chosen":      rec["algorithm"],
        "rationale":   rationale[:300],
        "apply":       args.apply,
        "audit_id":    appl["audit_id"],
        "suite_id":    appl["suite_id"],
        "wide_rows":   wide_n,
        "verified":    ver["suite_id"] is not None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
