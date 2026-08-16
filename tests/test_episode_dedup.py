#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
换链接后按"季+集"身份查重的回归测试。

场景：分享链接失效换新链接（洗码重传，fid/文件名/大小全变）后，
保存目录里已有的集数不再重复转存，从下一集继续。
例：目录已有 庆余年.S03E01-E22（本项目重命名过），新链接里是 01.mp4、02.mp4…，
期望 E01-E22 跳过、E23 开始转存。

运行：python3 tests/test_episode_dedup.py
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


def fake_file(name):
    """模拟 ls_dir 返回的目录文件条目"""
    return {"file_name": name, "dir": False, "size": 1, "updated_at": 1}


def decide(dir_names, share_name, task=None):
    """模拟转存前的查重判断：该分享文件是否应因'这一集已转存过'而跳过"""
    index = qas.build_existing_episode_index([fake_file(n) for n in dir_names])
    return qas.is_episode_already_saved(share_name, index, task)


def test_user_main_scenario():
    """主场景：目录已被本项目重命名为 庆余年.S03E01-E22，新链接是裸数字 01.mp4"""
    print("\n[1] 主场景：目录 S03 已重命名 + 新链接裸数字命名（洗码，大小全变）")
    qyn_dir = [f"庆余年.S03E{ep:02d}.mp4" for ep in range(1, 23)]
    task = {"taskname": "庆余年", "pattern": ".*", "replace": "庆余年.S03E{}"}
    check("01.mp4 应跳过（E01 已转存）", decide(qyn_dir, "01.mp4", task), True)
    check("22.mp4 应跳过（E22 已转存）", decide(qyn_dir, "22.mp4", task), True)
    check("23.mp4 应转存（E23 未转存）", decide(qyn_dir, "23.mp4", task), False)
    check("无任务上下文时也应跳过（单一季启发式）", decide(qyn_dir, "01.mp4"), True)
    check("无任务上下文时 E23 也应转存", decide(qyn_dir, "23.mp4"), False)
    # 新链接里带 S 标记的洗码版本同样跳过
    check("新链接 S03E05.4K.mkv 应跳过", decide(qyn_dir, "庆余年第三季.S03E05.2160p.WEB-DL.mkv", task), True)


def test_task_season_context():
    print("\n[2] 任务季上下文：目录多季混杂，靠 taskname/replace 归季")
    mixed_dir = ["庆余年.S01E01.mp4", "庆余年.S01E02.mp4", "庆余年.S02E01.mp4"]
    check(
        "taskname 含'第三季'时 01.mp4 归 S03 → 不跳过",
        decide(mixed_dir, "01.mp4", {"taskname": "庆余年第三季"}),
        False,
    )
    check(
        "taskname 含'第三季'且目录有 S03E01 → 跳过",
        decide(mixed_dir + ["庆余年.S03E01.mp4"], "01.mp4", {"taskname": "庆余年第三季"}),
        True,
    )
    check(
        "replace 模板含 S03E 时 01.mp4 归 S03 → 不跳过",
        decide(mixed_dir, "01.mp4", {"taskname": "庆余年", "replace": "庆余年.S03E{}"}),
        False,
    )
    check(
        "replace 模板含'第2季'时 01.mp4 归 S02 → 跳过",
        decide(mixed_dir, "01.mp4", {"taskname": "庆余年", "replace": "庆余年 第2季 第{}集"}),
        True,
    )


def test_single_season_dir_fallback():
    print("\n[3] 目录无季标记（第xx集式命名）+ 新链接带 S 标记")
    ep_dir = [f"第{ep:02d}集.mp4" for ep in range(1, 23)]
    check("S03E01 应跳过（目录无季标记，退化为按集数）", decide(ep_dir, "庆余年.S03E01.mp4"), True)
    check("S03E23 应转存", decide(ep_dir, "庆余年.S03E23.mp4"), False)
    check("裸数字 01.mp4 应跳过", decide(ep_dir, "01.mp4"), True)


