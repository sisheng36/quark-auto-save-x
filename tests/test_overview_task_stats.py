#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""总览任务统计：类型/追更中/今日加入/状态互斥/待处理排除规则。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from utils.overview_task_stats import (  # noqa: E402
    compute_overview_task_stats,
    format_shareurl_ban_message,
    is_recoverable_share_error,
    localize_show_status,
    progress_from_season_counts,
    should_count_shareurl_ban,
)

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


def test_share_ban_helpers():
    print("\n[1] 分享失效文案与可恢复错误")
    check(
        "封禁链接格式化",
        format_shareurl_ban_message("分享者用户封禁链接查看受限"),
        "该分享已失效，不可访问",
    )
    check(
        "过期格式化",
        format_shareurl_ban_message("分享地址已过期"),
        "该分享已过期，无法访问",
    )
    check(
        "删除格式化",
        format_shareurl_ban_message("文件已被分享者删除"),
        "该分享已被删除，无法访问",
    )
    check("可恢复网络错误返回 None", format_shareurl_ban_message("request error"), None)
    check("识别可恢复错误", is_recoverable_share_error("inner error"), True)
    check("可恢复不计入待处理", should_count_shareurl_ban("网络错误"), False)
    check("已格式化失效计入", should_count_shareurl_ban("该分享已失效，不可访问"), True)


def test_progress_and_status():
    print("\n[2] 进度与状态本地化")
    check("无 season_counts 为 None", progress_from_season_counts(None), None)
    check("全 0 为 None", progress_from_season_counts({"transferred_count": 0, "aired_count": 0, "total_count": 0}), None)
    check("aired=0 返回 0", progress_from_season_counts({"transferred_count": 3, "aired_count": 0, "total_count": 10}), 0)
    check("向下取整百分比", progress_from_season_counts({"transferred_count": 1, "aired_count": 3, "total_count": 10}), 33)
    check("returning 默认播出中", localize_show_status("returning_series"), "播出中")
    check(
        "returning 本季终",
        localize_show_status("returning_series", is_season_finale=True, aired=12, total=12),
        "本季终",
    )
    check("ended 已完结", localize_show_status("ended"), "已完结")
    check("已是中文则保持", localize_show_status("播出中"), "播出中")


def test_type_ongoing_today():
    print("\n[3] 类型 / 追更中 / 今日加入")
    tasks = [
        {"taskname": "剧A", "content_type": "tv", "shareurl_subscribed_since": "2026-09-20 08:00:00"},
        {"taskname": "动画B", "content_type": "anime"},
        {"taskname": "纪录C", "calendar_info": {"extracted": {"content_type": "documentary"}}},
        {"taskname": "综艺D", "content_type": "variety"},
        {"taskname": "电影E", "content_type": "movie"},
        {"taskname": "其它F"},
        {"taskname": "今日G", "content_type": "tv", "shareurl_subscribed_since": "2026-09-20"},
    ]
    calendar = {
        "剧A": {"season_counts": {"transferred_count": 5, "aired_count": 10, "total_count": 12}},
        "动画B": {"season_counts": {"transferred_count": 12, "aired_count": 12, "total_count": 12}},
        "纪录C": {"content_type": "documentary", "season_counts": {"transferred_count": 0, "aired_count": 0, "total_count": 0}},
        "综艺D": {"season_counts": {"transferred_count": 1, "aired_count": 8, "total_count": 20}},
        "电影E": {"season_counts": {"transferred_count": 1, "aired_count": 1, "total_count": 1}},
    }
    stats = compute_overview_task_stats(tasks, calendar_by_name=calendar, today="2026-09-20")
    check("剧集数", stats["tv_count"], 2)
    check("动画数", stats["anime_count"], 1)
    check("纪录片数", stats["documentary_count"], 1)
    check("综艺数", stats["variety_count"], 1)
    check("电影数", stats["movie_count"], 1)
    check("其他数", stats["other_count"], 1)
    # 剧A 进度 50%、纪录C 进度缺失、综艺D 进度 <100、今日G 进度缺失 → 4；动画B 100% 不计
    check("追更中", stats["ongoing_count"], 4)
    check("今日加入", stats["today_count"], 2)


def test_status_mutex():
    print("\n[4] 状态分布互斥")
    tasks = [
        {"taskname": "播出", "content_type": "tv"},
        {"taskname": "季终", "content_type": "tv"},
        {"taskname": "完结未满", "content_type": "tv"},
        {"taskname": "已上映满", "content_type": "movie"},
        {"taskname": "未匹配", "content_type": "tv"},
        {"taskname": "已取消满", "content_type": "tv"},
    ]
    calendar = {
        "播出": {"matched_status": "播出中", "match_tmdb_id": 1, "season_counts": {"transferred_count": 1, "aired_count": 2, "total_count": 10}},
        "季终": {"matched_status": "本季终", "match_tmdb_id": 2, "season_counts": {"transferred_count": 10, "aired_count": 10, "total_count": 10}},
        "完结未满": {"matched_status": "已完结", "match_tmdb_id": 3, "season_counts": {"transferred_count": 1, "aired_count": 10, "total_count": 10}},
        "已上映满": {"matched_status": "已上映", "match_tmdb_id": 4, "season_counts": {"transferred_count": 1, "aired_count": 1, "total_count": 1}},
        "已取消满": {"matched_status": "已取消", "match_tmdb_id": 5, "season_counts": {"transferred_count": 8, "aired_count": 8, "total_count": 8}},
    }
    stats = compute_overview_task_stats(tasks, calendar_by_name=calendar)
    check("播出中", stats["status_airing"], 1)
    check("本季终优先于已完成", stats["status_finale"], 1)
    check("已完结即使进度未满", stats["status_ended"], 1)
    check("已上映+100% 计入已上映桶", stats["status_completed"], 2)
    check("未匹配", stats["status_unmatched"], 1)


def test_failed_excludes_complete():
    print("\n[5] 待处理：已完成排除，未完成计入，可恢复不计")
    tasks = [
        {"taskname": "完成仍失效", "content_type": "tv", "shareurl_ban": "该分享已失效，不可访问"},
        {"taskname": "未完成失效", "content_type": "tv", "shareurl_ban": "分享地址已失效"},
        {"taskname": "临时错误", "content_type": "tv", "shareurl_ban": "request error"},
        {"taskname": "无标记", "content_type": "tv", "shareurl": "https://pan.quark.cn/s/abc"},
        {"shareurl_ban": "该分享已过期，无法访问"},
    ]
    complete = {"完成仍失效": True, "未完成失效": False}
    stats = compute_overview_task_stats(tasks, complete_by_name=complete)
    check("待处理数量", stats["failed_count"], 2)
    names = [item["taskname"] for item in stats["failed_tasks"]]
    check("不含已完成", "完成仍失效" in names, False)
    check("含未完成", "未完成失效" in names, True)
    check("不含可恢复", "临时错误" in names, False)
    check("无任务名仍可计入", "" in names, True)
    check(
        "未完成文案已格式化",
        stats["failed_tasks"][0]["shareurl_ban"],
        "该分享已失效，不可访问",
    )


def main():
    test_share_ban_helpers()
    test_progress_and_status()
    test_type_ongoing_today()
    test_status_mutex()
    test_failed_excludes_complete()
    print(f"\n通过 {PASSED}，失败 {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
