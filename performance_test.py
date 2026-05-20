import os
import requests
import json
import time

# List of algorithms.
#
# Updated 2026-05 to match what the current openquantumsafe/openssl-3
# + oqs-provider build actually exposes as TLS group names. The
# original list used pre-FIPS-203 names (kyber*, hqc*, x25519_kyber768
# etc.) which the new oqs-provider releases dropped — every handshake
# for those names came back with curl exit 59 ("failed setting
# curves list: '<name>'") or TLS handshake_failure (exit 35). The
# canonical names below are confirmed by `openssl list -kem-algorithms`
# on the live demo host.
#
# Coverage: classical baselines + ML-KEM family + ML-KEM hybrids +
# FrodoKEM family + BIKE family. HQC is intentionally absent because
# the current oqs-provider doesn't ship it.
algorithms = [
    # Classical baselines
    "prime256v1",
    "secp384r1",
    # ML-KEM (NIST FIPS 203 — formerly Kyber)
    "mlkem512",
    "mlkem768",
    "mlkem1024",
    # ML-KEM hybrids
    "p256_mlkem512",
    "p384_mlkem768",
    "X25519MLKEM768",
    # FrodoKEM family
    "frodo640aes",
    "frodo640shake",
    "frodo976aes",
    "frodo976shake",
    "frodo1344aes",
    "frodo1344shake",
    # BIKE family
    "bikel1",
    "bikel3",
    "bikel5",
]

# API endpoint — set CAM_QUJATA_URL env var (e.g.
# http://<your-qujata-host>:3010/curl) before running.
url = os.environ.get('CAM_QUJATA_URL', '').rstrip('/')
if not url:
    raise SystemExit("CAM_QUJATA_URL env var required (e.g. http://<host>:3010/curl)")

# Headers
headers = {
    'Content-Type': 'application/json'
}

# Payload data
data = {
    "algorithm": "",
    "iterationsCount": 50,
    "messageSize": 1000  # You can change this value based on the API requirements
}

# Loop through each algorithm and make the request
for algorithm in algorithms:
    data["algorithm"] = algorithm
    response = requests.post(url, headers=headers, data=json.dumps(data))

    # Check the response
    if response.status_code == 201:
        print(f"Successfully processed algorithm: {algorithm}")
        print(response.json())
    else:
        print(f"Failed to process algorithm: {algorithm}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

    # Sleep for 10 seconds
    time.sleep(5)