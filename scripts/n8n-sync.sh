#!/usr/bin/env bash
# Ship n8n host config to S3 and (optionally) re-run the boot script on the instance.
#   scripts/n8n-sync.sh push    upload docker-compose.yml + boot.sh to s3://<bucket>/config/
#   scripts/n8n-sync.sh apply   push, then re-run boot.sh on the EC2 via SSM Run Command
# No SSH and no instance replacement: config changes converge in place.
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-ap-southeast-2}"
BUCKET="$(scripts/stack-output.sh DataBucketName)"

push() {
  aws s3 cp --region "$REGION" docker-compose.yml "s3://${BUCKET}/config/docker-compose.yml"
  aws s3 cp --region "$REGION" deploy/n8n/boot.sh "s3://${BUCKET}/config/boot.sh"
  aws s3 sync --region "$REGION" --delete renderer/ "s3://${BUCKET}/config/renderer/" \
    --exclude "__pycache__/*"
}

apply() {
  push
  local instance_id command_id
  instance_id="$(scripts/stack-output.sh N8nInstanceId)"
  command_id="$(aws ssm send-command --region "$REGION" --instance-ids "$instance_id" \
    --document-name AWS-RunShellScript --comment "n8n-sync apply" \
    --parameters "commands=[\"aws s3 cp --region ${REGION} s3://${BUCKET}/config/boot.sh /root/n8n-boot.sh\",\"bash /root/n8n-boot.sh\"]" \
    --query Command.CommandId --output text)"
  echo "SSM command ${command_id} sent to ${instance_id}; waiting..."
  aws ssm wait command-executed --region "$REGION" --command-id "$command_id" \
    --instance-id "$instance_id" || true
  aws ssm get-command-invocation --region "$REGION" --command-id "$command_id" \
    --instance-id "$instance_id" --query '[Status, StandardOutputContent]' --output text | tail -5
}

case "${1:-}" in
  push) push ;;
  apply) apply ;;
  *) echo "usage: $0 push|apply" >&2; exit 2 ;;
esac
