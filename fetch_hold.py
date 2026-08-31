#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 adb uiautomator dump 读取同花顺 App 持仓（对齐 easy-T HoldList / JumpPage）。

写入 etf_hold.json 与 etf_hold/yyyy-mm-dd.json。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
HEXIN = "com.hexin.plat.android:id"
MAX_SWIPES = 50


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def resolve_adb() -> str:
    candidates = [
        os.environ.get("ADB_PATH", "").strip(),
        os.environ.get("EASY_T_ADB", "").strip(),
    ]
    home = Path.home()
    candidates.extend(
        [
            str(home / "Library/Android/sdk/platform-tools/adb"),
            str(home / "Android/Sdk/platform-tools/adb"),
            shutil.which("adb") or "",
        ]
    )
    for p in candidates:
        if p and Path(p).is_file() and os.access(p, os.X_OK):
            return p
    looked = shutil.which("adb")
    if looked:
        return looked
    return ""


def parse_float(s: str) -> float:
    s = (s or "").replace(",", "").replace(" ", "").strip()
    s = s.removeprefix("仓位").strip().removesuffix("%").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_uint(s: str) -> int:
    s = (s or "").replace(",", "").replace(" ", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


class UiNode:
    def __init__(self, el: ET.Element) -> None:
        self.el = el
        self.text = el.get("text") or ""
        self.resource_id = el.get("resource-id") or ""
        self.bounds = el.get("bounds") or ""
        self.children = [UiNode(c) for c in list(el) if c.tag.endswith("node") or c.tag == "node"]

    def get_bounds(self) -> tuple[int, int, int, int]:
        m = BOUNDS_RE.fullmatch(self.bounds.strip())
        if not m:
            raise ValueError(f"invalid bounds: {self.bounds}")
        return tuple(int(x) for x in m.groups())  # type: ignore[return-value]

    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.get_bounds()
        return x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2

    def find_by_id(self, resource_id: str) -> UiNode | None:
        if self.resource_id == resource_id:
            return self
        for c in self.children:
            found = c.find_by_id(resource_id)
            if found is not None:
                return found
        return None

    def find_all_by_id(self, resource_id: str) -> list[UiNode]:
        out: list[UiNode] = []
        if self.resource_id == resource_id:
            out.append(self)
        for c in self.children:
            out.extend(c.find_all_by_id(resource_id))
        return out

    def find_all_by_text(self, text: str) -> list[UiNode]:
        out: list[UiNode] = []
        if self.text == text:
            out.append(self)
        for c in self.children:
            out.extend(c.find_all_by_text(text))
        return out

    def child_at(self, index: Iterable[int]) -> UiNode | None:
        temp: UiNode | None = self
        for i in index:
            if temp is None or i < 0 or i >= len(temp.children):
                return None
            temp = temp.children[i]
        return temp


class Adb:
    def __init__(self, binary: str, device: str) -> None:
        self.binary = binary
        self.device = device
        self.data_dir = Path(os.environ.get("ADB_DATA_DIR") or ROOT / ".adb")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _prefix(self) -> list[str]:
        cmd = [self.binary]
        if self.device:
            cmd.extend(["-s", self.device])
        return cmd

    def run(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._prefix() + args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def tap(self, x: int, y: int) -> None:
        self.run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 100) -> None:
        self.run(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)]
        )

    def dump_ui(self) -> UiNode:
        remote = "/sdcard/ui.xml"
        with tempfile.NamedTemporaryFile(
            prefix="adb_dump_", suffix=".xml", dir=self.data_dir, delete=False
        ) as tmp:
            local = Path(tmp.name)
        try:
            self.run(["shell", "uiautomator", "dump", remote])
            self.run(["pull", remote, str(local)])
            tree = ET.parse(local)
            root = tree.getroot()
            nodes = [c for c in list(root) if c.tag.endswith("node") or c.tag == "node"]
            if not nodes:
                raise RuntimeError("uiautomator dump 无 node")
            return UiNode(nodes[0])
        finally:
            local.unlink(missing_ok=True)


def find_by_text(root: UiNode, text: str) -> UiNode | None:
    found = root.find_all_by_text(text)
    return found[0] if found else None


def find_by_ids(root: UiNode, *ids: str) -> UiNode | None:
    for rid in ids:
        n = root.find_by_id(rid)
        if n is not None:
            return n
    return None


def click_node(adb: Adb, node: UiNode | None, what: str) -> None:
    if node is None:
        raise RuntimeError(f"未找到节点：{what}")
    x, y = node.center()
    adb.tap(x, y)


def jump_hold(adb: Adb) -> tuple[UiNode, int, int]:
    info = adb.dump_ui()
    x2, y2 = info.get_bounds()[2], info.get_bounds()[3]
    hold = find_by_text(info, "持仓")
    click_node(adb, hold, "持仓")
    info = adb.dump_ui()
    refresh = find_by_ids(
        info,
        f"{HEXIN}/refresh_container",
        f"{HEXIN}/refresh_img_container",
        f"{HEXIN}/refresh_img",
    )
    click_node(adb, refresh, "刷新")
    info = adb.dump_ui()
    return info, x2, y2


def child_text(node: UiNode, *index: int) -> str:
    n = node.child_at(index)
    return n.text if n is not None else ""


