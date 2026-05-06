#!/bin/bash
# Deploy the CAM repo + the pqreact_hooks/ scripts to the QUJATA orchestrator
# VM (the same host that runs the MCP server stack) so testing can begin.
#
# What this script does:
#
#   1. rsync the entire CAM clone to $REMOTE_DIR on the target VM.
#   2. Create a Python venv there with pymysql installed.
#   3. Read MCP_DB_PASSWORD from the live `pqreact-mcp-mariadb` container env
#      so we never have to write the credential into the repo.
#   4. Drop an .env file with all the testbed defaults (MCP DB host, chat URL,
#      QUJATA endpoints) plus the password from step 3.
#   5. Run a smoke test in --synthetic mode (no QUJATA round-trip needed)
#      and a chat advisor query against the LLM.
#
# Idempotent. Re-running just refreshes the code + .env and reruns the smoke.
#
# Required env (no defaults — supply at the call site):
#   QUJATA_VM   target VM (the host running the MCP server + qujata-api)
#   SSHPASS     SSH password
#   SSHUSER     SSH username
#   MCP_HOST    MCP MariaDB host (defaults to QUJATA_VM if unset)
#   QUJATA_API  full QUJATA API base URL (e.g. http://<host>:3020/qujata-api)
#   CHAT_URL    LLM chat UI base URL  (e.g. http://<host>:8081)
#   QUJATA_LEGACY  optional — legacy /curl endpoint URL
#
# Optional env:
#   REMOTE_DIR  default /home/${SSHUSER:-cam-deploy}/cam
#
# Usage:
#   QUJATA_VM=<host> SSHPASS=<password> SSHUSER=<user> \
#   MCP_HOST=<host> QUJATA_API=http://<host>:3020/qujata-api \
#   CHAT_URL=http://<host>:8081 \
#     bash pqreact_hooks/deploy-to-qujata-vm.sh             # deploy + smoke
#   ... bash pqreact_hooks/deploy-to-qujata-vm.sh --no-smoke  # deploy only

set -uo pipefail

QUJATA_VM="${QUJATA_VM:?QUJATA_VM required (target VM hostname/IP)}"
SSHPASS_VAL="${SSHPASS:?SSHPASS required (SSH password)}"
SSHUSER="${SSHUSER:?SSHUSER required (SSH username)}"
MCP_HOST="${MCP_HOST:-$QUJATA_VM}"
QUJATA_API="${QUJATA_API:?QUJATA_API required (e.g. http://<host>:3020/qujata-api)}"
CHAT_URL="${CHAT_URL:?CHAT_URL required (e.g. http://<host>:8081)}"
QUJATA_LEGACY="${QUJATA_LEGACY:-}"
REMOTE_DIR="${REMOTE_DIR:-/home/$SSHUSER/cam}"

DO_SMOKE=1
case "${1:-}" in
    --no-smoke) DO_SMOKE=0 ;;
    -h|--help)  sed -n '2,29p' "$0"; exit 0 ;;
esac

GREEN='\033[32m'; RED='\033[31m'; YEL='\033[33m'; BLU='\033[36m'; NC='\033[0m'

# Resolve repo root (parent of pqreact_hooks/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ssh_q() {
    sshpass -p "$SSHPASS_VAL" ssh -o StrictHostKeyChecking=no \
        -o PreferredAuthentications=password -o PubkeyAuthentication=no \
        -o NumberOfPasswordPrompts=1 \
        "$SSHUSER@$QUJATA_VM" "$1"
}

printf "${BLU}── deploy CAM to %s ──${NC}\n" "$QUJATA_VM"
printf "  source: %s\n" "$REPO_ROOT"
printf "  target: %s:%s\n" "$QUJATA_VM" "$REMOTE_DIR"
printf "  smoke:  %s\n\n" "$DO_SMOKE"

# ── 1. tar | ssh-tar the repo (sshpass + rsync doesn't work on macOS — ───
#       rsync's child ssh tries to call ssh-askpass). tar through stdin
#       is portable, fast enough for a 12MB repo, and respects --exclude.
printf "${BLU}[1/5] sync repo via tar over ssh${NC}\n"
ssh_q "mkdir -p '$REMOTE_DIR' && rm -rf '$REMOTE_DIR'/* '$REMOTE_DIR'/.[!.]* 2>/dev/null || true"
( cd "$REPO_ROOT" && tar --exclude=.git --exclude=.venv --exclude='__pycache__' \
                       --exclude='*.pyc' --exclude='.env' -cf - . 2>/dev/null ) \
  | sshpass -p "$SSHPASS_VAL" ssh -o StrictHostKeyChecking=no \
        -o PreferredAuthentications=password -o PubkeyAuthentication=no \
        -o NumberOfPasswordPrompts=1 \
        "$SSHUSER@$QUJATA_VM" "tar -xf - -C '$REMOTE_DIR' 2>/dev/null"
printf "  ${GREEN}✓${NC} synced\n"

