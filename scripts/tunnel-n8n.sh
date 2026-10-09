#!/usr/bin/env bash
# Open the n8n editor at http://localhost:5678 through an SSM port-forwarding session.
# Needs: AWS CLI v2 + the Session Manager plugin. No SSH, no open inbound ports.
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-ap-southeast-2}"
LOCAL_PORT="${LOCAL_PORT:-5678}"
instance_id="$(scripts/stack-output.sh N8nInstanceId)"
echo "Tunnel to ${instance_id}: open http://localhost:${LOCAL_PORT} (Ctrl+C to close)"
aws ssm start-session --region "$REGION" --target "$instance_id" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=5678,localPortNumber=${LOCAL_PORT}"
