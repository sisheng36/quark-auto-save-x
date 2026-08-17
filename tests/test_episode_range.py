#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「集数范围」功能回归测试：只转存指定区间内的集。

场景：分享链接里有 01-16 集，任务配置起始 11、结束 16，则只转存第 11~16 集，
01-10 被过滤；只配置起始集时从该集起转存到结尾；识别不了集号的文件安全跳过。

运行：python3 tests/test_episode_range.py
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
    """模拟分享文件列表条目"""
    return {"file_name": name, "dir": is_dir, "size": 1, "updated_at": 1}


def names(result):
    return [f["file_name"] for f in result]


def make_list(start, end):
    """生成 E01..E16 的分享列表（含技术规格干扰命名的样例）"""
    items = []
    for ep in range(start, end + 1):
        items.append(fake_file(f"剧名 - 第{ep:02d}集.mp4"))
    return items


def test_not_configured():
    """未配置范围：原样返回"""
    print("\n[1] 未配置范围（不改变现有行为）")
    lst = make_list(1, 16)
    result = qas.filter_files_by_episode_range(lst, {})
    check("无配置返回原列表", result, lst)
    check("无配置长度不变", len(result), 16)
    result2 = qas.filter_files_by_episode_range(lst, {"episode_start": "", "episode_end": ""})
    check("空字符串视为未配置", len(result2), 16)
    result3 = qas.filter_files_by_episode_range(lst, {"episode_start": "abc", "episode_end": "xyz"})
    check("非数字视为未配置", len(result3), 16)


def test_main_scenario():
    """主场景：01-16 只转存 11-16"""
    print("\n[2] 主场景：起始 11、结束 16，分享含 01-16")
    lst = make_list(1, 16)
    result = qas.filter_files_by_episode_range(lst, {"episode_start": 11, "episode_end": 16})
    check("只保留 11-16（10 个被过滤）", len(result), 6)
    check("E11 保留（含边界）", names(result)[0], "剧名 - 第11集.mp4")
    check("E16 保留（含边界）", names(result)[-1], "剧名 - 第16集.mp4")
    check("E10 不在结果中", "剧名 - 第10集.mp4" not in names(result), True)


def test_start_only():
    """只配置起始集：从该集起转存到结尾"""
    print("\n[3] 只配置起始 11")
    lst = make_list(1, 16)
    result = qas.filter_files_by_episode_range(lst, {"episode_start": 11})
    check("保留 11-16", len(result), 6)
    check("E01 被过滤", "剧名 - 第01集.mp4" not in names(result), True)


def test_end_only():
    """只配置结束集：只转存该集及之前"""
    print("\n[4] 只配置结束 10")
    lst = make_list(1, 16)
    result = qas.filter_files_by_episode_range(lst, {"episode_end": 10})
    check("保留 01-10", len(result), 10)
    check("E16 被过滤", "剧名 - 第16集.mp4" not in names(result), True)


def test_filename_formats():
    """多种文件名格式与集号提取"""
    print("\n[5] 多种文件名格式")
    lst = [
        fake_file("01.mp4"),                     # 裸数字
        fake_file("Show.S01E11.mkv"),            # SxxExx
        fake_file("[1080P]第12集.mp4"),          # 技术规格前缀
        fake_file("剧名 - 第13集.H265.4K.mp4"),  # 技术规格干扰
        fake_file("Special 花絮合集.mp4"),       # 无法识别集号
    ]
    result = qas.filter_files_by_episode_range(lst, {"episode_start": 11, "episode_end": 13})
    check("E01 被过滤", "01.mp4" not in names(result), True)
    check("S01E11 保留", "Show.S01E11.mkv" in names(result), True)
    check("[1080P]第12集 保留", "[1080P]第12集.mp4" in names(result), True)
    check("E13 保留", "剧名 - 第13集.H265.4K.mp4" in names(result), True)
    check("无法识别集号的文件被跳过", "Special 花絮合集.mp4" not in names(result), True)


def test_folders_kept():
    """文件夹条目始终保留（交给更新目录逻辑）"""
    print("\n[6] 文件夹保留")
    lst = [
        fake_file("Season1", is_dir=True),
        fake_file("剧名 - 第01集.mp4"),
        fake_file("剧名 - 第16集.mp4"),
    ]
    result = qas.filter_files_by_episode_range(lst, {"episode_start": 11})
    check("文件夹保留", "Season1" in names(result), True)
    check("E01 被过滤", "剧名 - 第01集.mp4" not in names(result), True)
    check("E16 保留", "剧名 - 第16集.mp4" in names(result), True)


def test_extraction_prereq():
    """前置确认：extract_episode_number 对测试文件名的提取行为"""
    print("\n[0] 集号提取前置断言")
    check("01.mp4 -> 1", qas.extract_episode_number("01.mp4"), 1)
    check("Show.S01E11.mkv -> 11", qas.extract_episode_number("Show.S01E11.mkv"), 11)
    check("[1080P]第12集.mp4 -> 12", qas.extract_episode_number("[1080P]第12集.mp4"), 12)
    check("剧名 - 第13集.H265.4K.mp4 -> 13", qas.extract_episode_number("剧名 - 第13集.H265.4K.mp4"), 13)
    check("Special 花絮合集.mp4 -> None", qas.extract_episode_number("Special 花絮合集.mp4"), None)


if __name__ == "__main__":
    test_extraction_prereq()
    test_not_configured()
    test_main_scenario()
    test_start_only()
    test_end_only()
    test_filename_formats()
    test_folders_kept()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    if FAILED:
        sys.exit(1)
    print("EPISODE RANGE TEST PASSED")
