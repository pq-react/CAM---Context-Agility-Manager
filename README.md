# Context Agility Manager
The Context Agility Manager (CAM) in the PQ-REACT framework facilitates cryptographic agility by automatically selecting and configuring post-quantum and hybrid encryption algorithms tailored to the operational context. Leveraging principles from the PQC research community, CAM dynamically adjusts cryptographic configurations by analyzing real-time data from infrastructure assets and their associated security parameters. This context-aware mechanism takes into account various factors such as compliance with regulatory standards, the availability of cryptographic algorithms, security requirements, and resource constraints. Furthermore, CAM mitigates common issues related to cryptographic misconfigurations by automating the selection of optimal defaults, such as algorithm types, key sizes, and security levels. This ensures robust, adaptable security configurations are applied efficiently, as demonstrated in use cases like the Qujata testbed, where CAM enhances client-server communication security using post-quantum cryptographic methods.

The implementation of this repo currently enables users to create dashboards for monitoring the communication between a server and a client machine within the Qujata testbed. While CAM does not yet dynamically select the most suitable cryptographic configurations, it can loop through the available post-quantum, classical, and hybrid encryption algorithms provided by the Qujata framework. This allows users to visualize the performance and security impact of different algorithms in real-time. The integrated dashboards help users track system metrics, evaluate the effectiveness of each cryptographic approach, and better understand the operational environment, paving the way for future enhancements toward fully automated cryptographic agility.


## Recommended Setup

During the implementation of this repository, InfluxDB and Grafana instances were installed on two different virtual machines, while Telegraf and Qujata Server/Client instances were installed and configured on two separate physical machines (NUC).

## Requirements

This guide assumes the following prerequisites:

- Ubuntu 22.04 OS
- Git
- Nano (or any text editor of your choice)
- Node.js (which includes npm) for Client machine
- Docker Engine for Server machine

### Important Note

In the `metrics_dashboard.json` file, it is assumed that the username is `node-1`, the network interface is `enp86s0`, and the bucket name is `NUC_metrics`. If different, change these values to match your setup.

## Steps for Implementation

### Step 1: Install and Configure InfluxDB

**Update the System:**

```bash
sudo apt update && sudo apt upgrade
```

**Install InfluxDB:**

```bash
wget -q https://repos.influxdata.com/influxdb.key
echo '23a1c8836f0afc5ed24e0486339d7cc8f6790b83886c4c96995b88a061c5bb5d influxdb.key' | sha256sum -c && cat influxdb.key | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/influxdb.gpg > /dev/null
curl -LO https://download.influxdata.com/influxdb/releases/influxdb2_2.7.6-1_amd64.deb
sudo dpkg -i influxdb2_2.7.6-1_amd64.deb
sudo apt update
sudo apt install influxdb2
sudo systemctl start influxdb
```

**Initial Configuration of InfluxDB:**

```bash
influx setup
```
You need to set up your initial username, password, organization name, the primary bucket name to store data, and retention period (in hours). Your details are stored in /home/username/.influxdbv2/configs

### Step 2: Install and Configure Telegraf on Both Server and Client Machines

**Create a Directory:**

```bash
mkdir metrics_retrieval && cd metrics_retrieval/
```

**Install Telegraf:**

```bash
sudo apt-get update
sudo apt install telegraf
```

**Edit the Telegraf Configuration:**

```bash
sudo nano /etc/telegraf/telegraf.conf
```

Modify the following sections:

**Data Collection Interval:**

```ini
[agent]
interval = "1s"
```

**InfluxDB Configuration:**
```ini
[[outputs.influxdb_v2]]
urls = ["http://11.11.11.11:8086"]
token = "$INFLUX_TOKEN"
organization = "pqreact"
bucket = "metrics_1"
```

**Enable Intel PowerStat Plugin:**

```ini
[[inputs.intel_powerstat]]
cpu_metrics = ["cpu_frequency", "cpu_temperature", "cpu_busy_frequency"]
```

**Restart Telegraf:**

```bash
sudo systemctl restart telegraf
sudo systemctl status telegraf
```

### Step 3: Install Grafana Using Docker

**Create a Docker Volume:**

```bash
sudo docker volume create grafana-storage
```
**Run Grafana Docker Container:**

```bash
sudo docker run -d -p 3000:3000 --name=grafana --volume grafana-storage:/var/lib/grafana grafana/grafana-enterprise
```

### Step 4: Configure Grafana Data Source

Launch the Grafana UI at http://<serverIP>:3000.
  1. Log in with the default credentials (admin / admin), and set a new default password.
  2 . Add your first data source in the "Data Sources" menu.
  3. Select "InfluxDB" as the data source and choose Flux as the query language.

Enter the following values:

**HTTP:**
```plaintext
URL: 'http://<Influxdb_IP_Address>:8087'
```

**Auth:**

```plaintext
User: <Your_UserName>
Password: <Your_Influxdb_Password>
```

**InlfuxDB Details:**

```plaintext
Organization: pqreact
Token: <Influxdb_Token>
Bucket: metrics
Min time interval: 300ms
Max series: 10000
```

Click the "Save and Test" button to verify the setup.

### Step 5: Set up Grafana Dashboards

  1. In the "Dashboards" menu, click "Import" to upload and import the metrics_dashboard.json file.
  2. If the panels display "No data," edit the panels to ensure the correct bucket, username, and network interface are selected.

```plaintext
from(bucket: "metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "net")
  |> filter(fn: (r) => r["_field"] == "bytes_recv" or r["_field"] == "bytes_sent")
  |> filter(fn: (r) => r["host"] == "node-1")
  |> filter(fn: (r) => r["interface"] == "enp86s0")
  |> aggregate.rate(every: 1s, unit: 1s)
  |> yield(name: "mean")
```

Set the refresh rate to "300ms" to enable fast panel data updates.

### Step 6: Qujata Testbed Installation and Configuration

Download the Qujata GitHub Repository on Both Machines:

```bash
git clone https://github.com/att/qujata.git
```

**Set Up Qujata Server:**

Navigate to the qujata/run/docker directory and start the server:

```bash
sudo docker compose up
```

**Set Up Qujata Client:**

Navigate to the "qujata/curl" directory and install the required dependencies:

```bash
npm install
npm run start
```

**Modify and Run Python Test Script:**

```bash
nano performance_test.py
```

**Update the server IP in the script:**

```python
url = 'http://11.11.11.11:3010/curl'
```
Run the script to test the post-quantum and hybrid algorithms:

```bash
python3 performance_test.py
```

The client terminal will log the algorithm used and message size, and the server terminal will log the requests.



