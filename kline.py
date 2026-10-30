#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取持仓 ETF 日 K，按年写入 kline/yyyy/code.json。

优先东财；连接被对端直接断开时改用腾讯行情（不复权，成交量同样换算成股）。
同时从天天基金拉取现金分红，记到对应年份日 K 的 dps 字段。
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
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
DPS_RE = re.compile(r"每\s*([0-9]+(?:\.[0-9]+)?)\s*份.*?([0-9]+(?:\.[0-9]+)?)\s*元")
ROW_RE = re.compile(
    r"<tr><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td></tr>"
)
EASTMONEY_START = "1990-01-01"

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


def shift_day(ymd: str, days: int) -> str:
    return (date.fromisoformat(ymd) + timedelta(days=days)).isoformat()


def is_shanghai(code: str) -> bool:
    return code.startswith(("5", "6", "9"))


def eastmoney_secid(code: str) -> str:
    market = "1" if is_shanghai(code) else "0"
    return f"{market}.{code}"


def qq_symbol(code: str) -> str:
    prefix = "sh" if is_shanghai(code) else "sz"
    return f"{prefix}{code}"


def fetch_eastmoney_bars(code: str, start: str, end: str, retries: int = 4) -> list[dict[str, Any]]:
    """东财不复权日 K。成交量单位是手，乘 100 换成股。"""
    q = urllib.parse.urlencode(
        {
            "secid": eastmoney_secid(code),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start.replace("-", ""),
            "end": end.replace("-", ""),
            "lmt": "1000000",
        }
    )
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{q}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    last_err: Exception | None = None
    payload: Any = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    if payload is None and last_err:
        raise last_err
    klines = (payload.get("data") or {}).get("klines") if isinstance(payload, dict) else None
    if not isinstance(klines, list):
        return []
    bars: list[dict[str, Any]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        day = parts[0].strip()
        if len(day) != 10 or day[4] != "-" or day[7] != "-":
            continue
        try:
            bar = {
                "date": day,
                "open": round(float(parts[1]), 4),
                "high": round(float(parts[3]), 4),
                "low": round(float(parts[4]), 4),
                "close": round(float(parts[2]), 4),
                "volume": int(round(float(parts[5]) * 100)),
            }
        except ValueError:
            continue
        if not any(isinstance(bar[k], (int, float)) for k in ("open", "high", "low", "close")):
            continue
        bars.append(bar)
    return bars


def fetch_qq_bars(code: str, start: str, end: str, retries: int = 3) -> list[dict[str, Any]]:
    """腾讯不复权日 K。成交量单位是手，乘 100 换成股。单次最多约 2000 根，更早的往前翻页。"""
    symbol = qq_symbol(code)
    bars_by_date: dict[str, dict[str, Any]] = {}
    page_end = end
    for _page in range(30):
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param="
            f"{symbol},day,{start},{page_end},2000,"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://gu.qq.com/",
            },
        )
        payload: Any = None
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                last_err = e
                if attempt + 1 < retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                raise
        if payload is None and last_err:
            raise last_err
        node: Any = None
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                node = data.get(symbol)
        rows = node.get("day") if isinstance(node, dict) else None
        if not isinstance(rows, list) or not rows:
            break
        earliest: str | None = None
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            day = str(row[0]).strip()
            if len(day) != 10 or day[4] != "-" or day[7] != "-" or day < start or day > end:
                continue
            if earliest is None or day < earliest:
                earliest = day
            try:
                bar = {
                    "date": day,
                    "open": round(float(row[1]), 4),
                    "high": round(float(row[3]), 4),
                    "low": round(float(row[4]), 4),
                    "close": round(float(row[2]), 4),
                    "volume": int(round(float(row[5]) * 100)),
                }
            except ValueError:
                continue
            bars_by_date[day] = bar
        if earliest is None or earliest <= start or len(rows) < 2000:
            break
        nxt = shift_day(earliest, -1)
        if nxt >= page_end or nxt < start:
            break
        page_end = nxt
        time.sleep(0.2)
    return [bars_by_date[d] for d in sorted(bars_by_date)]


def fetch_bars(code: str, start: str, end: str) -> tuple[list[dict[str, Any]], str]:
    """优先东财。对端直接断开时改用腾讯，避免在已失效的地址上反复重试。"""
    try:
        return fetch_eastmoney_bars(code, start, end, retries=1), "eastmoney"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return fetch_qq_bars(code, start, end), "tencent"


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
        if not day:
            continue
        merged = dict(bar)
        prev = by_date.get(day)
        if prev and prev.get("dps") and not merged.get("dps"):
            merged["dps"] = prev["dps"]
        by_date[day] = merged
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
    cached: dict[str, Any] | None,
    *,
    full: bool,
    today: str,
) -> tuple[dict[str, Any], str, str]:
    local_end = str(cached.get("end") or "").strip() if cached else ""
    has_local = bool(cached and cached.get("rows") and local_end)

    if full or not has_local:
        mode = "全量"
        fetch_start = EASTMONEY_START
        local_bars: list[dict[str, Any]] = []
    else:
        mode = "增量"
        fetch_start = shift_day(local_end, -15)
        local_bars = load_local_bars(code, cached)

    remote, source = fetch_bars(code, fetch_start, today)
    remote = [bar for bar in remote if bar["date"] <= today]
    if not remote and not local_bars:
        raise ValueError("无日 K")

    if full or not has_local:
        bars = remote
        new_bars = list(remote)
    else:
        have = {str(bar.get("date") or "") for bar in local_bars}
        new_bars = [bar for bar in remote if bar["date"] not in have]
        bars = merge_bars(local_bars + new_bars)

    if new_bars:
        by_year = split_by_year(bars)
        years_to_write = {int(bar["date"][:4]) for bar in new_bars}
        write_year_files(code, name, {year: by_year[year] for year in years_to_write})

    first, last, years, row_count = summarize_bars(bars)
    via = "" if source == "eastmoney" else " · 腾讯"
    if new_bars:
        detail = f"{mode} +{len(new_bars)} 条（{new_bars[0]['date']} ~ {new_bars[-1]['date']}）{via}"
    else:
        detail = f"{mode} · 已是最新（至 {last or today}）{via}"

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
        source,
    )


