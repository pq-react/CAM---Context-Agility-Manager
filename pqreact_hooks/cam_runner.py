"""CAM agility loop — sweep, store, ask, re-sweep.

This is the orchestrator that closes the loop CAM was originally designed
for: cryptographic agility driven by *real* measurements + LLM advice
instead of a hardcoded round-robin.

Flow
====
1. Wide sweep      — `mcp_hook.run_legacy_sweep(--algos all)` over every
                     CAM algorithm; results written to PQREACT.performance_test
                     tagged source='cam-context-agility'.
2. Recommend       — `chat_advisor.recommend(use_case, security_floor, …)`
                     asks the LLM to pick ONE algorithm given the context.
                     The LLM reads the rows we just inserted to answer.
3. Re-measure      — narrow sweep on just the recommended algorithm with
                     a higher iteration count (`--iterations 200`) to get
                     a more precise number for the next decision.
4. Verdict         — print the chosen algorithm + rationale + a delta vs
                     the wide-sweep first measurement. (No re-recommendation
                     loop — that's a follow-on once the basics work.)

Usage
=====
    set -a; . ./.env; set +a
    python3 cam_runner.py --use-case "iot-sensor" --security-floor 1
    python3 cam_runner.py --use-case "banking"    --security-floor 5

Designed to be runnable from cron / CI: prints structured JSON on stdout
on the final line so downstream tooling can parse the decision.
"""
from __future__ import annotations

import argparse
import json
import sys

import mcp_hook
import chat_advisor


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--use-case",       default="general")
    p.add_argument("--security-floor", type=int, default=3)
    p.add_argument("--payload-size",   type=int, default=1000)
    p.add_argument("--energy-budget",  default="balanced",
                   choices=["min", "balanced", "max"])
    p.add_argument("--wide-iterations",  type=int, default=50)
    p.add_argument("--narrow-iterations", type=int, default=200)
    p.add_argument("--skip-wide", action="store_true",
                   help="skip step 1 (use existing CAM rows in MCP DB)")
    p.add_argument("--skip-narrow", action="store_true",
                   help="skip step 3 (just print the recommendation)")
    args = p.parse_args(argv)

    # Step 1 — wide sweep
    if args.skip_wide:
        print("[1/4] wide-sweep skipped (--skip-wide)")
        wide_n = 0
    else:
        print(f"[1/4] wide-sweep over all CAM algorithms "
              f"({args.wide_iterations} iters, msg={args.payload_size}B)")
        wide_n = mcp_hook.run_legacy_sweep(
            mcp_hook.ALGORITHMS_DEFAULT,
            args.wide_iterations, args.payload_size,
        )
        print(f"      → {wide_n} rows written to MCP DB\n")

    # Step 2 — ask the LLM
    print(f"[2/4] asking chat for a recommendation "
          f"(use_case='{args.use_case}', sec>={args.security_floor}, "
          f"energy={args.energy_budget})")
    rec = chat_advisor.recommend(args.use_case, args.security_floor,
                                 args.payload_size, args.energy_budget)
    chosen = rec["algorithm"]
    if not chosen:
        print("      ⚠ chat did not return ALG=<name>; aborting narrow sweep")
        print(f"      raw: {rec['rationale'][:300]}")
        print(json.dumps({"chosen": None, "rationale": rec["rationale"][:500]}))
        return 2
    print(f"      → chose {chosen}: {rec['rationale']}\n")

    # Step 3 — narrow sweep
    if args.skip_narrow:
        print("[3/4] narrow-sweep skipped (--skip-narrow)")
        narrow_n = 0
    else:
        print(f"[3/4] re-measuring {chosen} at {args.narrow_iterations} iterations")
        narrow_n = mcp_hook.run_legacy_sweep(
            [chosen], args.narrow_iterations, args.payload_size,
        )
        print(f"      → {narrow_n} rows written to MCP DB\n")

    # Step 4 — verdict
    print(f"[4/4] verdict")
    print(json.dumps({
        "chosen":         chosen,
        "rationale":      rec["rationale"],
        "use_case":       args.use_case,
        "security_floor": args.security_floor,
        "payload_size":   args.payload_size,
        "energy_budget":  args.energy_budget,
        "wide_rows":      wide_n,
        "narrow_rows":    narrow_n,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
