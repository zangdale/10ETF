#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地静态服务。"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def hold_dates() -> list[str]:
    d = ROOT / "etf_hold"
    if not d.is_dir():
        return []
    dates = []
    for p in d.glob("*.json"):
        if p.name == "index.json":
            continue
        stem = p.stem
        if len(stem) == 10 and stem[4:5] == "-" and stem[7:8] == "-":
            dates.append(stem)
    return sorted(dates)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/index.htm"):
            if path == "/":
                self.send_response(302)
                self.send_header("Location", "/index.html")
                self.end_headers()
                return
        if path in ("/etf_hold/index.json", "/etf_hold/index.json/"):
            body = json.dumps({"dates": hold_dates()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main() -> int:
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8080))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/index.html", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
