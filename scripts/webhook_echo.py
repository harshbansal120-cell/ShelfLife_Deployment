"""A local webhook receiver for testing stale-claim alerts.

Set ALERT_WEBHOOK_URL=http://127.0.0.1:9000/ in .env, restart the backend, run
this script, then check an answer with a stale claim. Each alert is printed here.

    python scripts/webhook_echo.py
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9000


class Echo(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (the name http.server expects)
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(min(length, 1_000_000))
        try:
            payload = json.loads(body)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        except ValueError:
            print(body[:2000].decode("utf-8", "replace"))
        print("-" * 60, flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    print(f"Listening for ShelfLife alerts on http://127.0.0.1:{PORT}/ (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", PORT), Echo).serve_forever()
