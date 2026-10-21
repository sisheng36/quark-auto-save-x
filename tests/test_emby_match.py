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


def test_imdb_id_path():
    print("\n[9] IMDb ID 路径（豆瓣与 TMDB 译名不一致）")
    # 豆瓣叫「沙丘2」，Emby/TMDB 里叫「沙丘：第二部」，只有 IMDb 一致
    library = [movie_item(
        name="沙丘：第二部", original_title="Dune: Part Two",
        year="2024", provider_tmdb="693134", provider_imdb="tt15239678",
    )]
    by_imdb = match_one(library, {
        "title": "沙丘2",
        "year": "2024",
        "imdb_id": "tt15239678",
        "content_type": "movie",
        "media_type": "movie",
    })
    check("译名不同但 IMDb 一致 → 已入库", by_imdb.get("in_library"), True)
    check("IMDb 命中方式", by_imdb.get("match_by"), "imdb")
    check("IMDb 命中名称", by_imdb.get("matched_name"), "沙丘：第二部")

    # IMDb 大小写/前后空格应被规范化
    loose = match_one(library, {
        "title": "沙丘2", "year": "2024",
        "imdb_id": " TT15239678 ", "content_type": "movie",
    })
    check("IMDb 大小写与空格规范化", loose.get("in_library"), True)

    # 豆瓣没有 IMDb 时回落到标题匹配
    fallback = match_one(library, {
        "title": "沙丘：第二部", "year": "2024", "content_type": "movie",
    })
    check("无 IMDb 回落标题匹配", fallback.get("in_library"), True)
    check("标题命中方式", fallback.get("match_by"), "title")


def test_imdb_conflict():
    print("\n[10] 同名不同片：IMDb 冲突时不能误判已入库")
    library = [movie_item(
        name="沙丘", original_title="Dune",
        year="1984", provider_imdb="tt0087182",
    )]
    conflict = match_one(library, {
        "title": "沙丘", "year": "1984",
        "imdb_id": "tt1160419",   # 2021 版
        "content_type": "movie",
    })
    check("IMDb 不同 → 未入库", conflict.get("in_library"), False)

    # Emby 侧没有 IMDb 时，标题命中仍然算已入库（不能因为缺信息就误报红）
    library_no_imdb = [movie_item(name="沙丘", original_title="Dune", year="1984", provider_imdb="")]
    allowed = match_one(library_no_imdb, {
        "title": "沙丘", "year": "1984", "imdb_id": "tt1160419", "content_type": "movie",
    })
    check("Emby 无 IMDb → 标题命中已入库", allowed.get("in_library"), True)


def test_imdb_tv_season():
    print("\n[11] 剧集 IMDb 命中后仍比对季数")
    library = [silo_series(provider_imdb="tt14688458")]
    s3 = match_one(library, {
        "title": "末日地堡 第三季", "year": "2025",
        "imdb_id": "tt14688458", "content_type": "tv",
    })
    check("IMDb 命中 + 第三季在库", s3.get("in_library"), True)
    check("IMDb 命中季列表", s3.get("seasons"), "1,2,3")

    s5 = match_one(library, {
        "title": "末日地堡 第五季", "year": "2027",
        "imdb_id": "tt14688458", "content_type": "tv",
    })
    check("IMDb 命中但第五季未入库", s5.get("in_library"), False)

    # 剧集类型偏好：Series 优先于同 IMDb 的 Movie 条目
    mixed = [movie_item(provider_imdb="tt14688458"), silo_series(provider_imdb="tt14688458")]
    tv_hit = match_one(mixed, {
        "title": "末日地堡", "year": "2023", "imdb_id": "tt14688458", "content_type": "tv",
    })
    check("剧集命中 Series 而非 Movie", tv_hit.get("matched_name"), "末日地堡")
    movie_hit = match_one(mixed, {
        "title": "末日地堡", "year": "2023", "imdb_id": "tt14688458", "content_type": "movie",
    })
    check("电影命中 Movie", movie_hit.get("matched_name"), "沙丘")


if __name__ == "__main__":
    test_split_season_suffix()
    test_chinese_numeral()
    test_silo_season_cards()
    test_english_season_titles()
    test_empty_season_numbers()
    test_exact_season_named_series()
    test_movie_not_stripped()
    test_tmdb_id_path()
    test_imdb_id_path()
    test_imdb_conflict()
    test_imdb_tv_season()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    sys.exit(1 if FAILED else 0)
