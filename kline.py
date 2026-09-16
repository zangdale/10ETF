#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Tiingo 拉取持仓 ETF 日 K，按年写入 kline/yyyy/code.json。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
KLINE_DIR = ROOT / "kline"
INFO_PATH = KLINE_DIR / "info.json"

DEFAULT_CODES = [
    "159307",
    "515180",
    "561580",
    "518680",
    "513870",
    "511010",
    "513650",
    "159985",
    "511360",
    "520870",
]

NAME_OVERRIDES = {
    "515180": "中证红利",
}


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


def load_codes() -> list[str]:
    hold_path = ROOT / "etf_hold.json"
    if not hold_path.is_file():
        return list(DEFAULT_CODES)
    try:
        data = json.loads(hold_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_CODES)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return list(DEFAULT_CODES)
    codes: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes or list(DEFAULT_CODES)


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    hold_path = ROOT / "etf_hold.json"
    if hold_path.is_file():
        try:
            data = json.loads(hold_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "").strip()
                name = str(item.get("name") or "").strip()
                if code and name:
                    names[code] = name
    names.update(NAME_OVERRIDES)
    return names


def load_info_cache() -> dict[str, dict[str, Any]]:
    if not INFO_PATH.is_file():
        return {}
    try:
        data = json.loads(INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if code:
            out[code] = item
    return out


def tiingo_get(path: str, token: str, timeout: int = 30, retries: int = 5) -> Any:
    url = f"https://api.tiingo.com{path}"
    sep = "&" if "?" in path else "?"
    url = f"{url}{sep}token={urllib.parse.quote(token, safe='')}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt + 1 < retries:
                wait = min(120.0, 15.0 * (attempt + 1))
                print(f"  Tiingo 429，{wait:.0f}s 后重试 ({attempt + 1}/{retries})", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err
    return None


def fetch_meta(code: str, token: str) -> dict[str, Any]:
    ticker = urllib.parse.quote(code.strip(), safe="")
    payload = tiingo_get(f"/tiingo/daily/{ticker}", token)
    return payload if isinstance(payload, dict) else {}


def fetch_prices(code: str, token: str, start: str, end: str) -> list[dict[str, Any]]:
    ticker = urllib.parse.quote(code.strip(), safe="")
    q = urllib.parse.urlencode({"startDate": start, "endDate": end})
    payload = tiingo_get(f"/tiingo/daily/{ticker}/prices?{q}", token)
    return payload if isinstance(payload, list) else []


def normalize_bar(row: dict[str, Any]) -> dict[str, Any] | None:
    raw_date = str(row.get("date") or "").strip()
    if not raw_date:
        return None
    day = raw_date[:10]
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        return None
    bar = {
        "date": day,
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "volume": row.get("volume"),
    }
    if not any(isinstance(bar[k], (int, float)) for k in ("open", "high", "low", "close")):
        return None
    return bar


def next_day(ymd: str) -> str:
    return (date.fromisoformat(ymd) + timedelta(days=1)).isoformat()


def list_local_years(code: str) -> list[int]:
    years: list[int] = []
    if not KLINE_DIR.is_dir():
        return years
    for p in KLINE_DIR.iterdir():
        if not p.is_dir() or not p.name.isdigit():
            continue
        if (p / f"{code}.json").is_file():
            years.append(int(p.name))
    return sorted(years)


def load_local_bars(code: str, cached: dict[str, Any] | None) -> list[dict[str, Any]]:
    years = cached.get("years") if isinstance(cached, dict) else None
    year_list = [int(y) for y in years] if isinstance(years, list) and years else list_local_years(code)
    bars: list[dict[str, Any]] = []
    for year in year_list:
        path = KLINE_DIR / str(year) / f"{code}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            bars.extend(item for item in items if isinstance(item, dict) and item.get("date"))
    return merge_bars(bars)


def merge_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for bar in bars:
        day = str(bar.get("date") or "").strip()
        if day:
            by_date[day] = bar
    return [by_date[d] for d in sorted(by_date)]


def split_by_year(bars: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        year = int(bar["date"][:4])
        grouped[year].append(bar)
    for year in grouped:
        grouped[year].sort(key=lambda x: x["date"])
    return dict(grouped)


def write_year_files(code: str, name: str, by_year: dict[int, list[dict[str, Any]]]) -> list[Path]:
    written: list[Path] = []
    for year, year_bars in sorted(by_year.items()):
        year_dir = KLINE_DIR / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)
        out = year_dir / f"{code}.json"
        payload = {
            "code": code,
            "name": name,
            "year": year,
            "items": year_bars,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(out)
    return written


def summarize_bars(bars: list[dict[str, Any]]) -> tuple[str | None, str | None, list[int], int]:
    if not bars:
        return None, None, [], 0
    years = sorted({int(bar["date"][:4]) for bar in bars})
    return bars[0]["date"], bars[-1]["date"], years, len(bars)


def sync_code(
    code: str,
    name: str,
    token: str,
    cached: dict[str, Any] | None,
    *,
    full: bool,
) -> tuple[dict[str, Any], str]:
    meta = fetch_meta(code, token)
    tiingo_start = str(meta.get("startDate") or "").strip()
    tiingo_end = str(meta.get("endDate") or "").strip()
    if not tiingo_start or not tiingo_end:
        raise ValueError("Tiingo 无有效日期范围")

    local_bars: list[dict[str, Any]] = []
    local_end = str(cached.get("end") or "").strip() if cached else ""
    has_local = bool(cached and cached.get("rows") and local_end)

    if full or not has_local:
        mode = "全量"
        fetch_start = tiingo_start
        local_bars = [] if full else load_local_bars(code, cached)
    else:
        mode = "增量"
        fetch_start = next_day(local_end)
        local_bars = load_local_bars(code, cached)

    if fetch_start > tiingo_end:
        bars = local_bars
        first, last, years, rows = summarize_bars(bars)
        return (
            {
                "code": code,
                "name": name,
                "start": first,
                "end": last,
                "years": years,
                "rows": rows,
            },
            f"{mode} · 已是最新（至 {last or tiingo_end}）",
        )

    time.sleep(0.5)
    rows = fetch_prices(code, token, fetch_start, tiingo_end)
    new_bars = [b for b in (normalize_bar(r) for r in rows) if b]
    bars = merge_bars(local_bars + new_bars)
    by_year = split_by_year(bars)
    write_year_files(code, name, by_year)
    first, last, years, row_count = summarize_bars(bars)

    if mode == "增量":
        if new_bars:
            detail = f"增量 +{len(new_bars)} 条（{new_bars[0]['date']} ~ {new_bars[-1]['date']}）"
        else:
            detail = f"增量 · 无新 K 线（Tiingo 至 {tiingo_end}）"
    else:
        detail = f"全量 {row_count} 条 · {first} ~ {last} · {len(by_year)} 个年份文件"

    return (
        {
            "code": code,
            "name": name,
            "start": first,
            "end": last,
            "years": years,
            "rows": row_count,
        },
        detail,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拉取 Tiingo 日 K 到 kline/")
    parser.add_argument(
        "--full",
        action="store_true",
        help="忽略本地缓存，全量重新拉取",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    token = os.environ.get("TIINGO_API_KEY", "").strip()
    if not token:
        print("未配置 TIINGO_API_KEY，请在 .env 中设置", file=sys.stderr)
        return 1

    codes = load_codes()
    names = load_names()
    KLINE_DIR.mkdir(parents=True, exist_ok=True)
    info_cache = load_info_cache()

    if args.full:
        print("模式：全量", flush=True)
    else:
        print("模式：增量（无本地数据时自动全量）", flush=True)

    info_items: list[dict[str, Any]] = []
    for i, code in enumerate(codes):
        name = names.get(code, code)
        print(f"[{i + 1}/{len(codes)}] {code} {name}", flush=True)
        try:
            item, detail = sync_code(
                code,
                name,
                token,
                info_cache.get(code),
                full=args.full,
            )
            info_items.append(item)
            print(f"  {detail}", flush=True)
        except Exception as e:
            print(f"  失败：{e}", file=sys.stderr)
            prev = info_cache.get(code)
            if isinstance(prev, dict):
                kept = dict(prev)
                kept["name"] = name
                kept["error"] = str(e)
                info_items.append(kept)
            else:
                info_items.append(
                    {
                        "code": code,
                        "name": name,
                        "start": None,
                        "end": None,
                        "years": [],
                        "rows": 0,
                        "error": str(e),
                    }
                )
        time.sleep(2.5)

    info = {
        "fetched_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "source": "tiingo",
        "mode": "full" if args.full else "incremental",
        "items": info_items,
    }
    INFO_PATH.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {INFO_PATH} ({len(info_items)} ETFs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
