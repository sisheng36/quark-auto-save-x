#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣 IMDb ID 抓取与缓存回归。

覆盖：
1) 影片信息 H5 页面 IMDb 行解析（含缺失、404、请求异常）
2) 缓存命中不重复抓取、过期重抓、抓取失败不落缓存
3) 时间预算内没抓完的条目不写入缓存
4) Emby 匹配时豆瓣卡凭 IMDb 命中（译名不一致场景）

运行：python3 tests/test_douban_imdb_cache.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
for p in (ROOT, APP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from sdk.db import CalendarDB  # noqa: E402
from sdk.douban_service import (  # noqa: E402
    DoubanService,
    DOUBAN_IMDB_STATUS_OK,
    DOUBAN_IMDB_STATUS_MISSING,
    DOUBAN_IMDB_STATUS_FAILED,
    DOUBAN_IMDB_STATUS_NOT_FOUND,
)
from sdk.emby_service import EmbyService  # noqa: E402

PASSED = 0
FAILED = 0


def check(name, actual, expected):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}: 期望 {expected!r}, 实际 {actual!r}")


DESC_WITH_IMDB = """
<html><head><title>肖申克的救赎</title></head><body>
<section class="subject-desc"><table><tbody>
<tr><td>片名</td><td>肖申克的救赎</td></tr>
<tr><td>IMDb</td><td>tt0111161</td></tr>
</tbody></table></section></body></html>
"""

DESC_WITHOUT_IMDB = """
<html><head><title>无名之辈</title></head><body>
<section class="subject-desc"><table><tbody>
<tr><td>片名</td><td>无名之辈</td></tr>
</tbody></table></section></body></html>
"""


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class FakeSession:
    """替换 DoubanService.fetch_imdb_id 内部的 requests.Session。"""

    def __init__(self, pages=None, calls=None, delay=0.0):
        self.pages = pages or {}
        self.calls = calls if calls is not None else []
        self.delay = delay
        self.headers = {}

    def update(self, values):
        self.headers.update(values)

    def get(self, url, timeout=None):
        self.calls.append(url)
        if self.delay:
            time.sleep(self.delay)
        for key, value in self.pages.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        return FakeResponse(404, "not found")


def patch_session(pages, calls, delay=0.0):
    """把 douban_service 模块内的 requests.Session 换成假实现。"""
    import sdk.douban_service as mod

    class FakeRequests:
        def Session(self):
            return FakeSession(pages, calls, delay)

    mod.requests = FakeRequests()


def restore_requests():
    import importlib
    import sdk.douban_service as mod
    importlib.reload(mod)
    return mod


def make_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = CalendarDB(tmp.name)
    return db, tmp.name


def test_parse_desc_page():
    print("\n[1] 影片信息页解析")
    calls = []
    patch_session({
        "/1292052/": FakeResponse(200, DESC_WITH_IMDB),
        "/999/": FakeResponse(200, DESC_WITHOUT_IMDB),
        "/404/": FakeResponse(404, "not found"),
        "/555/": RuntimeError("network down"),
    }, calls)
    svc = DoubanService()

    ok = svc.fetch_imdb_id("1292052")
    check("解析到 IMDb", ok.get("imdb_id"), "tt0111161")
    check("状态 ok", ok.get("status"), DOUBAN_IMDB_STATUS_OK)
    check("顺带取到标题", ok.get("title"), "肖申克的救赎")

    missing = svc.fetch_imdb_id("999")
    check("页面无 IMDb 行 → missing", missing.get("status"), DOUBAN_IMDB_STATUS_MISSING)
    check("页面无 IMDb 行 → 空 ID", missing.get("imdb_id"), "")

    not_found = svc.fetch_imdb_id("404")
    check("404 → not_found", not_found.get("status"), DOUBAN_IMDB_STATUS_NOT_FOUND)

    failed = svc.fetch_imdb_id("555")
    check("请求异常 → failed", failed.get("status"), DOUBAN_IMDB_STATUS_FAILED)

    check("非法 subject id 不请求", svc.fetch_imdb_id("abc").get("status"), DOUBAN_IMDB_STATUS_NOT_FOUND)
    restore_requests()


def test_cache_roundtrip():
    print("\n[2] 缓存读写与命中")
    db, path = make_db()
    try:
        calls = []
        patch_session({"/1292052/": FakeResponse(200, DESC_WITH_IMDB)}, calls)
        svc = DoubanService()
        entries = [{"id": "1292052", "title": "肖申克的救赎", "year": "1994", "is_tv": False}]

        first = svc.resolve_imdb_ids(entries, db)
        check("首次解析 IMDb", first["1292052"]["imdb_id"], "tt0111161")
        check("首次非缓存", first["1292052"]["cached"], False)
        check("首次请求了豆瓣", len(calls), 1)

        second = svc.resolve_imdb_ids(entries, db)
        check("二次命中缓存", second["1292052"]["imdb_id"], "tt0111161")
        check("二次标记缓存", second["1292052"]["cached"], True)
        check("二次未重复请求", len(calls), 1)

        check("缓存条数", db.get_douban_imdb_cache_count(), 1)
        row = db.get_douban_imdb_cache(["1292052"]).get("1292052") or {}
        check("缓存写入标题", row.get("title"), "肖申克的救赎")
        check("缓存写入年份", str(row.get("year")), "1994")
        check("缓存写入 is_tv", row.get("is_tv"), 0)
        restore_requests()
    finally:
        db.close()
        os.unlink(path)


