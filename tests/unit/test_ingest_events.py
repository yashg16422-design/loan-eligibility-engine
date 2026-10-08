"""Unit tests: S3 key contract, SQS/S3 event parsing, and the webhook notifier."""

import json
import urllib.error
import uuid

import pytest

from loan_engine.common.notifier import N8nWebhookNotifier, NoopNotifier
from loan_engine.common.s3_keys import job_id_from_event_key, raw_key_for
from loan_engine.ingest.events import parse_sqs_record

JOB = uuid.UUID("1ed10381-ea5b-4a02-8715-c0146261aa06")


# ---------------------------------------------------------------- S3 keys


class TestS3Keys:
    def test_round_trip(self):
        assert job_id_from_event_key(raw_key_for(JOB)) == JOB

    def test_url_encoded_key_is_decoded(self):
        assert job_id_from_event_key(f"raw%2F{JOB}.csv") == JOB

    @pytest.mark.parametrize(
        "key",
        [
            f"other/{JOB}.csv",  # wrong prefix
            f"raw/{JOB}.txt",  # wrong suffix
            f"raw/{str(JOB).upper()}.csv",  # the API only ever issues lowercase
            f"raw/sub/{JOB}.csv",  # nested path
            "raw/not-a-uuid.csv",
            f"raw/{JOB}.csv+extra",
            "raw/my+file.csv",  # '+' decodes to a space
            "",
        ],
    )
    def test_rejects_anything_but_the_exact_pattern(self, key):
        assert job_id_from_event_key(key) is None


# ---------------------------------------------------------------- SQS envelope


def sqs_record(body: dict, receive_count: str = "1") -> dict:
    return {
        "messageId": "m-1",
        "body": json.dumps(body),
        "attributes": {"ApproximateReceiveCount": receive_count},
    }


def s3_record(key: str, event: str = "ObjectCreated:Post", bucket: str = "b") -> dict:
    return {"eventName": event, "s3": {"bucket": {"name": bucket}, "object": {"key": key}}}


class TestParseSqsRecord:
    def test_s3_test_event_yields_nothing(self):
        msg = parse_sqs_record(sqs_record({"Event": "s3:TestEvent", "Bucket": "b"}))
        assert msg.uploads == []
        assert msg.skipped == ["s3:TestEvent"]

    def test_every_record_in_the_body_is_processed(self):
        other = uuid.UUID(int=7)
        body = {"Records": [s3_record(raw_key_for(JOB)), s3_record(raw_key_for(other))]}
        msg = parse_sqs_record(sqs_record(body))
        assert [u.job_id for u in msg.uploads] == [JOB, other]
        assert msg.uploads[0].key == f"raw/{JOB}.csv"
        assert msg.uploads[0].bucket == "b"

    def test_bad_keys_and_non_create_events_are_skipped_not_fatal(self):
        body = {
            "Records": [
                s3_record("raw/evil.csv"),
                s3_record(raw_key_for(JOB), event="ObjectRemoved:Delete"),
                s3_record(raw_key_for(JOB)),
            ]
        }
        msg = parse_sqs_record(sqs_record(body))
        assert [u.job_id for u in msg.uploads] == [JOB]
        assert len(msg.skipped) == 2

    def test_receive_count_is_read(self):
        msg = parse_sqs_record(sqs_record({"Records": []}, receive_count="3"))
        assert msg.receive_count == 3


# ---------------------------------------------------------------- notifier


class TestN8nWebhookNotifier:
    def make(self, outcomes: list):
        """A notifier whose HTTP call follows a script: None = success, Exception = fail."""
        sleeps: list[float] = []
        notifier = N8nWebhookNotifier(
            "http://n8n/webhook", "secret", backoff=(1, 2, 4), sleep=sleeps.append
        )
        calls: list[bytes] = []

        def fake_post(body: bytes) -> None:
            calls.append(body)
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome

        notifier._post = fake_post  # type: ignore[method-assign]
        return notifier, calls, sleeps

    def test_success_first_try(self):
        notifier, calls, sleeps = self.make([None])
        assert notifier.notify_job_completed(JOB) is True
        assert json.loads(calls[0]) == {"job_id": str(JOB)}
        assert sleeps == []

    def test_retries_with_backoff_then_succeeds(self):
        err = urllib.error.URLError("down")
        notifier, calls, sleeps = self.make([err, err, None])
        assert notifier.notify_job_completed(JOB) is True
        assert len(calls) == 3
        assert sleeps == [1, 2]

    def test_gives_up_after_all_retries_without_raising(self):
        err = TimeoutError("slow")
        notifier, calls, sleeps = self.make([err, err, err, err])
        assert notifier.notify_job_completed(JOB) is False  # the sweeper takes over
        assert len(calls) == 4
        assert sleeps == [1, 2, 4]


def test_noop_notifier_reports_not_delivered():
    assert NoopNotifier().notify_job_completed(JOB) is False
