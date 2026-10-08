"""How ingest announces "job COMPLETED" to the next stage (a pluggable seam).

Today the next stage is n8n Workflow B via a private-network webhook. The ingest
Lambda only depends on the `Notifier` protocol, so swapping in EventBridge or
anything else later means a new class here, not a change to the ingest logic.

Notification is best-effort by design: if it fails, Workflow B's 10-minute
sweeper still picks up the job (PLAN.md §5.3 step 6, §11.1).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_HEADER = "X-Webhook-Secret"  # must match the n8n Header Auth credential
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


class Notifier(Protocol):
    """Anything that can announce a completed job. Returns True if delivered."""

    def notify_job_completed(self, job_id: uuid.UUID) -> bool: ...


class NoopNotifier:
    """Used until n8n exists (or when disabled by config): logs and does nothing."""

    def notify_job_completed(self, job_id: uuid.UUID) -> bool:
        logger.info("no notifier configured; job %s will be picked up by the sweeper", job_id)
        return False


class N8nWebhookNotifier:
    """POST {"job_id": ...} to the n8n webhook with a shared-secret header and retries."""

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
        timeout: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,  # injectable so tests don't wait
    ) -> None:
        self._url = url
        self._secret = secret
        self._backoff = backoff
        self._timeout = timeout
        self._sleep = sleep

    def notify_job_completed(self, job_id: uuid.UUID) -> bool:
        body = json.dumps({"job_id": str(job_id)}).encode()
        attempts = len(self._backoff) + 1  # first try + one retry per backoff step
        for attempt in range(1, attempts + 1):
            try:
                self._post(body)
                logger.info("webhook delivered for job %s (attempt %d)", job_id, attempt)
                return True
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                logger.warning("webhook attempt %d/%d failed: %s", attempt, attempts, err)
                if attempt < attempts:
                    self._sleep(self._backoff[attempt - 1])
        logger.error("webhook gave up for job %s; the sweeper will recover it", job_id)
        return False

    def _post(self, body: bytes) -> None:
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", WEBHOOK_SECRET_HEADER: self._secret},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            if response.status >= 300:
                raise urllib.error.URLError(f"HTTP {response.status}")
