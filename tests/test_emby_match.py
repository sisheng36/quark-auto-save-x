#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影视发现 Emby 入库匹配：多季剧集标题（末日地堡 第三季）应识别为已入库。

运行：python3 tests/test_emby_match.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

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
        print(f"  ❌ {name}: 期望 {expected}, 实际 {actual}")


class FakeCalDB:
    def __init__(self, items):
        self._items = items

    def get_all_emby_items(self):
        return self._items


def silo_series(**overrides):
    item = {
        "emby_id": "emby-silo",
        "name": "末日地堡",
        "original_title": "Silo",
        "year": "2023",
        "item_type": "Series",
        "provider_tmdb": "125988",
        "provider_imdb": "",
        "provider_tvdb": "",
        "season_numbers": "1,2,3",
        "last_updated": 0,
    }
    item.update(overrides)
    return item


def movie_item(**overrides):
    item = {
        "emby_id": "emby-movie",
        "name": "沙丘",
        "original_title": "Dune",
        "year": "2021",
        "item_type": "Movie",
        "provider_tmdb": "438631",
        "provider_imdb": "",
        "provider_tvdb": "",
        "season_numbers": "",
        "last_updated": 0,
    }
    item.update(overrides)
    return item


def match_one(emby_items, discovery_item):
    svc = EmbyService()
    status_map = svc.match_items([discovery_item], FakeCalDB(emby_items))
    key = EmbyService._make_status_key(discovery_item)
    return status_map.get(key) or {}


def test_split_season_suffix():
    print("\n[1] 单元：_split_season_suffix")
    cases = [
        ("末日地堡 第三季", ("末日地堡", 3)),
        ("末日地堡第三季", ("末日地堡", 3)),
        ("末日地堡 第3季", ("末日地堡", 3)),
        ("海贼王 第十二季", ("海贼王", 12)),
        ("Silo Season 3", ("Silo", 3)),
        ("Silo S03", ("Silo", 3)),
        ("Silo S03E01", ("Silo", 3)),
        ("末日地堡", ("末日地堡", None)),
        ("沙丘", ("沙丘", None)),
        ("", ("", None)),
    ]
    for title, expected in cases:
        check(repr(title), EmbyService._split_season_suffix(title), expected)


def test_chinese_numeral():
    print("\n[2] 单元：_chinese_numeral_to_int")
    cases = [
        ("三", 3),
        ("十", 10),
        ("十二", 12),
        ("二十四", 24),
        ("两", 2),
        ("1", 1),
        ("", None),
    ]
    for text, expected in cases:
        check(repr(text), EmbyService._chinese_numeral_to_int(text), expected)


def test_silo_season_cards():
    print("\n[3] 末日地堡多季卡片")
    library = [silo_series()]

    s3 = match_one(library, {
        "title": "末日地堡 第三季",
        "year": "2025",
        "content_type": "tv",
    })
    check("第三季 已入库", s3.get("in_library"), True)
    check("第三季 季列表", s3.get("seasons"), "1,2,3")
    check("第三季 匹配名", s3.get("matched_name"), "末日地堡")

    s3_nospace = match_one(library, {
        "title": "末日地堡第三季",
        "year": "2025",
        "content_type": "tv",
    })
    check("无空格第三季 已入库", s3_nospace.get("in_library"), True)

    s4 = match_one(library, {
        "title": "末日地堡 第四季",
        "year": "2026",
        "content_type": "tv",
    })
    check("第四季 未入库", s4.get("in_library"), False)

    series = match_one(library, {
        "title": "末日地堡",
        "year": "2023",
        "content_type": "tv",
    })
    check("无季后缀 已入库", series.get("in_library"), True)

    year_mismatch = match_one(library, {
        "title": "末日地堡 第三季",
        "year": "2025",
        "content_type": "tv",
    })
    check("分季年份与开播年相差>1 仍命中", year_mismatch.get("in_library"), True)


def test_english_season_titles():
    print("\n[4] 英文季后缀匹配 original_title")
    library = [silo_series()]

    season = match_one(library, {
        "title": "Silo Season 3",
        "year": "2025",
        "content_type": "tv",
    })
    check("Silo Season 3 已入库", season.get("in_library"), True)

    sxx = match_one(library, {
        "title": "Silo S03",
        "year": "2025",
        "content_type": "tv",
    })
    check("Silo S03 已入库", sxx.get("in_library"), True)


def test_empty_season_numbers():
    print("\n[5] 缓存无季列表时不误报红")
    library = [silo_series(season_numbers="")]
    s3 = match_one(library, {
        "title": "末日地堡 第三季",
        "year": "2025",
        "content_type": "tv",
    })
    check("season_numbers 为空 → 已入库", s3.get("in_library"), True)


def test_exact_season_named_series():
    print("\n[6] Emby 条目名本身带季后缀")
    library = [silo_series(name="末日地堡 第三季", original_title="", season_numbers="1")]
    s3 = match_one(library, {
        "title": "末日地堡 第三季",
        "year": "2025",
        "content_type": "tv",
    })
    check("整标题命中 → 已入库", s3.get("in_library"), True)


def test_movie_not_stripped():
    print("\n[7] 电影标题不被季逻辑误伤")
    library = [movie_item()]
    movie = match_one(library, {
        "title": "沙丘",
        "year": "2021",
        "content_type": "movie",
        "media_type": "movie",
    })
    check("电影精确标题 已入库", movie.get("in_library"), True)

    fake_season = match_one(library, {
        "title": "沙丘 第三季",
        "year": "2021",
        "content_type": "movie",
        "media_type": "movie",
    })
    check("电影带季后缀不剥季匹配", fake_season.get("in_library"), False)


def test_tmdb_id_path():
    print("\n[8] TMDB ID 路径不变")
    library = [silo_series()]
    by_id = match_one(library, {
        "title": "Silo",
        "year": "2023",
        "tmdb_id": 125988,
        "media_type": "tv",
        "content_type": "tv",
    })
    check("tmdb id 已入库", by_id.get("in_library"), True)
    check("tmdb id 匹配名", by_id.get("matched_name"), "末日地堡")


if __name__ == "__main__":
    test_split_season_suffix()
    test_chinese_numeral()
    test_silo_season_cards()
    test_english_season_titles()
    test_empty_season_numbers()
    test_exact_season_named_series()
    test_movie_not_stripped()
    test_tmdb_id_path()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    sys.exit(1 if FAILED else 0)
