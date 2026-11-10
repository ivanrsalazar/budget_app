from __future__ import annotations

import json
import mimetypes
import os
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from budget.store import Store, parse_date


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DEFAULT_SAMPLE = ROOT / "resources" / "Finances - Winter '26_'27.csv"
STORE = Store(Path(os.environ.get("BUDGET_DB", ROOT / "data" / "budget.db")))


class BudgetHandler(BaseHTTPRequestHandler):
    server_version = "TrueNorth/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/bootstrap":
                self.json_response({
                    "settings": STORE.settings(),
                    "recurring": STORE.list_items("recurring_items"),
                    "transactions": STORE.list_items("transactions"),
                    "credit_lines": STORE.list_items("credit_lines"),
                })
            elif parsed.path == "/api/projection":
                query = parse_qs(parsed.query)
                start = parse_date(query.get("start", [date.today().isoformat()])[0])
                through = parse_date(query.get("through", [start.isoformat()])[0])
                weeks = int(query.get("weeks", ["12"])[0])
                self.json_response(STORE.projection(start, weeks, through))
            elif parsed.path.startswith("/api/"):
                self.error_response(HTTPStatus.NOT_FOUND, "API route not found")
            else:
                self.serve_static(parsed.path)
        except (ValueError, TypeError) as exc:
            self.error_response(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unexpected error: {exc}")

    def do_POST(self) -> None:
        self.mutate("POST")

    def do_PUT(self) -> None:
        self.mutate("PUT")

    def do_DELETE(self) -> None:
        self.mutate("DELETE")

    def mutate(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json() if method != "DELETE" else {}
            if path == "/api/settings" and method == "PUT":
                self.json_response(STORE.update_settings(payload))
                return

            parts = [part for part in path.split("/") if part]
            if len(parts) not in {2, 3} or parts[0] != "api" or parts[1] not in {"recurring", "transactions", "credit-lines"}:
                self.error_response(HTTPStatus.NOT_FOUND, "API route not found")
                return
            table = {"recurring": "recurring_items", "transactions": "transactions", "credit-lines": "credit_lines"}[parts[1]]
            item_id = int(parts[2]) if len(parts) == 3 else None
            if method == "POST" and item_id is None:
                self.json_response(STORE.save_item(table, payload), HTTPStatus.CREATED)
            elif method == "PUT" and item_id is not None:
                self.json_response(STORE.save_item(table, payload, item_id))
            elif method == "DELETE" and item_id is not None:
                STORE.delete_item(table, item_id)
                self.json_response({"ok": True})
            else:
                self.error_response(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
        except KeyError as exc:
            self.error_response(HTTPStatus.NOT_FOUND, str(exc))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.error_response(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unexpected error: {exc}")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def json_response(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error_response(self, status: HTTPStatus, message: str) -> None:
        self.json_response({"error": message}, status)

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        requested = (PUBLIC / relative).resolve()
        if PUBLIC.resolve() not in requested.parents and requested != PUBLIC.resolve():
            self.error_response(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not requested.is_file():
            requested = PUBLIC / "index.html"
        body = requested.read_bytes()
        mime, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> None:
    sample = Path(os.environ.get("BUDGET_SAMPLE_CSV", DEFAULT_SAMPLE))
    STORE.initialize(sample)
    host = os.environ.get("BUDGET_HOST", "127.0.0.1")
    port = int(os.environ.get("BUDGET_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), BudgetHandler)
    print(f"TrueNorth Budget is running at http://{host}:{port}")
    print(f"Database: {STORE.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

