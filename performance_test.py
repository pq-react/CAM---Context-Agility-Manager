import os
import requests
import json
import time

# List of algorithms
algorithms = [
    "bikel1",
    "bikel3",
    "bikel5",
    "frodo1344aes",
    "frodo1344shake",
    "frodo640aes",
    "frodo640shake",
    "frodo976aes",
    "frodo976shake",
    "hqc128",
    "hqc192",
    "hqc256",
    "kyber1024",
    "kyber512",
    "kyber768",
    "p256_kyber512",
    "p384_kyber768",
    "prime256v1",
    "secp384r1",
    "x25519_kyber768"
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