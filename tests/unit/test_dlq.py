"""The dead-letter consumer marks crashed uploads FAILED (loan_engine/ingest/dlq.py)."""

import uuid

from loan_engine.ingest import dlq
from tests.unit.test_ingest_events import s3_record, sqs_record

JOB = uuid.UUID("0b7f9c1e-2a51-4f6e-9d3c-3f5d8a1c2b4e")


def test_every_upload_in_the_dead_letter_batch_is_marked_failed():
    event = {
        "Records": [
            sqs_record({"Records": [s3_record(f"raw/{JOB}.csv")]}, receive_count="3"),
            sqs_record({"Event": "s3:TestEvent"}),  # not an upload: ignored
            sqs_record({"Records": [s3_record("other/file.csv")]}),  # never reaches the DB
        ]
    }
    assert dlq.failed_jobs(event) == [JOB]
    failed = []
    dlq.mark_failed(dlq.failed_jobs(event), lambda job, reason: failed.append((job, reason)))
    assert failed == [(JOB, dlq.REASON)]
    assert "upload the file again" in dlq.REASON  # the UI shows what to do next


def test_an_empty_batch_touches_nothing(monkeypatch, lambda_context):
    monkeypatch.setattr(dlq, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert dlq.handler({"Records": []}, lambda_context) == {"failed": []}
