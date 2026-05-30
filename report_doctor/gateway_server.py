from __future__ import annotations

import argparse
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import load_runtime_settings
from .dataworks_client import DataWorksClientError, DataWorksReadOnlyClient
from .gateway import handle_gateway_payload
from .odps_client import execute_sql_to_dicts, make_odps
from .safe_runner import DEFAULT_AUDIT_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "gateway_state.json"


class GatewayState:
    def __init__(
        self,
        *,
        odps,
        token: str,
        audit_path: Path,
        odps_project: str,
        dataworks_client=None,
    ):
        self.odps = odps
        self.token = token
        self.audit_path = audit_path
        self.odps_project = odps_project
        self.dataworks_client = dataworks_client

    def execute(
        self,
        sql: str,
        limit: int | None,
        *,
        hints: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        return execute_sql_to_dicts(self.odps, sql, limit=limit, hints=hints)


def make_handler(state: GatewayState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ODPSReadOnlyGateway/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/query":
                self._send_json(404, {"error": "not found"})
                return

            token = self.headers.get("X-ODPS-Gateway-Token", "")
            if not secrets.compare_digest(token, state.token):
                self._send_json(401, {"error": "unauthorized"})
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rows = handle_gateway_payload(
                    payload,
                    state.execute,
                    audit_path=state.audit_path,
                    dataworks_client=state.dataworks_client,
                    odps_project=state.odps_project,
                )
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return

            self._send_json(200, {"ok": True, "rows": rows})

    return Handler


def write_state(path: Path, *, port: int, token: str) -> None:
    path.write_text(
        json.dumps(
            {
                "base_url": f"http://127.0.0.1:{port}",
                "token": token,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start a local read-only ODPS gateway")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Bind port, default: 8765")
    parser.add_argument("--env", default=str(PROJECT_ROOT / ".env"), help="Path to .env or .env.enc")
    parser.add_argument("--state", default=str(STATE_PATH), help="Path to gateway state JSON")
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH), help="Path to audit JSONL log")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_runtime_settings(args.env)
    odps = make_odps(settings.odps)
    try:
        dataworks_client = DataWorksReadOnlyClient.from_settings(settings.dataworks)
        dataworks_status = "enabled"
    except DataWorksClientError as exc:
        dataworks_client = None
        dataworks_status = f"unavailable: {exc}"

    token = secrets.token_urlsafe(24)
    state = GatewayState(
        odps=odps,
        token=token,
        audit_path=Path(args.audit_log),
        odps_project=settings.odps.project,
        dataworks_client=dataworks_client,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    write_state(Path(args.state), port=server.server_port, token=token)
    print(f"ODPS read-only gateway listening on http://{args.host}:{server.server_port}")
    print(f"DataWorks read-only fallback: {dataworks_status}")
    print(f"State written to {args.state}")
    print("Keep this PowerShell window open. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGateway stopped.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
