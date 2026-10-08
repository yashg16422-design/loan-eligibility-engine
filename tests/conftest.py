"""Shared pytest fixtures."""

from dataclasses import dataclass

import pytest


@dataclass
class FakeLambdaContext:
    """The attributes Powertools' inject_lambda_context reads."""

    function_name: str = "test"
    memory_limit_in_mb: int = 128
    invoked_function_arn: str = "arn:aws:lambda:ap-southeast-2:000000000000:function:test"
    aws_request_id: str = "req-1"


@pytest.fixture
def lambda_context() -> FakeLambdaContext:
    return FakeLambdaContext()