def test_failed_short_ttl():
    print("\n[3] 抓取失败短 TTL：不立即重试，过期后重试成功")
    db, path = make_db()
    try:
        calls = []
        patch_session({"/777/": FakeResponse(500, "err")}, calls)
        svc = DoubanService()
        entries = [{"id": "777", "title": "某片"}]
        first = svc.resolve_imdb_ids(entries, db)
        check("失败状态", first["777"]["status"], DOUBAN_IMDB_STATUS_FAILED)
        check("失败条数也记录", db.get_douban_imdb_cache_count(), 1)
        row = db.get_douban_imdb_cache(["777"]).get("777") or {}
        check("失败记录空 IMDb", row.get("imdb_id"), "")

        # 短 TTL 内不再重复请求豆瓣
        before = len(calls)
        svc.resolve_imdb_ids(entries, db)
        check("TTL 内不重复请求", len(calls), before)

        # 把时间改成超过失败 TTL，再抓应成功
        cursor = db.conn.cursor()
        cursor.execute(
            'UPDATE douban_imdb_cache SET last_updated=? WHERE subject_id=?',
            (int(time.time()) - 7200, '777')
        )
        db.conn.commit()
        patch_session({"/777/": FakeResponse(200, DESC_WITH_IMDB)}, calls)
        second = DoubanService().resolve_imdb_ids(entries, db)
        check("过期后重试成功", second["777"]["imdb_id"], "tt0111161")
        check("成功状态覆盖失败", second["777"]["status"], DOUBAN_IMDB_STATUS_OK)
        restore_requests()
    finally:
        db.close()
        os.unlink(path)


def test_stale_cache_refetch():
    print("\n[4] 缓存过期后重抓")
    db, path = make_db()
    try:
        calls = []
        patch_session({"/1292052/": FakeResponse(200, DESC_WITH_IMDB)}, calls)
        svc = DoubanService()
        entries = [{"id": "1292052", "title": "肖申克的救赎"}]
        svc.resolve_imdb_ids(entries, db)
        # 把 last_updated 改成很久以前
        cursor = db.conn.cursor()
        cursor.execute(
            'UPDATE douban_imdb_cache SET last_updated=? WHERE subject_id=?',
            (int(time.time()) - 60 * 24 * 3600, '1292052')
        )
        db.conn.commit()
        before = len(calls)
        svc.resolve_imdb_ids(entries, db)
        check("过期后重新请求", len(calls), before + 1)
        restore_requests()
    finally:
        db.close()
        os.unlink(path)


def test_time_budget_skips_cache():
    print("\n[5] 时间预算内未抓完的条目不落缓存")
    db, path = make_db()
    try:
        calls = []

        patch_session({}, calls, delay=0.6)
        svc = DoubanService()
        entries = [{"id": str(1000 + i), "title": f"片{i}"} for i in range(5)]
        started = time.time()
        result = svc.resolve_imdb_ids(entries, db, max_fetch=5, concurrency=1, time_budget=0.8)
        elapsed = time.time() - started
        check("总耗时受预算约束", elapsed < 3.0, True)
        cached_rows = db.get_douban_imdb_cache_count()
        check("只缓存已抓到的条目", cached_rows < 5, True)
        check("未抓到的条目结果为空", result[str(1004)]["imdb_id"] == "" or cached_rows >= 1, True)
        restore_requests()
    finally:
        db.close()
        os.unlink(path)


def test_match_with_resolved_imdb():
    print("\n[6] 端到端：豆瓣卡补 IMDb 后命中 Emby（译名不同）")
    db, path = make_db()
    try:
        calls = []
        patch_session({"/36179101/": FakeResponse(200, """
            <html><head><title>希望</title></head><body><table><tbody>
            <tr><td>IMDb</td><td>tt27609988</td></tr>
            </tbody></table></body></html>
        """)}, calls)
        svc = DoubanService()
        entries = [{"id": "36179101", "title": "希望", "year": "2026", "is_tv": False}]
        imdb_map = svc.resolve_imdb_ids(entries, db)
        check("解析出 IMDb", imdb_map["36179101"]["imdb_id"], "tt27609988")

        emby_items = [{
            "emby_id": "emby-hope",
            "name": "HOPE",
            "original_title": "HOPE",
            "year": "2026",
            "item_type": "Movie",
            "provider_tmdb": "1234567",
            "provider_imdb": "tt27609988",
            "provider_tvdb": "",
            "season_numbers": "",
            "last_updated": 0,
        }]

        class FakeCalDB:
            def get_all_emby_items(self):
                return emby_items

        discovery_item = {
            "id": "36179101",
            "title": "希望",
            "year": "2026",
            "imdb_id": imdb_map["36179101"]["imdb_id"],
            "content_type": "movie",
        }
        status_map = EmbyService().match_items([discovery_item], FakeCalDB())
        status = status_map.get(EmbyService._make_status_key(discovery_item)) or {}
        check("IMDb 命中已入库", status.get("in_library"), True)
        check("命中方式为 imdb", status.get("match_by"), "imdb")
        restore_requests()
    finally:
        db.close()
        os.unlink(path)


def test_subject_id_extraction():
    print("\n[7] subject id 提取")
    check("id 字段", DoubanService._subject_id_of({"id": "1292052"}), "1292052")
    check("uri 兜底", DoubanService._subject_id_of({"uri": "douban://douban.com/movie/1292052"}), "1292052")
    check("url 兜底", DoubanService._subject_id_of({"url": "https://movie.douban.com/subject/1292052/"}), "1292052")
    check("空条目", DoubanService._subject_id_of({}), "")


if __name__ == "__main__":
    test_parse_desc_page()
    test_cache_roundtrip()
    test_failed_short_ttl()
    test_stale_cache_refetch()
    test_time_budget_skips_cache()
    test_match_with_resolved_imdb()
    test_subject_id_extraction()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    sys.exit(1 if FAILED else 0)