def parse_dps(text: str) -> float | None:
    """「每10份派现金0.6100元」→ 每股 0.061 元。"""
    match = DPS_RE.search(text.replace(",", ""))
    if not match:
        return None
    shares = float(match.group(1))
    cash = float(match.group(2))
    if shares <= 0 or cash < 0:
        return None
    return round(cash / shares, 6)


def fetch_fund_dividends(code: str) -> list[dict[str, Any]]:
    """天天基金分红送配。返回按除息日升序的现金分红，dps 为每股元。"""
    url = f"https://fundf10.eastmoney.com/fhsp_{code}.html"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    table = None
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            time.sleep(0.8 * (attempt + 1))
            continue
        table = re.search(r"<table class='w782 comm cfxq'>(.*?)</table>", raw, re.S)
        if table:
            break
        last_err = ValueError("分红页面无表格")
        time.sleep(0.8 * (attempt + 1))
    else:
        raise last_err or ValueError("分红页面无表格")
    assert table is not None
    if "暂无分红" in table.group(1):
        return []
    by_date: dict[str, dict[str, Any]] = {}
    for _year, record, ex_date, amount, pay in ROW_RE.findall(table.group(1)):
        day = ex_date.strip() or pay.strip() or record.strip()
        if len(day) != 10 or day[4] != "-" or day[7] != "-":
            continue
        dps = parse_dps(amount)
        if dps is None or dps <= 0:
            continue
        prev = by_date.get(day)
        event = {
            "date": day,
            "dps": dps if not prev else round(prev["dps"] + dps, 6),
        }
        record_day = record.strip()
        pay_day = pay.strip()
        if len(record_day) == 10:
            event["record"] = record_day
        if len(pay_day) == 10:
            event["pay"] = pay_day
        by_date[day] = event
    return [by_date[d] for d in sorted(by_date)]


def apply_dividends(code: str, name: str, events: list[dict[str, Any]]) -> int:
    """把每股分红写进除息日当天的 K 线；当天无 K 线则记到之后首个交易日。"""
    bars = load_local_bars(code, None)
    if not bars:
        return 0
    changed_years: set[int] = set()
    for bar in bars:
        if "dps" in bar:
            bar.pop("dps", None)
            changed_years.add(int(str(bar["date"])[:4]))
    dates = [str(bar["date"]) for bar in bars]
    applied = 0
    for event in events:
        day = str(event.get("date") or "")
        dps = event.get("dps")
        if len(day) != 10 or not isinstance(dps, (int, float)) or dps <= 0:
            continue
        idx = bisect.bisect_left(dates, day)
        if idx >= len(bars):
            continue
        bar_day = dates[idx]
        lag = (date.fromisoformat(bar_day) - date.fromisoformat(day)).days
        if lag > 10:
            continue
        bar = bars[idx]
        bar["dps"] = round(float(bar.get("dps") or 0) + float(dps), 6)
        changed_years.add(int(str(bar["date"])[:4]))
        applied += 1
    if changed_years:
        by_year = split_by_year(bars)
        write_year_files(code, name, {year: by_year[year] for year in changed_years if year in by_year})
    return applied


def sync_dividends(codes: list[str], names: dict[str, str]) -> None:
    print("分红：写入各年日 K", flush=True)
    for i, code in enumerate(codes):
        name = names.get(code, code)
        print(f"  [{i + 1}/{len(codes)}] {code} {name}", flush=True)
        try:
            events = fetch_fund_dividends(code)
            applied = apply_dividends(code, name, events)
            print(f"    {applied}/{len(events)} 次写入日 K", flush=True)
        except Exception as e:
            print(f"    失败：{e}（保留已有 dps）", file=sys.stderr)
        time.sleep(0.25)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拉取日 K 到 kline/")
    parser.add_argument(
        "--full",
        action="store_true",
        help="忽略本地缓存，全量重新拉取",
    )
    parser.add_argument(
        "--dividend",
        action="store_true",
        help="只把分红写入各年日 K，不拉行情",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today().isoformat()
    codes = load_codes()
    names = load_names()
    KLINE_DIR.mkdir(parents=True, exist_ok=True)
    if args.dividend:
        sync_dividends(codes, names)
        return 0
    info_cache = load_info_cache()

    if args.full:
        print("模式：全量", flush=True)
    else:
        print(f"模式：增量（无本地数据时自动全量，截止 {today}）", flush=True)

    info_items: list[dict[str, Any]] = []
    sources: set[str] = set()
    for i, code in enumerate(codes):
        name = names.get(code, code)
        print(f"[{i + 1}/{len(codes)}] {code} {name}", flush=True)
        try:
            item, detail, source = sync_code(
                code,
                name,
                info_cache.get(code),
                full=args.full,
                today=today,
            )
            sources.add(source)
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
        time.sleep(0.4)

    info = {
        "fetched_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "source": "+".join(sorted(sources)) if sources else "eastmoney",
        "mode": "full" if args.full else "incremental",
        "items": info_items,
    }
    INFO_PATH.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {INFO_PATH} ({len(info_items)} ETFs)")
    sync_dividends(codes, names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
