import os
import requests
import time
import subprocess
import re
import glob

# InfluxDB configuration — set CAM_INFLUXDB_URL / CAM_INFLUXDB_TOKEN env
# vars before running (e.g. CAM_INFLUXDB_URL=http://<host>:8086/api/v2/write).
#
# Module-level reads only — do NOT raise at import time, otherwise unit
# tests (which import this module to mock its internals) can't even
# load. Runtime callers (send_to_influxdb / __main__) validate via
# _require_config() below.
influxdb_url = os.environ.get('CAM_INFLUXDB_URL', '')
org = os.environ.get('CAM_INFLUXDB_ORG', 'pqreact')
bucket = os.environ.get('CAM_INFLUXDB_BUCKET', 'metrics')
token = os.environ.get('CAM_INFLUXDB_TOKEN', '')


def _require_config():
    """Validate env config at call time (not import time)."""
    missing = [
        name for name, val in (
            ('CAM_INFLUXDB_URL', influxdb_url),
            ('CAM_INFLUXDB_TOKEN', token),
        ) if not val
    ]
    if missing:
        raise SystemExit(f"required env var(s) not set: {', '.join(missing)}")

# Function to get current temperatures using the sensors command
def get_temperatures():
    try:
        result = subprocess.run(['sensors'], capture_output=True, text=True, check=True)
        output = result.stdout.strip()

        # Extract temperatures using regular expressions
        temps = {}
        patterns = {
            "Core_0": r"Core 0:\s+\+([\d\.]+)°C",
            "Core_4": r"Core 4:\s+\+([\d\.]+)°C",
            "Core_8": r"Core 8:\s+\+([\d\.]+)°C",
            "Core_12": r"Core 12:\s+\+([\d\.]+)°C",
            "Core_16": r"Core 16:\s+\+([\d\.]+)°C",
            "Core_17": r"Core 17:\s+\+([\d\.]+)°C",
            "Core_18": r"Core 18:\s+\+([\d\.]+)°C",
            "Core_19": r"Core 19:\s+\+([\d\.]+)°C",
            "Core_20": r"Core 20:\s+\+([\d\.]+)°C",
            "Core_21": r"Core 21:\s+\+([\d\.]+)°C",
            "Core_22": r"Core 22:\s+\+([\d\.]+)°C",
            "Core_23": r"Core 23:\s+\+([\d\.]+)°C",
            "ACPI": r"temp1:\s+\+([\d\.]+)°C\s+\(crit =",
            "PCI": r"Composite:\s+\+([\d\.]+)°C"
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                temps[key] = float(match.group(1))

        return temps
    except subprocess.CalledProcessError as e:
        print(f"Error while getting temperatures: {e}")
        return {}

# Function to get power consumption
def get_power_consumption(interval=1):
    try:
        # Read initial energy values
        energy_files = glob.glob('/sys/class/powercap/*/energy_uj')
        T0 = [int(open(file).read().strip()) for file in energy_files]
        time.sleep(interval)
        # Read final energy values
        T1 = [int(open(file).read().strip()) for file in energy_files]
        power_values = [((T1[i] - T0[i]) / interval) / 1e6 for i in range(len(T0))]  # Convert to Watts

        power_dict = {
            "System": power_values[0] if len(power_values) > 0 else 0,
            "Core": power_values[1] if len(power_values) > 1 else 0,
            "Package_0_0": power_values[2] if len(power_values) > 2 else 0
        }
        return power_dict
    except Exception as e:
        print(f"Error while getting power consumption: {e}")
        return {}

# Function to send data to InfluxDB
def send_to_influxdb(temps, power):
    data = ""
    for key, value in temps.items():
        data += f"temperatures,key={key} value={value}\n"

    for key, power_value in power.items():
        data += f"power_consumption,key={key} value={power_value}\n"

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "text/plain; charset=utf-8"
    }
    params = {
        "org": org,
        "bucket": bucket,
        "precision": "s"
    }
    response = requests.post(influxdb_url, headers=headers, params=params, data=data)
    if response.status_code != 204:
        print(f"Failed to write data to InfluxDB: {response.status_code} - {response.text}")

# Main loop to retrieve and send metrics every second
if __name__ == "__main__":
    _require_config()
    while True:
        temperatures = get_temperatures()
        power = get_power_consumption(interval=1)

        if temperatures or power:
            for key, value in temperatures.items():
                print(f"{key}: {value}°C")
            for key, power_value in power.items():
                print(f"Power consumption ({key}): {power_value} W")
            send_to_influxdb(temperatures, power)
        else:
            print("Failed to retrieve temperatures or power consumption.")

        time.sleep(0.5)