def test_multi_season_safety():
    print("\n[4] 防误杀：多季目录 + 无任务上下文 + 裸数字分享")
    multi_dir = ["庆余年.S01E01.mp4", "庆余年.S02E01.mp4"]
    check("多季目录裸数字 01.mp4 不跳过（歧义，宁可转存）", decide(multi_dir, "01.mp4"), False)
    check("多季目录精确 S02E01 跳过", decide(multi_dir, "庆余年.S02E01.mp4"), True)
    check("多季目录 S03E01 转存", decide(multi_dir, "庆余年.S03E01.mp4"), False)
    check("中文季标记'第2季 第02集' → (2,2) 未转存 → 转存", decide(multi_dir, "第2季 第02集.mp4"), False)
    check("中文季标记'第2季 第01集' → (2,1) 命中 S02E01 → 跳过", decide(multi_dir, "第2季 第01集.mp4"), True)
    check(
        "中文季标记 + 目录只有 S01 → 不误跳",
        decide(["庆余年.S01E01.mp4"], "第2季 第01集.mp4"),
        False,
    )


def test_subtitle_and_format():
    print("\n[5] 字幕保护与洗码换封装")
    qyn_dir = [f"庆余年.S03E{ep:02d}.mp4" for ep in range(1, 23)]
    check("视频不挡字幕：01.srt 应转存", decide(qyn_dir, "01.srt"), False)
    check("视频不挡字幕：S03E01.ass 应转存", decide(qyn_dir, "庆余年.S03E01.ass"), False)
    check("字幕挡字幕：目录已有第01集.srt 时 01.srt 跳过", decide(["第01集.srt"], "01.srt"), True)
    check("洗码换封装：目录 mkv + 新 mp4 → 跳过", decide(["庆余年.S03E01.mkv"], "01.mp4"), True)


def test_no_episode_files():
    print("\n[6] 无集数文件不受影响（走原有查重）")
    check("电影名提不出集数 → 不跳过", decide(["阿凡达.水之道.mp4"], "The.Way.of.Water.2160p.mkv"), False)
    check("花絮无集数 → 不跳过", decide(["庆余年.S03E01.mp4"], "花絮.ts"), False)
    check("日期型综艺名 → 不跳过", decide(["快乐大本营.20250801.mp4"], "快乐大本营.20250808.mp4"), False)


def test_extractors():
    print("\n[7] 单元：extract_season_episode_key / extract_episode_number / extract_task_season")
    check("S03E01 → (3, 1)", qas.extract_season_episode_key("庆余年.S03E01.mp4"), (3, 1))
    check("裸数字 01.mp4 → (None, 1)", qas.extract_season_episode_key("01.mp4"), (None, 1))
    check("第2季 第01集 → (2, 1)", qas.extract_season_episode_key("第2季 第01集.mp4"), (2, 1))
    check("中文季 第三季01 → (3, 1)", qas.extract_season_episode_key("庆余年第三季01.mp4"), (3, 1))
    check("Season 2 E01 → (2, 1)", qas.extract_season_episode_key("Show.Season.2.E01.mp4"), (2, 1))
    check("第01集（无季）→ (None, 1)", qas.extract_season_episode_key("第01集.mp4"), (None, 1))
    check("无集数 → None", qas.extract_season_episode_key("海报.jpg"), None)
    check("纯数字兜底 extract_episode_number('01.mp4') == 1", qas.extract_episode_number("01.mp4"), 1)
    check("taskname 第三季 → 3", qas.extract_task_season({"taskname": "庆余年 第三季"}), 3)
    check("taskname 第十二季 → 12", qas.extract_task_season({"taskname": "海贼王 第十二季"}), 12)
    check("replace S03E{} → 3", qas.extract_task_season({"taskname": "庆余年", "replace": "庆余年.S03E{}"}), 3)
    check("无季上下文 → None", qas.extract_task_season({"taskname": "庆余年"}), None)


def test_index_shape():
    print("\n[8] 单元：build_existing_episode_index 索引结构")
    index = qas.build_existing_episode_index(
        [
            fake_file("庆余年.S03E01.mp4"),
            fake_file("第02集.srt"),
            {"file_name": "Season3", "dir": True},  # 目录不计入
        ]
    )
    check("se 索引", index["se"], {(3, 1): {"media"}})
    check("ep 索引（字幕类别）", index["ep"], {2: {"subtitle"}})
    check("seasons 集合", index["seasons"], {3})
    check("空目录 → 空索引", qas.build_existing_episode_index([]), {"se": {}, "ep": {}, "seasons": set()})


if __name__ == "__main__":
    test_user_main_scenario()
    test_task_season_context()
    test_single_season_dir_fallback()
    test_multi_season_safety()
    test_subtitle_and_format()
    test_no_episode_files()
    test_extractors()
    test_index_shape()
    print(f"\n结果：{PASSED} 通过, {FAILED} 失败")
    sys.exit(1 if FAILED else 0)
