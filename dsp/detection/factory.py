"""Detection provider factory — pluggable vendor adapters."""

from __future__ import annotations

from dsp.detection.base import DetectionAdapter
from dsp.detection.providers.stellar.client_base import StellarClient

SUPPORTED_PROVIDERS = frozenset({"stellar"})
SUPPORTED_STELLAR_CLIENT_MODES = frozenset({"manual", "mock", "http"})
DEFAULT_STELLAR_CLIENT_MODE = "manual"


class UnsupportedDetectionProviderError(ValueError):
    """Raised when an unknown detection provider is requested."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"unsupported detection provider: {provider_id}")


class UnsupportedStellarClientModeError(ValueError):
    """Raised when an unknown Stellar client mode is requested."""

    def __init__(self, client_mode: str) -> None:
        self.client_mode = client_mode
        super().__init__(f"unsupported stellar client mode: {client_mode}")


def create_stellar_client(
    client_mode: str = DEFAULT_STELLAR_CLIENT_MODE,
    *,
    simulate_detection: bool = True,
    simulate_empty: bool = False,
) -> StellarClient:
    """Instantiate a Stellar client implementation."""
    if client_mode not in SUPPORTED_STELLAR_CLIENT_MODES:
        raise UnsupportedStellarClientModeError(client_mode)

    if client_mode == "manual":
        raise UnsupportedStellarClientModeError(client_mode)

    if client_mode == "mock":
        from dsp.detection.providers.stellar.mock_client import MockStellarClient

        return MockStellarClient(
            simulate_detection=simulate_detection,
            simulate_empty=simulate_empty,
        )

    if client_mode == "http":
        from dsp.detection.providers.stellar.http_client import StellarHttpClient

        return StellarHttpClient()

    raise UnsupportedStellarClientModeError(client_mode)


def create_detection_adapter(
    provider_id: str = "stellar",
    *,
    stellar_client: str = DEFAULT_STELLAR_CLIENT_MODE,
    simulate_detection: bool = True,
    simulate_empty: bool = False,
) -> DetectionAdapter:
    """Instantiate a detection adapter for the given provider."""
    if provider_id not in SUPPORTED_PROVIDERS:
        raise UnsupportedDetectionProviderError(provider_id)

    if provider_id == "stellar":
        if stellar_client == "manual":
            from dsp.detection.providers.manual.manual_adapter import ManualDetectionAdapter

            return ManualDetectionAdapter()

        from dsp.detection.providers.stellar.stellar_adapter import StellarAdapter

        client = create_stellar_client(
            stellar_client,
            simulate_detection=simulate_detection,
            simulate_empty=simulate_empty,
        )
        evidence_limits = None
        if stellar_client == "http":
            from dsp.detection.providers.stellar.http_client import StellarHttpClient

            if isinstance(client, StellarHttpClient) and client.config is not None:
                evidence_limits = client.config.evidence_limits

        return StellarAdapter(
            client=client,
            client_mode=stellar_client,
            evidence_limits=evidence_limits,
        )

    raise UnsupportedDetectionProviderError(provider_id)
