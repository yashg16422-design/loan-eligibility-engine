#!/usr/bin/env python3
"""Measure the ingest Lambda's code on a large CSV against a local Postgres (never production).

Runs the PRODUCTION process_upload on a synthetic file of about the S3 upload limit (50 MB),
on both ingest paths, and records wall time, peak Python memory (tracemalloc) and the counts.
The file streams from disk the way S3's StreamingBody streams in Lambda.

    docker run -d --rm --name pgbench -e POSTGRES_PASSWORD=localtest -e POSTGRES_DB=app \\
      -p 55433:5432 postgres:17 -c ssl=on \\
      -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem \\
      -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key
    PG_TEST_PORT=55433 .venv/bin/python scripts/bench_ingest.py --rows 520000 \\
        --out docs/evidence/ingest_bench_2026-10-11.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loan_engine.common.secrets import DbCredentials  # noqa: E402
from loan_engine.common.validation import DEFAULT_RULES  # noqa: E402
from loan_engine.ingest import handler as ingest  # noqa: E402
from loan_engine.ingest.events import UploadRef  # noqa: E402
from tests.integration.matching_setup import connect, fresh_schema  # noqa: E402
from tests.synthetic_users import synthetic_users_csv  # noqa: E402


def run(path: Path, streaming: bool) -> dict:
    conn = connect()
    fresh_schema(conn)
    job_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO upload_jobs (job_id, s3_key) VALUES (%s, %s)", (job_id, f"raw/{job_id}.csv")
    )

    class FileS3:
        def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
            return {"Body": path.open("rb")}

    creds = DbCredentials("postgres", os.environ.get("PG_TEST_PASSWORD", "localtest"))
    ingest.cached_db_credentials = lambda arn: creds  # type: ignore[assignment]
    deps = ingest.Dependencies(
        "localhost",
        "x",
        int(os.environ["PG_TEST_PORT"]),
        DEFAULT_RULES,
        ingest.NoopNotifier(),
        FileS3(),
        streaming,
    )
    tracemalloc.start()
    started = time.perf_counter()
    outcome = ingest.process_upload(UploadRef("b", f"raw/{job_id}.csv", job_id), 1, deps)
    seconds = time.perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    row = conn.execute(
        "SELECT status, total_rows, inserted, updated, unchanged, rejected FROM upload_jobs "
        "WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    conn.close()
    keys = ("status", "total_rows", "inserted", "updated", "unchanged", "rejected")
    return {
        "path": "streaming" if streaming else "in-memory",
        "outcome": outcome.value,
        "seconds": round(seconds, 1),
        "peak_python_mb": round(peak / 1e6, 1),
        **dict(zip(keys, row, strict=True)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=520_000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "users.csv"
        path.write_bytes(synthetic_users_csv(rows=args.rows, seed=11))
        size_mb = round(path.stat().st_size / 1e6, 1)
        results = [run(path, streaming) for streaming in (True, False)]
    report = {
        "file_mb": size_mb,
        "rows": args.rows,
        "machine": f"{platform.machine()} {platform.system()} {platform.release()}, "
        f"Python {platform.python_version()}, Postgres 17 in Docker (local)",
        "note": "Local measurement, not Lambda: Lambda's CPU share scales with its memory size.",
        "results": results,
    }
    print(json.dumps(report, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
