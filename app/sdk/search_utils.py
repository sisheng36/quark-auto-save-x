# -*- coding: utf-8 -*-
"""资源搜索结果处理的公共小工具。

PanSou 与 CloudSaver 两个搜索源都要做同一件事：把同一分享链接的多条结果
按发布时间归并成一条。时间字段格式五花八门（"2026-10-21 12:00:00"、
"2026-10-21"、ISO8601 带 Z），这里统一解析成时间戳用于比较。
"""
from datetime import datetime


def parse_datetime_to_ts(date_str) -> float:
    """把常见的日期时间字符串解析成时间戳；解析不出来返回 0（视为最旧）。"""
    if not date_str:
        return 0
    s = str(date_str).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0


def dedupe_by_shareurl(items, time_key):
    """按 shareurl 归并结果，保留 time_key 字段（发布时间）最新的一条。

    Args:
        items: 搜索结果列表，每项至少包含 shareurl
        time_key: 用于比较新旧的字段名（PanSou 为 publish_date，CloudSaver 为 datetime）

    Returns:
        去重后的列表（保持首次出现顺序，值被最新记录替换）
    """
    by_url = {}
    for item in items or []:
        try:
            url = item.get("shareurl", "")
            if not url:
                continue
            existed = by_url.get(url)
            if not existed or parse_datetime_to_ts(item.get(time_key)) > parse_datetime_to_ts(existed.get(time_key)):
                by_url[url] = item
        except Exception:
            continue
    return list(by_url.values())
