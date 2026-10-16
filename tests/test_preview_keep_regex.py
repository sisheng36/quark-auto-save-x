#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预览接口回归：/get_share_detail 的命名预览必须把任务级「正则规则」(keep_regex) 算进过滤，
不转存的文件与真实转存保持一致（预览列显示 ×）。

做法：在进程内加载真实 Flask 应用，用一个假的 Quark 账号替换网络层，
用测试客户端发真实 HTTP 请求，全程不访问网络。

运行：python3 tests/test_preview_keep_regex.py
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

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


def load_webapp():
    """加载真实 Flask 应用模块（module 级只有定义与配置读取，不会启动服务）"""
    app_dir = os.path.join(REPO, "app")
    if app_dir not in sys.path:
        # app/run.py 以 app 目录为根导入 sdk/utils
        sys.path.insert(0, app_dir)
    path = os.path.join(app_dir, "run.py")
    spec = importlib.util.spec_from_file_location("qas_webapp_for_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    # 应用在真实运行时才加载配置，这里只填预览接口需要的最小配置
    mod.config_data.update(
        {
            "webui": {"username": "test", "password": "test"},
            "task_settings": {"filterwords": ""},
            "episode_patterns": [],
            "cookie": ["kps=x;sign=y;vcode=z"],
        }
    )
    return mod


SHARE_FILES = [
    {"fid": "f1", "file_name": "电影.2026.2160p.mkv", "dir": False, "size": 11, "updated_at": 1},
    {"fid": "f2", "file_name": "电影.2026.1080p.mp4", "dir": False, "size": 12, "updated_at": 1},
    {"fid": "f3", "file_name": "电影.2026.720p.mp4", "dir": False, "size": 13, "updated_at": 1},
    {"fid": "f4", "file_name": "海报.jpg", "dir": False, "size": 14, "updated_at": 1},
]

EPISODE_FILES = [
    {"fid": "e1", "file_name": "剧名.01.2160p.mkv", "dir": False, "size": 21, "updated_at": 1},
    {"fid": "e2", "file_name": "剧名.01.1080p.mp4", "dir": False, "size": 22, "updated_at": 1},
    {"fid": "e3", "file_name": "剧名.02.2160p.mkv", "dir": False, "size": 23, "updated_at": 1},
]


def make_fake_quark(files):
    class FakeQuark(qas.Quark):
        def __init__(self, cookie, index=0):
            super().__init__(cookie or "kps=x;sign=y;vcode=z", index or 0)
            self.episode_patterns = []

        def extract_url(self, url):
            return ("pwd_test", "", 0, [])

        def get_stoken(self, pwd_id, passcode):
            return (True, "stoken_test", {})

        def get_detail(self, pwd_id, stoken, pdir_fid=0, **kwargs):
            return {"list": [dict(f) for f in files]}

    return FakeQuark


def preview(mod, files, regex):
    """走真实 HTTP：POST /get_share_detail"""
    mod.Quark = make_fake_quark(files)
    token = mod.get_login_token()
    client = mod.app.test_client()
    resp = client.post(
        f"/get_share_detail?token={token}",
        json={"shareurl": "https://pan.quark.cn/s/abcdef", "stoken": "stoken_test", "regex": regex},
    )
    body = resp.get_json()
    assert body and body.get("success"), body
    return body["data"]["list"]


def preview_cell(item):
    """预览列：与前端模板一致——没有 file_name_re 就显示 ×"""
    return item.get("file_name_re") or "×"


def base_regex(**overrides):
    regex = {
        "pattern": r"^(.*)\.(2160p|1080p|720p)\.(mkv|mp4)$",
        "replace": r"电影 (2026).\3",
        "taskname": "电影",
        "filterwords": "",
        "keep_regex": "",
        "magic_regex": {},
        "use_sequence_naming": False,
        "sequence_naming": "",
        "use_episode_naming": False,
        "episode_naming": "",
        "episode_patterns": [],
    }
    regex.update(overrides)
    return regex


def test_regex_mode_preview():
    print("\n[1] 正则命名预览：正则规则只保留匹配项，其余显示 ×")
    mod = load_webapp()
    rows = preview(mod, SHARE_FILES, base_regex(keep_regex="2160p"))
    cells = {r["file_name"]: (preview_cell(r), bool(r.get("filtered", False))) for r in rows}
    check("2160p 保留并算出新名", cells["电影.2026.2160p.mkv"], ("电影 (2026).mkv", False))
    check("1080p 被正则规则拦下 → ×", cells["电影.2026.1080p.mp4"], ("×", True))
    check("720p 被正则规则拦下 → ×", cells["电影.2026.720p.mp4"], ("×", True))

    print("\n[2] 留空对照：行为与现在完全一致")
    rows2 = preview(mod, SHARE_FILES, base_regex(keep_regex=""))
    cells2 = {r["file_name"]: preview_cell(r) for r in rows2}
    check("2160p 有名字", cells2["电影.2026.2160p.mkv"], "电影 (2026).mkv")
    check("1080p 有名字", cells2["电影.2026.1080p.mp4"], "电影 (2026).mp4")
    check("720p 有名字", cells2["电影.2026.720p.mp4"], "电影 (2026).mp4")

    print("\n[3] 优先级：过滤规则先剔除，正则规则不能把文件捞回来")
    rows3 = preview(mod, SHARE_FILES, base_regex(keep_regex="2160p|1080p", filterwords="1080p"))
    cells3 = {r["file_name"]: (preview_cell(r), bool(r.get("filtered", False))) for r in rows3}
    check("1080p 被过滤规则剔除 → ×", cells3["电影.2026.1080p.mp4"], ("×", True))
    check("2160p 仍保留", cells3["电影.2026.2160p.mkv"][0], "电影 (2026).mkv")


def test_episode_mode_preview():
    print("\n[4] 剧集命名预览：被正则规则拦下的集显示 ×")
    mod = load_webapp()
    rows = preview(
        mod,
        EPISODE_FILES,
        base_regex(
            use_episode_naming=True,
            episode_naming="剧名.S01E[]",
            pattern="剧名.S01E[]",
            replace="",
            keep_regex="2160p",
        ),
    )
    cells = {r["file_name"]: (preview_cell(r), bool(r.get("filtered", False))) for r in rows}
    check("E01 2160p 保留并命名", cells["剧名.01.2160p.mkv"], ("剧名.S01E01.mkv", False))
    check("E01 1080p 显示 ×", cells["剧名.01.1080p.mp4"], ("×", True))
    check("E02 2160p 保留并命名", cells["剧名.02.2160p.mkv"], ("剧名.S01E02.mkv", False))


if __name__ == "__main__":
    test_regex_mode_preview()
    test_episode_mode_preview()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    if FAILED:
        sys.exit(1)
    print("PREVIEW KEEP REGEX TEST PASSED")
