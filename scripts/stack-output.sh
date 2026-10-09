#!/usr/bin/env bash
# Print one CloudFormation output of the stack, e.g. scripts/stack-output.sh N8nInstanceId
set -euo pipefail
STAGE="${STAGE:-dev}"
REGION="${AWS_REGION:-ap-southeast-2}"
aws cloudformation describe-stacks --region "$REGION" --stack-name "loan-engine-${STAGE}" \
  --query "Stacks[0].Outputs[?OutputKey=='${1:?usage: $0 <OutputKey>}'].OutputValue" --output text
