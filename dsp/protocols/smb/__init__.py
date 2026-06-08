"""SMB protocol library — Phase 13 SMB Login Failure."""

from dsp.protocols.smb.attempts import (
    ATTEMPTS_PER_HOST_DEFAULT,
    DEFAULT_PASSWORD_LABELS,
    DEFAULT_USERNAMES,
    MAX_ATTEMPTS_PER_HOST,
    MAX_HOSTS_DEFAULT,
    SMB_ALT_PORT,
    SMB_PORT_DEFAULT,
    PlannedSmbAttempt,
    plan_smb_attempts,
)
from dsp.protocols.smb.client import SmbClient
from dsp.protocols.smb.smb_events import (
    SMB_AUTH_ATTEMPT,
    SMB_AUTH_FAILED,
    SMB_CONNECTION_FAILED,
    SMB_CONNECTION_OPENED,
    SMB_LOGIN_FAILURE_TRAFFIC_EVENTS,
    SMB_SCENARIO_COMPLETED,
    SMB_SCENARIO_STARTED,
    append_outcome_events,
    build_smb_auth_attempt_event,
    build_smb_auth_failed_event,
    build_smb_connection_failed_event,
    build_smb_connection_opened_event,
    build_smb_scenario_completed_event,
    build_smb_scenario_started_event,
)
from dsp.protocols.smb.smb_reporting import (
    build_smb_login_failure_report_section,
    smb_login_failure_report_profile,
)
from dsp.protocols.smb.smb_validation import (
    SMB_LOGIN_FAILURE_METRIC_NAMES,
    smb_login_failure_validation_profile,
)

__all__ = [
    "ATTEMPTS_PER_HOST_DEFAULT",
    "DEFAULT_PASSWORD_LABELS",
    "DEFAULT_USERNAMES",
    "MAX_ATTEMPTS_PER_HOST",
    "MAX_HOSTS_DEFAULT",
    "PlannedSmbAttempt",
    "SMB_ALT_PORT",
    "SMB_AUTH_ATTEMPT",
    "SMB_AUTH_FAILED",
    "SMB_CONNECTION_FAILED",
    "SMB_CONNECTION_OPENED",
    "SMB_LOGIN_FAILURE_METRIC_NAMES",
    "SMB_LOGIN_FAILURE_TRAFFIC_EVENTS",
    "SMB_PORT_DEFAULT",
    "SMB_SCENARIO_COMPLETED",
    "SMB_SCENARIO_STARTED",
    "SmbClient",
    "append_outcome_events",
    "build_smb_auth_attempt_event",
    "build_smb_auth_failed_event",
    "build_smb_connection_failed_event",
    "build_smb_connection_opened_event",
    "build_smb_login_failure_report_section",
    "build_smb_scenario_completed_event",
    "build_smb_scenario_started_event",
    "plan_smb_attempts",
    "smb_login_failure_report_profile",
    "smb_login_failure_validation_profile",
]