def hold_list(adb: Adb) -> dict[str, Any]:
    info, screen_x, screen_y = jump_hold(adb)
    position = 0.0
    cangwei = find_by_ids(info, f"{HEXIN}/total_cangwei_text")
    if cangwei is not None:
        s = cangwei.text.removeprefix("仓位 ").removesuffix("%")
        position = parse_float(s)

    cells = info.find_all_by_id(f"{HEXIN}/capital_cell_value")
    total = float_profit = total_value = available = 0.0
    if len(cells) >= 4:
        total = parse_float(cells[0].text)
        float_profit = parse_float(cells[1].text)
        total_value = parse_float(cells[2].text)
        available = parse_float(cells[3].text)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    swipe_count = 0
    ended = False

    while True:
        if find_by_text(info, "持仓管理") is not None:
            ended = True
        rv = find_by_ids(info, f"{HEXIN}/recyclerview_id")
        if rv is None:
            raise RuntimeError("未找到持仓列表 recyclerview_id，请确认同花顺交易页已打开")

        children = rv.children
        for i, child in enumerate(children):
            if swipe_count == 0 and i + 1 == len(children):
                break
            if swipe_count > 0 and i == 0:
                continue
            name = child_text(child, 0, 0, 0, 0, 0, 0)
            stock_id = child_text(child, 0, 0, 1, 0, 0)
            amount = child_text(child, 0, 0, 1, 0, 1, 0)
            available_amount = child_text(child, 0, 0, 1, 0, 1, 1)
            cost_price = child_text(child, 0, 0, 1, 0, 2, 0)
            current_price = child_text(child, 0, 0, 1, 0, 2, 1)
            if not stock_id or not name:
                continue
            if stock_id in seen:
                continue
            seen.add(stock_id)
            amt = parse_uint(amount)
            cost = parse_float(cost_price)
            price = parse_float(current_price)
            row: dict[str, Any] = {
                "code": stock_id,
                "name": name,
                "amount": amt,
                "available": parse_uint(available_amount),
                "cost": cost,
                "cost_value": round(amt * cost, 2),
                "price": price,
                "market_value": round(amt * price, 2),
            }
            row["pnl"] = round(row["market_value"] - row["cost_value"], 2)
            if cost > 0:
                row["pnl_pct"] = round((price - cost) / cost * 100, 2)
            else:
                row["pnl_pct"] = None
            items.append(row)

        if ended:
            break
        if swipe_count >= MAX_SWIPES:
            raise RuntimeError(f"滑动超过 {MAX_SWIPES} 次仍未看到「持仓管理」")
        adb.swipe(
            screen_x // 2,
            screen_y // 6 * 4,
            screen_x // 2,
            screen_y // 6 * 3,
            100,
        )
        swipe_count += 1
        info = adb.dump_ui()

    for _ in range(swipe_count + 1):
        adb.swipe(
            screen_x // 2,
            screen_y // 6 * 3,
            screen_x // 2,
            screen_y // 6 * 4,
            100,
        )
        time.sleep(1)

    now = datetime.now()
    return {
        "fetched_at": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "position": position,
        "total": total,
        "float_profit": float_profit,
        "total_value": total_value,
        "available": available,
        "items": items,
    }


TIINGO_META_CACHE = ROOT / ".tiingo_meta.json"


def _load_tiingo_cache() -> dict[str, Any]:
    if not TIINGO_META_CACHE.is_file():
        return {}
    try:
        data = json.loads(TIINGO_META_CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_tiingo_cache(cache: dict[str, Any]) -> None:
    TIINGO_META_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def fetch_tiingo_name(code: str, token: str, timeout: int = 20) -> str | None:
    ticker = urllib.parse.quote(code.strip(), safe="")
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}?token={urllib.parse.quote(token, safe='')}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name") or "").strip()
    return name or None


def enrich_names_from_tiingo(items: list[dict[str, Any]]) -> None:
    token = os.environ.get("TIINGO_API_KEY", "").strip()
    if not token:
        print("未配置 TIINGO_API_KEY，跳过 Tiingo 名称", file=sys.stderr)
        return
    cache = _load_tiingo_cache()
    changed = False
    for item in items:
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        cached = cache.get(code)
        name = str(cached.get("name") or "").strip() if isinstance(cached, dict) else ""
        if not name:
            name = fetch_tiingo_name(code, token) or ""
            if name:
                cache[code] = {"name": name}
                changed = True
            time.sleep(0.15)
        if name:
            item["tiingo_name"] = name
    if changed:
        _save_tiingo_cache(cache)


NAME_OVERRIDES = {
    "515180": "中证红利",
}


def apply_name_overrides(items: list[dict[str, Any]]) -> None:
    for item in items:
        code = str(item.get("code") or "").strip()
        if code in NAME_OVERRIDES:
            item["name"] = NAME_OVERRIDES[code]


def main() -> int:
    load_dotenv(ROOT / ".env")
    adb_bin = resolve_adb()
    if not adb_bin:
        print("未配置 ADB_PATH，请在 .env 中设置 adb 可执行文件路径，例如：", file=sys.stderr)
        print("ADB_PATH=/Users/you/Library/Android/sdk/platform-tools/adb", file=sys.stderr)
        return 1
    device = (
        os.environ.get("ADB_DEVICE", "").strip()
        or os.environ.get("EASY_T_ADB_DEVICE", "").strip()
    )
    adb = Adb(adb_bin, device)
    try:
        snapshot = hold_list(adb)
        enrich_names_from_tiingo(snapshot["items"])
        apply_name_overrides(snapshot["items"])
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        print(f"adb 失败: {err}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    latest = ROOT / "etf_hold.json"
    hist_dir = ROOT / "etf_hold"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist = hist_dir / f"{date.today().isoformat()}.json"
    latest.write_text(text, encoding="utf-8")
    hist.write_text(text, encoding="utf-8")
    print(f"Wrote {latest} ({len(snapshot['items'])} items)")
    print(f"Wrote {hist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
