#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局过滤规则：先按 task_settings.filterwords 剔除，再叠加任务级 filterwords。

运行：python3 tests/test_global_filterwords.py
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


def sample_list():
    return [
        fake_file("剧名 - 第01集.mkv"),
        fake_file("剧名 - 第01集.nfo"),
        fake_file("海报.jpg"),
        fake_file("说明.txt"),
        fake_file("剧名 - 加更.mkv"),
        fake_file("剧名 - 纯享.mkv"),
    ]


def apply(files, task_fw="", global_fw=""):
    return qas.apply_task_file_filters(
        files,
        {"filterwords": task_fw},
        {"filterwords": global_fw},
    )


def test_no_filters():
    print("\n[1] 未配置全局和任务：不改变现有行为")
    lst = sample_list()
    result = apply(lst, "", "")
    check("空配置返回原列表", result, lst)
    check("长度不变", len(result), 6)
    result2 = apply(lst, "  ", "  ")
    check("空白字符串视为未配置", names(result2), names(lst))


def test_global_only():
    print("\n[2] 仅全局：去掉 jpg/nfo/txt")
    result = apply(sample_list(), "", "jpg，nfo，txt")
    check("去掉扩展名匹配的文件", names(result), [
        "剧名 - 第01集.mkv",
        "剧名 - 加更.mkv",
        "剧名 - 纯享.mkv",
    ])
    result2 = apply(sample_list(), "", "jpg,nfo,txt")
    check("英文逗号同样生效", names(result2), names(result))


def test_global_plus_task():
    print("\n[3] 全局 + 任务：先去扩展名，再去任务词")
    result = apply(sample_list(), "加更，纯享", "jpg，nfo，txt")
    check("只保留正片", names(result), ["剧名 - 第01集.mkv"])


def test_task_empty_global_applies():
    print("\n[4] 任务规则为空、全局有值：仍过滤")
    result = apply(sample_list(), "", "nfo")
    check("nfo 被剔除", "剧名 - 第01集.nfo" not in names(result), True)
    check("mkv 保留", "剧名 - 第01集.mkv" in names(result), True)


def test_task_only_unchanged():
    print("\n[5] 仅任务规则：与原来 advanced_filter_files 一致")
    lst = sample_list()
    task_fw = "加更，纯享"
    combined = apply(lst, task_fw, "")
    direct = qas.advanced_filter_files(lst, task_fw)
    check("无全局时等价于任务过滤", names(combined), names(direct))


def test_keep_words_after_global():
    print("\n[6] 全局排除 + 任务保留词|过滤词")
    lst = [
        fake_file("期-正片.mkv"),
        fake_file("期-加更.mkv"),
        fake_file("期-封面.jpg"),
        fake_file("花絮.mkv"),
        fake_file("readme.txt"),
    ]
    result = apply(lst, "期|加更", "jpg，txt")
    check("先剔除 jpg/txt，再保留含「期」且去掉加更", names(result), ["期-正片.mkv"])


def test_config_data_fallback():
    print("\n[7] 未传入 task_settings 时回落到 CONFIG_DATA")
    old = qas.CONFIG_DATA
    try:
        qas.CONFIG_DATA = {"task_settings": {"filterwords": "jpg，txt"}}
        result = qas.apply_task_file_filters(sample_list(), {"filterwords": ""})
        check("从 CONFIG_DATA 读取全局规则", "海报.jpg" not in names(result), True)
        check("txt 被剔除", "说明.txt" not in names(result), True)
        check("mkv 保留", "剧名 - 第01集.mkv" in names(result), True)
    finally:
        qas.CONFIG_DATA = old


if __name__ == "__main__":
    test_no_filters()
    test_global_only()
    test_global_plus_task()
    test_task_empty_global_applies()
    test_task_only_unchanged()
    test_keep_words_after_global()
    test_config_data_fallback()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    if FAILED:
        sys.exit(1)
    print("GLOBAL FILTERWORDS TEST PASSED")
