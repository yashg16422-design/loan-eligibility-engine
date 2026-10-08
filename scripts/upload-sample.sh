#!/usr/bin/env bash
# Upload a CSV exactly like the browser UI does, then poll the job until it finishes.
#   1. POST /uploads            -> job_id + presigned POST (url + signed fields)
#   2. multipart POST to S3     -> the file goes straight to S3, never through the API
#   3. GET /uploads/{job_id}    -> poll the status every 3 s
# Usage: scripts/upload-sample.sh <api-base-url> [csv-path]
set -euo pipefail

API="${1:?usage: $0 <api-base-url> [csv-path]}"
API="${API%/}"
CSV="${2:-data/users.csv}"
[[ -f "$CSV" ]] || { echo "no such file: $CSV" >&2; exit 1; }

ticket="$(curl -sS --fail-with-body -X POST "$API/uploads" \
  -H 'content-type: application/json' -d "{\"filename\": \"$(basename "$CSV")\"}")"
job_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' <<<"$ticket")"
url="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["upload"]["url"])' <<<"$ticket")"
echo "job $job_id -> uploading $CSV to $url"

# Signed fields first, the file last (S3 ignores fields after the file).
form_args=()
while IFS= read -r field; do form_args+=(-F "$field"); done < <(
  python3 -c 'import json,sys
for k, v in json.load(sys.stdin)["upload"]["fields"].items(): print(f"{k}={v}")' <<<"$ticket")
curl -sS --fail-with-body -o /dev/null -w "S3 answered HTTP %{http_code} in %{time_total}s\n" \
  "${form_args[@]}" -F "file=@$CSV" "$url"

for _ in $(seq 1 60); do
  sleep 3
  line="$(curl -sS --fail-with-body "$API/uploads/$job_id" | python3 -c 'import json,sys
j = json.load(sys.stdin)["job"]
print(j["status"], "| rows", j["total_rows"], "| inserted", j["inserted"], "| updated", j["updated"],
      "| unchanged", j["unchanged"], "| rejected", j["rejected"], "| attempts", j["attempts"])')"
  echo "$(date +%H:%M:%S) $line"
  case "$line" in COMPLETED*|FAILED*|EXPIRED*) exit 0 ;; esac
done
echo "still not finished after 3 minutes" >&2; exit 1
