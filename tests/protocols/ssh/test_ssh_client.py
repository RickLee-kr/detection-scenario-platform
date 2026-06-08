"""SSH attempt generation and client unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dsp.protocols.base import SshProtocolError
from dsp.protocols.ssh.attempts import PlannedSshAttempt, plan_ssh_attempts
from dsp.protocols.ssh.client import SshClient, attempt_auth_failure


def test_ssh_client_mock_attempt_auth_failed():
    client = SshClient(mode="mock")
    plan = plan_ssh_attempts(["10.10.10.20"], max_total=1)[0]
    result = client.attempt(plan)
    assert result.outcome == "auth_failed"
    assert result.dry_run is True
    assert result.username == plan.username


def test_ssh_client_mock_custom_outcome():
    client = SshClient(mode="mock")
    plan = plan_ssh_attempts(["10.10.10.20"], max_total=1)[0]
    result = client.attempt(plan, mock_outcome="connection_refused")
    assert result.outcome == "connection_refused"


def test_ssh_client_live_rejects_mock_outcome():
    client = SshClient(mode="live")
    plan = plan_ssh_attempts(["10.10.10.20"], max_total=1)[0]
    with pytest.raises(SshProtocolError, match="mock_outcome"):
        client.attempt(plan, mock_outcome="auth_failed")


def test_attempt_auth_failure_classifies_permission_denied():
    completed = MagicMock()
    completed.returncode = 255
    completed.stderr = "Permission denied (publickey)."

    with patch("subprocess.run", return_value=completed):
        result = attempt_auth_failure("10.10.10.20", username="root")

    assert result.outcome == "auth_failed"
    assert result.dry_run is False
    assert result.username == "root"


def test_attempt_auth_failure_classifies_connection_refused():
    completed = MagicMock()
    completed.returncode = 255
    completed.stderr = "ssh: connect to host 10.10.10.20 port 22: Connection refused"

    with patch("subprocess.run", return_value=completed):
        result = attempt_auth_failure("10.10.10.20", username="admin")

    assert result.outcome == "connection_refused"


def test_ssh_client_make_attempt():
    client = SshClient(mode="mock")
    planned = PlannedSshAttempt(
        host="10.10.10.20",
        port=22,
        username="ubuntu",
        password_label="Test123",
    )
    attempt = client.make_attempt(planned)
    assert attempt.host == "10.10.10.20"
    assert attempt.username == "ubuntu"
    assert attempt.password_label == "Test123"
