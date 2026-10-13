#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地同屏查看 10 只 ETF 的雪球页面。

雪球股票页是脚本渲染，且首页有阿里云 WAF，直接请求 HTML 拿不到
`.stock__main`。这里只提供页面和代码列表；浏览器里用 iframe 打开雪球，
再按实测偏移裁出主体。行情由雪球页面自己更新。
"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parent


def symbol_of(code: str) -> str:
    exch = "SZ" if code.startswith("1") else "SH"
    return exch + code


def load_etfs() -> list[dict]:
    items: list[dict] = []
    info = ROOT / "kline" / "info.json"
    if info.is_file():
        data = json.loads(info.read_text(encoding="utf-8"))
        for it in data.get("items") or []:
            code = str(it.get("code") or "").strip()
            if not code:
                continue
            items.append({"code": code, "name": str(it.get("name") or code)})
    if not items:
        hold = ROOT / "etf_hold.json"
        if hold.is_file():
            data = json.loads(hold.read_text(encoding="utf-8"))
            for it in data.get("items") or []:
                code = str(it.get("code") or "").strip()
                if not code:
                    continue
                items.append({"code": code, "name": str(it.get("name") or code)})
    out = []
    for it in items:
        symbol = symbol_of(it["code"])
        out.append(
            {
                "code": it["code"],
                "name": it["name"],
                "symbol": symbol,
                "url": f"https://xueqiu.com/S/{symbol}",
            }
        )
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DESKTOP), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/etfs":
            body = json.dumps({"items": load_etfs()}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main() -> int:
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8765))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
