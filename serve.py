#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地静态服务：监视 HTML 与持仓 JSON，变更后浏览器自动刷新。"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WATCH_FILES = ("index.html", "history.html", "etf_hold.json")
INJECT = """
<script>
(function () {
  let stamp = null;
  async function poll() {
    try {
      const r = await fetch("/__watch", { cache: "no-store" });
      if (!r.ok) return;
      const d = await r.json();
      if (stamp !== null && d.stamp !== stamp) location.reload();
      stamp = d.stamp;
    } catch (e) {}
  }
  setInterval(poll, 700);
  poll();
})();
</script>
"""


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


def watch_stamp() -> float:
    latest = 0.0
    for name in WATCH_FILES:
        p = ROOT / name
        if p.is_file():
            latest = max(latest, p.stat().st_mtime)
    hold_dir = ROOT / "etf_hold"
    if hold_dir.is_dir():
        for p in hold_dir.glob("*.json"):
            latest = max(latest, p.stat().st_mtime)
    return latest


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/etf_hold/index.json", "/etf_hold/index.json/"):
            body = json.dumps({"dates": hold_dates()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/__watch":
            body = json.dumps({"stamp": watch_stamp()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/index.html") or path.endswith(".html"):
            rel = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            fp = (ROOT / rel).resolve()
            if fp.is_file() and str(fp).startswith(str(ROOT)):
                html = fp.read_text(encoding="utf-8")
                if "</body>" in html:
                    html = html.replace("</body>", INJECT + "</body>", 1)
                else:
                    html += INJECT
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        super().do_GET()


def main() -> int:
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8080))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(
        f"http://127.0.0.1:{port}/index.html  （监视 HTML / etf_hold）",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
