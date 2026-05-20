"""PQC algorithm registry — one place to declare what the panel offers.

The values match openquantumsafe/openssl-3 + openquantumsafe/oqs-provider
group names. They're the same identifiers QUJATA uses in its DEFAULT_GROUPS
env var (see QUJATA-Telefonica/run/docker/docker-compose.yml), so the demo
matrix matches the screenshot the project's been showing.

Each entry carries:
  id        — the curl `--curves` / openssl `-groups` value
  family    — 'classical', 'kyber', 'mlkem', 'frodo', 'bike', 'hybrid'
  display   — short label for the dropdown
  nist_l    — NIST PQC security level (1, 3, 5) or None for classical
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class Algorithm:
    id: str
    family: str
    display: str
    nist_l: int | None


ALGORITHMS: list[Algorithm] = [
    # ── Classical baselines (for comparison) ──────────────────────────────
    Algorithm("prime256v1", "classical", "P-256 (prime256v1)", None),
    Algorithm("secp384r1",  "classical", "P-384 (secp384r1)",  None),

    # ── ML-KEM (NIST FIPS 203 — formerly Kyber) ───────────────────────────
    Algorithm("mlkem512",   "mlkem", "ML-KEM-512",  1),
    Algorithm("mlkem768",   "mlkem", "ML-KEM-768",  3),
    Algorithm("mlkem1024",  "mlkem", "ML-KEM-1024", 5),

    # ── ML-KEM hybrids (classical + ML-KEM) ───────────────────────────────
    Algorithm("p256_mlkem512",   "hybrid", "P-256 + ML-KEM-512",   1),
    Algorithm("p384_mlkem768",   "hybrid", "P-384 + ML-KEM-768",   3),
    Algorithm("X25519MLKEM768",  "hybrid", "X25519 + ML-KEM-768",  3),

    # ── Kyber (pre-FIPS naming) ──────────────────────────────────────────
    # Intentionally removed. The current openquantumsafe/openssl-3 +
    # oqs-provider build (verified 2026-05 on the CAM demo host) NO
    # LONGER exposes `kyber*` or `x25519_kyber768` as TLS group names
    # — the names were dropped when NIST published FIPS 203 and the
    # corresponding ML-KEM identifiers became canonical. Use the
    # mlkem512 / mlkem768 / mlkem1024 entries above instead.
    # `openssl list -kem-algorithms` confirms only mlkem* exists.

    # ── FrodoKEM (lattice with conservative assumptions) ──────────────────
    Algorithm("frodo640aes",    "frodo", "Frodo-640 AES",     1),
    Algorithm("frodo640shake",  "frodo", "Frodo-640 SHAKE",   1),
    Algorithm("frodo976aes",    "frodo", "Frodo-976 AES",     3),
    Algorithm("frodo976shake",  "frodo", "Frodo-976 SHAKE",   3),
    Algorithm("frodo1344aes",   "frodo", "Frodo-1344 AES",    5),
    Algorithm("frodo1344shake", "frodo", "Frodo-1344 SHAKE",  5),

    # ── BIKE (code-based) ─────────────────────────────────────────────────
    Algorithm("bikel1", "bike", "BIKE-L1", 1),
    Algorithm("bikel3", "bike", "BIKE-L3", 3),
    Algorithm("bikel5", "bike", "BIKE-L5", 5),
]

BY_ID: dict[str, Algorithm] = {a.id: a for a in ALGORITHMS}

# Convenient defaults for the QA-shaped quick-runs.
DEFAULT_ALGOS_QUICK   = ["mlkem768", "p256_mlkem512", "X25519MLKEM768", "prime256v1"]
DEFAULT_ALGOS_FULL    = [a.id for a in ALGORITHMS]
DEFAULT_ITERATIONS    = 100
DEFAULT_PAYLOAD_BYTES = 1200      # matches the QA battery's 1200-byte size


def as_dicts() -> list[dict]:
    return [asdict(a) for a in ALGORITHMS]
