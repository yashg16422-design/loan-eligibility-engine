#!/usr/bin/env bash
# Print a Cognito ID token for a merchant account, for scripts that call signed-in routes
# (e.g. scripts/upload-sample.sh). The password is read from the terminal, never echoed, and
# goes only to Cognito.   Usage: export ID_TOKEN="$(scripts/id-token.sh you@example.com)"
set -euo pipefail
EMAIL="${1:?usage: $0 <email>}"
CLIENT_ID="$(scripts/stack-output.sh UserPoolClientId)"
read -r -s -p "Password for ${EMAIL}: " PASSWORD </dev/tty; echo >&2
aws cognito-idp initiate-auth --region "${AWS_REGION:-ap-southeast-2}" --client-id "$CLIENT_ID" \
  --auth-flow USER_PASSWORD_AUTH --auth-parameters "USERNAME=${EMAIL},PASSWORD=${PASSWORD}" \
  --query AuthenticationResult.IdToken --output text
