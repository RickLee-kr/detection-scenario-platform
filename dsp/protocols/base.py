"""Protocol base types and errors."""

from __future__ import annotations


class ProtocolError(Exception):
    """Base protocol library error."""


class DnsProtocolError(ProtocolError):
    """DNS-specific protocol error."""


class TimeoutError(ProtocolError):
    """Query or connection timed out."""


class ConnectionRefusedError(ProtocolError):
    """Connection refused by remote host."""


class DnsResolutionError(ProtocolError):
    """DNS resolution failed."""


class HttpProtocolError(ProtocolError):
    """HTTP-specific protocol error."""


class SshProtocolError(ProtocolError):
    """SSH-specific protocol error."""


class SmbProtocolError(ProtocolError):
    """SMB-specific protocol error."""


class ReconProtocolError(ProtocolError):
    """Reconnaissance-specific protocol error."""


class LdapProtocolError(ProtocolError):
    """LDAP-specific protocol error."""


class KerberosProtocolError(ProtocolError):
    """Kerberos-specific protocol error."""
