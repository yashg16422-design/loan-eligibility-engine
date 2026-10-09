#!/usr/bin/env bash
# Reach the private RDS from the laptop: SSM forwards localhost:LOCAL_PORT through the
# n8n EC2 (which RDS's security group trusts) to the database on 5432.
#   scripts/tunnel-rds.sh          then, in another terminal:
#   psql "host=localhost port=15432 dbname=app user=n8n_workflows sslmode=require"
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-ap-southeast-2}"
LOCAL_PORT="${LOCAL_PORT:-15432}"
instance_id="$(scripts/stack-output.sh N8nInstanceId)"
db_host="$(scripts/stack-output.sh DbEndpoint)"
echo "Tunnel localhost:${LOCAL_PORT} -> ${db_host}:5432 via ${instance_id} (Ctrl+C to close)"
aws ssm start-session --region "$REGION" --target "$instance_id" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "host=${db_host},portNumber=5432,localPortNumber=${LOCAL_PORT}"
