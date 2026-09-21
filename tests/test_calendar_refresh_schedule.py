#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""追剧日历服务端刷新调度：到期判定与本地 meta 持久化。

运行：python3 tests/test_calendar_refresh_schedule.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from sdk.db import CalendarDB, compute_calendar_refresh_schedule  # noqa: E402

PASSED = 0
FAILED = 0


def check(name, actual, expected):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}: 期望 {expected}, 实际 {actual}")


def test_schedule():
    print("compute_calendar_refresh_schedule")
    check("关闭自动刷新", compute_calendar_refresh_schedule(1000, 0, 0), (False, None))
    check("负周期视为关闭", compute_calendar_refresh_schedule(1000, 10, -1), (False, None))
    check("从未刷新则立即跑", compute_calendar_refresh_schedule(1000, 0, 21600), (True, 21600))
    check("已到期则立即跑", compute_calendar_refresh_schedule(22000, 100, 21600), (True, 21600))
    check("未到期则等到剩余秒数", compute_calendar_refresh_schedule(1100, 1000, 21600), (False, 21500))
    check("刚好到期", compute_calendar_refresh_schedule(21700, 100, 21600), (True, 21600))
    check("非法周期视为关闭", compute_calendar_refresh_schedule(1000, 1, "x"), (False, None))


def test_meta_and_touch():
    print("CalendarDB meta / last_refreshed_at")
    tmp = tempfile.mkdtemp()
    db = CalendarDB(os.path.join(tmp, "data.db"))
    check("meta 缺失返回 None", db.get_meta("last_full_refresh_at"), None)
    db.set_meta("last_full_refresh_at", 123456)
    check("meta 读写", db.get_meta("last_full_refresh_at"), "123456")
    db.upsert_show(1, "Show", "2024", "播出中", "", 1, 0, "", "tv", 0)
    db.touch_show_refreshed_at(1, 999)
    show = db.get_show(1)
    check("touch last_refreshed_at", int(show.get("last_refreshed_at") or 0), 999)
    db.close()


if __name__ == "__main__":
    test_schedule()
    test_meta_and_touch()
    print(f"\n通过 {PASSED}，失败 {FAILED}")
    sys.exit(1 if FAILED else 0)