# ── 2. install python3-venv if missing, then create venv + pymysql ──────
printf "\n${BLU}[2/5] python venv + pymysql${NC}\n"
ssh_q "echo '$SSHPASS_VAL' | sudo -S apt-get install -y python3.12-venv >/dev/null 2>&1 || true; \
       cd '$REMOTE_DIR/pqreact_hooks' && \
       [ -d .venv ] || python3 -m venv .venv && \
       .venv/bin/pip install -q --upgrade pip 2>/dev/null && \
       .venv/bin/pip install -q -r requirements.txt && \
       .venv/bin/python -c 'import pymysql; print(\"  ✓ pymysql\", pymysql.__version__)'"

# ── 3. read MCP_DB_PASSWORD from the live container ─────────────────────
printf "\n${BLU}[3/5] resolve MCP_DB_PASSWORD from pqreact-mcp-mariadb container${NC}\n"
MCP_DB_PASSWORD="$(ssh_q "docker inspect pqreact-mcp-mariadb --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | awk -F= '/MARIADB_ROOT_PASSWORD/ {print \$2}'")"
if [ -z "$MCP_DB_PASSWORD" ]; then
    printf "  ${RED}✗${NC} could not read MARIADB_ROOT_PASSWORD from pqreact-mcp-mariadb\n"
    printf "    is the container running? \`docker ps | grep pqreact-mcp-mariadb\`\n"
    exit 1
fi
printf "  ${GREEN}✓${NC} resolved (length=%d, first 4 chars: %s***)\n" "${#MCP_DB_PASSWORD}" "${MCP_DB_PASSWORD:0:4}"

# ── 4. drop .env on the remote ──────────────────────────────────────────
printf "\n${BLU}[4/5] write %s/.env${NC}\n" "$REMOTE_DIR/pqreact_hooks"
ssh_q "cat > '$REMOTE_DIR/pqreact_hooks/.env' <<EOF
# Auto-generated by deploy-to-qujata-vm.sh — do not commit
MCP_DB_HOST=$MCP_HOST
MCP_DB_PORT=3307
MCP_DB_USER=root
MCP_DB_PASSWORD=$MCP_DB_PASSWORD
MCP_DB_NAME=PQREACT
QUJATA_BASE=$QUJATA_API
QUJATA_LEGACY=$QUJATA_LEGACY
CHAT_URL=$CHAT_URL
CAM_SOURCE_TAG=cam-context-agility

# qujata-mysql is reachable from the .247 host on 127.0.0.1:3306
# (the qujata-mysql container publishes its 3306 to the host).
QUJATA_MYSQL_HOST=127.0.0.1
QUJATA_MYSQL_PORT=3306
QUJATA_MYSQL_USER=root
QUJATA_MYSQL_PASSWORD=qujata
QUJATA_MYSQL_DB=qujata
EOF
chmod 600 '$REMOTE_DIR/pqreact_hooks/.env'"
printf "  ${GREEN}✓${NC} .env written (mode 600 — gitignored, password not echoed)\n"

# ── 5. smoke test ───────────────────────────────────────────────────────
if [ "$DO_SMOKE" = "0" ]; then
    printf "\n${YEL}[5/5] smoke skipped (--no-smoke)${NC}\n"
    printf "\n${GREEN}── done ──${NC}\n"
    printf "  Run from %s:\n" "$QUJATA_VM"
    printf "    ssh %s@%s\n" "$SSHUSER" "$QUJATA_VM"
    printf "    cd %s/pqreact_hooks && set -a; . ./.env; set +a\n" "$REMOTE_DIR"
    printf "    .venv/bin/python mcp_hook.py --synthetic --algos kyber768 mlkem1024\n"
    exit 0
fi

printf "\n${BLU}[5/5] smoke test (synthetic insert + chat advisor)${NC}\n"
ssh_q "cd '$REMOTE_DIR/pqreact_hooks' && \
       set -a && . ./.env && set +a && \
       echo '─── synthetic insert ───' && \
       .venv/bin/python mcp_hook.py --synthetic --algos kyber768 mlkem1024 classical && \
       echo && \
       echo '─── chat advisor ───' && \
       .venv/bin/python chat_advisor.py recommend --use-case 'iot-sensor' --security-floor 1 --energy-budget min"

printf "\n${GREEN}── done ──${NC}\n"
printf "  CAM deployed to %s on %s\n" "$REMOTE_DIR" "$QUJATA_VM"
printf "  Run a wider sweep with:\n"
printf "    ssh %s@%s 'cd %s/pqreact_hooks && set -a; . ./.env; set +a; .venv/bin/python mcp_hook.py --synthetic'\n" \
       "$SSHUSER" "$QUJATA_VM" "$REMOTE_DIR"
printf "  Clean up CAM rows with:\n"
printf "    docker exec pqreact-mcp-mariadb mysql -uroot -p\$MCP_DB_PASSWORD -D PQREACT \\\n"
printf "      -e \"DELETE FROM performance_test WHERE source='cam-context-agility'\"\n"
