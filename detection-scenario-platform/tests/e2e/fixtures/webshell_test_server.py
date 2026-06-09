"""Local disposable HTTP server that simulates the webshell transport contract."""

from __future__ import annotations

import json
import threading
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from dsp.execution.remote.payload import REMOTE_SCENARIO_COMMAND, decode_scenario_payload
from dsp.runner.remote_scenario_cli import main as remote_scenario_main

from tests.e2e.fixtures.bundle_helpers import remote_bundle_path_for_run


@dataclass
class WebshellTestServer:
    """In-process HTTP server for webshell E2E tests — no external network."""

    host: str = "127.0.0.1"
    port: int = 0
    storage_dir: Path | None = None
    _files: dict[str, bytes] = field(default_factory=dict)
    _command_calls: list[str] = field(default_factory=list)
    _download_calls: list[str] = field(default_factory=list)
    _upload_calls: list[str] = field(default_factory=list)
    _httpd: ThreadingHTTPServer | None = field(default=None, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)

    @property
    def webshell_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("server is not started")
        return f"http://{self.host}:{self._httpd.server_address[1]}/shell.jsp"

    @property
    def command_calls(self) -> list[str]:
        return list(self._command_calls)

    @property
    def download_calls(self) -> list[str]:
        return list(self._download_calls)

    @property
    def upload_calls(self) -> list[str]:
        return list(self._upload_calls)

    def start(self) -> str:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if "remote_path" in params:
                    remote_path = params["remote_path"][0]
                    server._download_calls.append(remote_path)
                    payload = server._files.get(remote_path, b"")
                    status = 200 if payload else 404
                    self._respond(status, payload)
                    return
                if "cmd" in params:
                    server._handle_command(params["cmd"][0])
                    self._respond(200, b"ok")
                    return
                self._respond(200, b"ok")

            def do_POST(self) -> None:
                content_type = self.headers.get("Content-Type", "")
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length) if content_length else b""
                if content_type.startswith("multipart/form-data"):
                    server._handle_upload(body, content_type)
                    self._respond(200, b"uploaded")
                    return
                if content_type.startswith("application/x-www-form-urlencoded"):
                    params = urllib.parse.parse_qs(body.decode("utf-8"))
                    if "cmd" in params:
                        server._handle_command(params["cmd"][0])
                        self._respond(200, b"ok")
                        return
                self._respond(400, b"unsupported post")

            def _respond(self, status: int, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.webshell_url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _handle_command(self, command_line: str) -> None:
        self._command_calls.append(command_line)
        if not command_line.startswith(f"{REMOTE_SCENARIO_COMMAND} "):
            return
        payload_raw = command_line[len(REMOTE_SCENARIO_COMMAND) + 1 :]
        payload = decode_scenario_payload(payload_raw)
        self._execute_remote_scenario(payload)

    def _execute_remote_scenario(self, payload: dict[str, Any]) -> None:
        run_id = str(payload["run_id"])
        storage_root = self.storage_dir or Path("/tmp/dsp-test-server")
        local_dir = storage_root / run_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_bundle = local_dir / "events.jsonl"
        virtual_path = remote_bundle_path_for_run(run_id)

        metadata = dict(payload.get("execution_metadata") or {})
        metadata["remote_bundle_path"] = str(local_bundle)
        payload["execution_metadata"] = metadata

        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        exit_code = remote_scenario_main([encoded])
        if exit_code != 0:
            raise RuntimeError(f"dsp-remote-scenario failed with exit code {exit_code}")

        if local_bundle.is_file():
            self._files[virtual_path] = local_bundle.read_bytes()

    def _handle_upload(self, body: bytes, content_type: str) -> None:
        boundary = _extract_boundary(content_type)
        remote_path = _extract_form_field(body, boundary, "remote_path")
        file_bytes = _extract_file_bytes(body, boundary)
        if remote_path:
            self._upload_calls.append(remote_path)
            self._files[remote_path] = file_bytes


def _extract_boundary(content_type: str) -> str:
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part.split("=", 1)[1]
    raise ValueError("multipart boundary missing")


def _extract_form_field(body: bytes, boundary: str, name: str) -> str:
    marker = f'name="{name}"'.encode()
    if marker not in body:
        return ""
    section = body.split(marker, 1)[1]
    value = section.split(b"\r\n\r\n", 1)[1]
    return value.split(b"\r\n", 1)[0].decode("utf-8")


def _extract_file_bytes(body: bytes, boundary: str) -> bytes:
    marker = b'name="file"'
    if marker not in body:
        return b""
    section = body.split(marker, 1)[1]
    payload = section.split(b"\r\n\r\n", 1)[1]
    return payload.split(f"\r\n--{boundary}".encode(), 1)[0]
