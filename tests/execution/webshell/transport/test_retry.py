"""RetryPolicy tests."""

from __future__ import annotations

from dsp.execution.webshell.transport import RetryPolicy


def test_retry_policy_roundtrip():
    policy = RetryPolicy(
        max_retries=3,
        backoff_seconds=2.5,
        retry_on_timeout=False,
        retry_on_http_5xx=True,
        retry_on_http_429=False,
    )
    restored = RetryPolicy.from_dict(policy.to_dict())
    assert restored == policy


def test_should_retry_on_timeout():
    policy = RetryPolicy(max_retries=2, retry_on_timeout=True)
    assert policy.should_retry(attempt=0, timed_out=True) is True
    assert policy.should_retry(attempt=2, timed_out=True) is False


def test_should_retry_on_5xx():
    policy = RetryPolicy(max_retries=2, retry_on_http_5xx=True)
    assert policy.should_retry(attempt=0, status_code=503) is True
    assert policy.should_retry(attempt=0, status_code=404) is False


def test_should_retry_on_429():
    policy = RetryPolicy(max_retries=1, retry_on_http_429=True)
    assert policy.should_retry(attempt=0, status_code=429) is True
    assert policy.should_retry(attempt=1, status_code=429) is False
