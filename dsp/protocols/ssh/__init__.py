"""SSH protocol library — Phase 5 SSH Login Failure."""

from dsp.protocols.ssh.attempts import (
    DEFAULT_PASSWORDS,
    DEFAULT_USERNAMES,
    MAX_ATTEMPTS_PER_HOST_DEFAULT,
    MAX_ATTEMPTS_TOTAL_DEFAULT,
    MAX_HOSTS_DEFAULT,
    SSH_PORT_DEFAULT,
    PlannedSshAttempt,
    plan_ssh_attempts,
)
from dsp.protocols.ssh.client import SshClient, attempt_auth_failure
from dsp.protocols.ssh.events import (
    SSH_AUTH_ATTEMPT,
    SSH_AUTH_FAILED,
    SSH_CONNECTION_ERROR,
    SSH_FAILURE_COMPLETED,
    SSH_FAILURE_STARTED,
    SSH_FAILURE_TRAFFIC_EVENTS,
    append_outcome_event,
    build_ssh_auth_attempt_event,
    build_ssh_auth_failed_event,
    build_ssh_connection_error_event,
    build_ssh_failure_completed_event,
    build_ssh_failure_started_event,
)
from dsp.protocols.ssh.reporting import build_ssh_failure_report_section, ssh_failure_report_profile
from dsp.protocols.ssh.validation import SSH_FAILURE_METRIC_NAMES, ssh_failure_validation_profile

__all__ = [
    "DEFAULT_PASSWORDS",
    "DEFAULT_USERNAMES",
    "MAX_ATTEMPTS_PER_HOST_DEFAULT",
    "MAX_ATTEMPTS_TOTAL_DEFAULT",
    "MAX_HOSTS_DEFAULT",
    "SSH_AUTH_ATTEMPT",
    "SSH_AUTH_FAILED",
    "SSH_CONNECTION_ERROR",
    "SSH_FAILURE_COMPLETED",
    "SSH_FAILURE_METRIC_NAMES",
    "SSH_FAILURE_STARTED",
    "SSH_FAILURE_TRAFFIC_EVENTS",
    "SSH_PORT_DEFAULT",
    "PlannedSshAttempt",
    "SshClient",
    "append_outcome_event",
    "attempt_auth_failure",
    "build_ssh_auth_attempt_event",
    "build_ssh_auth_failed_event",
    "build_ssh_connection_error_event",
    "build_ssh_failure_completed_event",
    "build_ssh_failure_report_section",
    "build_ssh_failure_started_event",
    "plan_ssh_attempts",
    "ssh_failure_report_profile",
    "ssh_failure_validation_profile",
]
