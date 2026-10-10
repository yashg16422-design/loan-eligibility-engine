#!/usr/bin/env bash
# Build both front ends into the api Lambda package (run before `serverless deploy`):
#   web/       (landing, served at /)      -> loan_engine/api/site/
#   dashboard/ (app, served at /app/)      -> loan_engine/api/static/   (vite outDir)
set -euo pipefail
cd "$(dirname "$0")/.."
(cd web && npm ci --no-audit --no-fund && VITE_APP_URL=/app/ npm run build)
rm -rf loan_engine/api/site && cp -R web/dist loan_engine/api/site
(cd dashboard && npm ci --no-audit --no-fund && npm run build)
echo "built: $(du -sh loan_engine/api/site | cut -f1) landing, $(du -sh loan_engine/api/static | cut -f1) app"
