"""WebshellSecurityPolicy validation helper tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsp.execution.webshell import (
    WebshellSecurityPolicy,
    WebshellSecurityViolation,
    validate_command_allowed,
    validate_download_allowed,
    validate_execute_allowed,
    validate_file_size_allowed,
    validate_local_file_allowed,
    validate_remote_path_allowed,
    validate_upload_allowed,
)


def test_security_policy_roundtrip():
    policy = WebshellSecurityPolicy(
        allow_execute=True,
        max_file_size_mb=5.0,
        safe_mode=True,
    )
    restored = WebshellSecurityPolicy.from_dict(policy.to_dict())
    assert restored.allow_execute == policy.allow_execute
    assert restored.max_file_size_mb == policy.max_file_size_mb


def test_validate_execute_denied():
    policy = WebshellSecurityPolicy(allow_execute=False)
    with pytest.raises(WebshellSecurityViolation, match="execute not allowed"):
        validate_execute_allowed(policy)


def test_validate_upload_denied():
    policy = WebshellSecurityPolicy(allow_upload=False)
    with pytest.raises(WebshellSecurityViolation, match="upload not allowed"):
        validate_upload_allowed(policy)


def test_validate_download_denied():
    policy = WebshellSecurityPolicy(allow_download=False)
    with pytest.raises(WebshellSecurityViolation, match="download not allowed"):
        validate_download_allowed(policy)


def test_validate_blocked_command():
    policy = WebshellSecurityPolicy()
    with pytest.raises(WebshellSecurityViolation, match="blocked command"):
        validate_command_allowed(policy, "rm -rf /var")


def test_validate_command_allowed_when_safe_mode_off():
    policy = WebshellSecurityPolicy(safe_mode=False)
    validate_command_allowed(policy, "rm -rf /")


def test_validate_remote_path_allowed():
    policy = WebshellSecurityPolicy()
    validate_remote_path_allowed(policy, "/tmp/dsp_stub/run01/executor.py")


def test_validate_remote_path_denied():
    policy = WebshellSecurityPolicy()
    with pytest.raises(WebshellSecurityViolation, match="remote path not allowed"):
        validate_remote_path_allowed(policy, "/etc/passwd")


def test_validate_file_size_exceeded():
    policy = WebshellSecurityPolicy(max_file_size_mb=1.0)
    with pytest.raises(WebshellSecurityViolation, match="exceeds limit"):
        validate_file_size_allowed(policy, 2 * 1024 * 1024)


def test_validate_local_file(tmp_path: Path):
    local = tmp_path / "stub.py"
    local.write_text("print('ok')")
    policy = WebshellSecurityPolicy()
    validate_local_file_allowed(policy, local)
