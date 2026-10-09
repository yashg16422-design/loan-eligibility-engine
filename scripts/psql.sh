#!/usr/bin/env bash
# psql into the private RDS through the SSM tunnel (run scripts/tunnel-rds.sh first).
# The password is read from Secrets Manager into this process's env only, never printed.
#   scripts/psql.sh                      interactive, as n8n_workflows
#   scripts/psql.sh -c "SELECT ..."      one query
#   DB_ROLE=app_ingest scripts/psql.sh   as another app role
set -euo pipefail
ROLE="${DB_ROLE:-n8n_workflows}"
PGPASSWORD="$(aws secretsmanager get-secret-value --region "${AWS_REGION:-ap-southeast-2}" \
  --secret-id "loan-engine/dev/db/${ROLE}" --query SecretString --output text \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')"
export PGPASSWORD
# sslmode=require: TLS on; the hostname is localhost (tunnel), so verify-full can't match.
exec psql "host=localhost port=${LOCAL_PORT:-15432} dbname=app user=${ROLE} sslmode=require" -P pager=off "$@"
