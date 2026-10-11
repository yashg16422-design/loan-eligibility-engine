#!/bin/bash
# Bring up n8n on the EC2 host. Runs as root:
#   - on first boot, from the EC2 user-data, and
#   - again on every `scripts/n8n-sync.sh apply` (via SSM Run Command).
# Idempotent: re-running converges to the same state, so config updates never need
# a new instance. Contains no secrets: they are read at runtime via the instance role.
#
# Expects /etc/n8n/boot.env (written by user-data) with:
#   BUCKET REGION DB_HOST META_SECRET_ARN ENC_KEY_SECRET_ARN
set -euo pipefail
source /etc/n8n/boot.env

COMPOSE_VERSION="v5.5.1"
# Published checksum for docker-compose-linux-aarch64 v5.5.1: never run an unverified binary.
COMPOSE_SHA256="732e3a84c1a0f67256ce80bc2598a24546b10ca05f9faa97efceb1171ece2ef7"
COMPOSE_BIN="/usr/libexec/docker/cli-plugins/docker-compose"
APP_DIR="/opt/n8n"

log() { echo "[n8n-boot] $(date -u +%FT%TZ) $*"; }

# --- 1. Docker + Compose plugin ------------------------------------------------
if ! command -v docker >/dev/null; then
  log "installing docker"
  dnf install -y docker jq
fi
systemctl enable --now docker

if ! "$COMPOSE_BIN" version 2>/dev/null | grep -q "${COMPOSE_VERSION#v}"; then
  log "installing docker compose ${COMPOSE_VERSION}"
  tmp="$(mktemp)"
  curl -fsSL -o "$tmp" \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64"
  echo "${COMPOSE_SHA256}  ${tmp}" | sha256sum -c -
  install -D -m 0755 "$tmp" "$COMPOSE_BIN"
  rm -f "$tmp"
fi

# --- 1b. Swap: n8n + headless Chromium share 2 GB RAM; a heavy page should slow down,
# not get n8n OOM-killed. Created once, kept across reboots.
if ! swapon --show | grep -q /swapfile; then
  log "creating 2 GB swap file"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- 2. Config from S3 + the RDS CA bundle -------------------------------------
mkdir -p "$APP_DIR/certs"
cd "$APP_DIR"
aws s3 cp --region "$REGION" "s3://${BUCKET}/config/docker-compose.yml" docker-compose.yml
# Renderer build context (Dockerfile + server code), versioned in the repo's renderer/.
aws s3 sync --region "$REGION" --delete --exact-timestamps "s3://${BUCKET}/config/renderer/" renderer/
# Official AWS trust store for RDS in this region: n8n verifies the DB certificate
# instead of blindly accepting it (DB_POSTGRESDB_SSL_REJECT_UNAUTHORIZED stays true).
curl -fsSL -o certs/rds-ca.pem \
  "https://truststore.pki.rds.amazonaws.com/${REGION}/${REGION}-bundle.pem"
chmod 0644 certs/rds-ca.pem

# --- 3. Secrets -> .env (root-only, never logged) -------------------------------
secret() { aws secretsmanager get-secret-value --region "$REGION" --secret-id "$1" --query SecretString --output text; }
meta_json="$(secret "$META_SECRET_ARN")"
enc_key="$(secret "$ENC_KEY_SECRET_ARN" | jq -r .key)"

# IMDSv2 (token required) -> this instance's private IP for n8n's webhook URLs.
token="$(curl -fsS -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 300')"
private_ip="$(curl -fsS -H "X-aws-ec2-metadata-token: ${token}" \
  http://169.254.169.254/latest/meta-data/local-ipv4)"

umask 077
{
  echo "DB_TYPE=postgresdb"
  echo "DB_POSTGRESDB_HOST=${DB_HOST}"
  echo "DB_POSTGRESDB_PORT=5432"
  echo "DB_POSTGRESDB_DATABASE=n8n"
  echo "DB_POSTGRESDB_USER=$(jq -r .username <<<"$meta_json")"
  echo "DB_POSTGRESDB_PASSWORD=$(jq -r .password <<<"$meta_json")"
  echo "DB_POSTGRESDB_SSL_ENABLED=true"
  # n8n's own connection pool (defaults: 2 connections, 20 s connect timeout, idle ones evicted
  # after 30 s). During a 10,000-user run RDS is busy writing matches, and reconnecting took
  # longer than that: n8n lost its database mid-run once (found live). Keep more connections
  # open and give a reconnect time.
  echo "DB_POSTGRESDB_POOL_SIZE=6"
  echo "DB_POSTGRESDB_CONNECTION_TIMEOUT=60000"
  echo "DB_POSTGRESDB_IDLE_CONNECTION_TIMEOUT=600000"
  echo "DB_CONNECTION_ACQUISITION_TIMEOUT_MS=120000"
  echo "DB_POSTGRESDB_SSL_CA_FILE=/certs/rds-ca.pem"
  # Trust the RDS CA process-wide too, so the workflows' Postgres credential can use
  # "SSL: Require" WITH certificate verification (no "ignore SSL issues").
  echo "NODE_EXTRA_CA_CERTS=/certs/rds-ca.pem"
  echo "N8N_ENCRYPTION_KEY=${enc_key}"
  # The editor is only ever reached through the SSM tunnel at http://localhost:5678.
  echo "N8N_PROTOCOL=http"
  echo "N8N_SECURE_COOKIE=false"
  echo "WEBHOOK_URL=http://${private_ip}:5678/"
  echo "GENERIC_TIMEZONE=Asia/Kolkata"
  echo "TZ=Asia/Kolkata"
  echo "N8N_DIAGNOSTICS_ENABLED=false"
  echo "N8N_VERSION_NOTIFICATIONS_ENABLED=false"
  # Below Workflow B's 15-minute lock reclaim, so a live run is never reclaimed (PLAN.md §11.2).
  echo "EXECUTIONS_TIMEOUT=600"
  echo "EXECUTIONS_TIMEOUT_MAX=900"
  echo "EXECUTIONS_DATA_PRUNE=true"
  echo "EXECUTIONS_DATA_MAX_AGE=336"
  # Lets the "AWS (Assume Role)" credential start from the EC2 instance role: no access keys.
  echo "N8N_AWS_SYSTEM_CREDENTIALS_ACCESS_ENABLED=true"
  echo "AWS_REGION=${REGION}"
} > .env.new
mv .env.new .env
umask 022

# --- 4. Start / update -------------------------------------------------------------
docker compose pull --quiet --ignore-buildable
profiles=()
if [[ "${ENABLE_RENDERER:-false}" == "true" ]]; then
  # Plain `docker build` (not `compose build`): compose v5 wants buildx >= 0.17, and
  # AL2023 ships 0.12. Same tag as `image:` in docker-compose.yml, so compose uses it.
  docker build --quiet -t loan-renderer:1.63.0 renderer/ >/dev/null
  profiles=(--profile renderer)
else
  # Disabled: make sure a previously enabled renderer is stopped and removed.
  docker compose --profile renderer rm --stop --force renderer >/dev/null 2>&1 || true
fi
docker compose "${profiles[@]}" up -d --remove-orphans
log "n8n started; waiting for /healthz"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:5678/healthz >/dev/null 2>&1; then
    log "n8n is healthy (webhook base http://${private_ip}:5678/)"
    exit 0
  fi
  sleep 5
done
log "n8n did not become healthy in 5 minutes"
docker compose logs --tail 50 n8n
exit 1
