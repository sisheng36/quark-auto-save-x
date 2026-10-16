#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务级「正则规则」（keep_regex）：过滤规则的反向规则，只转存文件名匹配该正则的文件。

场景：同一部电影分享了好几种规格（1080p/4K/mkv/mp4），任务里填一条正则只保留其中一个。

运行：python3 tests/test_keep_regex.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quark_auto_save as qas

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


def fake_file(name, is_dir=False):
    return {"file_name": name, "dir": is_dir, "size": 1, "updated_at": 1}


def names(result):
    return [f["file_name"] for f in result]


def movie_share():
    """同一部电影的多种规格 + 一个文件夹 + 杂项文件"""
    return [
        fake_file("电影名.2026.2160p.HDR.mkv"),
        fake_file("电影名.2026.1080p.WEB-DL.mp4"),
        fake_file("电影名.2026.720p.HD.mp4"),
        fake_file("电影名.2026.1080p.中字.srt"),
        fake_file("电影名 (2026)", is_dir=True),
        fake_file("海报.jpg"),
    ]


def apply(files, keep_regex="", task_fw="", global_fw=""):
    return qas.apply_task_file_filters(
        files,
        {"filterwords": task_fw, "keep_regex": keep_regex},
        {"filterwords": global_fw},
    )


def test_keep_regex_basic():
    print("\n[1] 正则规则：只保留匹配项")
    result = apply(movie_share(), "2160p|4K")
    check("只留下 2160p 规格", names(result), ["电影名.2026.2160p.HDR.mkv", "电影名 (2026)"])
    result2 = apply(movie_share(), r"\.1080p\..*\.(mp4|srt)$")
    check("多条规格用 | 组合", names(result2), [
        "电影名.2026.1080p.WEB-DL.mp4",
        "电影名.2026.1080p.中字.srt",
        "电影名 (2026)",
    ])


def test_empty_rule_is_noop():
    print("\n[2] 留空/空白：不改变现有行为")
    lst = movie_share()
    check("空串无副作用", apply(lst, "") == lst, True)
    check("空白串无副作用", apply(lst, "   ") == lst, True)
    check("None 无副作用", qas.filter_files_by_keep_regex(lst, None) == lst, True)


def test_priority_lower_than_filters():
    print("\n[3] 优先级：全局过滤规则 > 任务过滤规则 > 正则规则")
    lst = movie_share()
    # 全局过滤掉 jpg；任务过滤掉 srt；正则只保留 1080p
    result = apply(lst, "1080p", task_fw="srt", global_fw="jpg")
    check("过滤规则先剔除，正则只保留匹配项", names(result), [
        "电影名.2026.1080p.WEB-DL.mp4",
        "电影名 (2026)",
    ])
    # 被过滤规则剔除的文件，即使匹配正则也不会回来
    result2 = apply(lst, "2160p|1080p", task_fw="1080p", global_fw="")
    check("任务过滤规则剔除的不因匹配正则而回来", names(result2), [
        "电影名.2026.2160p.HDR.mkv",
        "电影名 (2026)",
    ])


def test_folders_kept():
    print("\n[4] 文件夹始终保留（是否递归由分享结构/更新目录决定）")
    lst = [fake_file("Season 01", is_dir=True), fake_file("01.mp4"), fake_file("02.mp4")]
    result = apply(lst, r"^02")
    check("不匹配的文件夹不删除", names(result), ["Season 01", "02.mp4"])


def test_invalid_regex_fallback():
    print("\n[5] 正则非法：打印提示并原样返回，不影响转存")
    lst = movie_share()
    result = apply(lst, "([unclosed")
    check("非法正则不生效", names(result), names(lst))


def test_keep_regex_ignored_for_local_dir():
    print("\n[6] 本地目录列表不套用正则规则（apply_keep_regex=False）")
    lst = movie_share()
    kept = qas.apply_task_file_filters(lst, {"keep_regex": "2160p"}, {}, apply_keep_regex=False)
    check("本地重命名流程保留全部文件", names(kept), names(lst))
    kept_share = qas.apply_task_file_filters(lst, {"keep_regex": "2160p"}, {})
    check("分享侧仍然只保留匹配项", names(kept_share), ["电影名.2026.2160p.HDR.mkv", "电影名 (2026)"])


def test_episode_style_share():
    print("\n[7] 剧集场景：只转存 4K 版本")
    lst = [
        fake_file("剧名.S01E01.2160p.mkv"),
        fake_file("剧名.S01E01.1080p.mp4"),
        fake_file("剧名.S01E02.2160p.mkv"),
        fake_file("剧名.S01E02.1080p.mp4"),
    ]
    result = apply(lst, "2160p")
    check("每集只留 4K", names(result), ["剧名.S01E01.2160p.mkv", "剧名.S01E02.2160p.mkv"])


if __name__ == "__main__":
    test_keep_regex_basic()
    test_empty_rule_is_noop()
    test_priority_lower_than_filters()
    test_folders_kept()
    test_invalid_regex_fallback()
    test_keep_regex_ignored_for_local_dir()
    test_episode_style_share()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    if FAILED:
        sys.exit(1)
    print("KEEP REGEX TEST PASSED")
