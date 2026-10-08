"""Stream an S3 object as text lines without loading the whole file into memory."""

from __future__ import annotations

import codecs
from collections.abc import Iterator
from typing import Any, Protocol


class SupportsGetObject(Protocol):
    """The one boto3 S3 client method we use; lets tests pass a tiny fake."""

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...  # noqa: N803 (boto3 names)


def iter_text_lines(s3_client: SupportsGetObject, bucket: str, key: str) -> Iterator[str]:
    """Yield decoded lines of an S3 object, keeping line endings.

    - utf-8-sig strips a leading BOM (common in Excel exports).
    - Line endings are kept so the csv module can handle CRLF and newlines inside
      quoted fields correctly (the equivalent of open(..., newline='')).
    - Invalid UTF-8 raises UnicodeDecodeError, which the caller treats as a bad file.
    """
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"]
    reader = codecs.getreader("utf-8-sig")(body)
    try:
        yield from reader
    finally:
        body.close()
