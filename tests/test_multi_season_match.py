#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一部剧多季任务的季号回归测试。不访问 TMDB。

运行：python3 tests/test_multi_season_match.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
sys.path.insert(0, ROOT)

from sdk.db import CalendarDB, normalize_save_path, save_path_matches
from utils.season_match import (
    binding_sync_should_overwrite_season,
    choose_match_season,
    correct_stored_season,
    display_season_for_task,
    resolve_task_for_edit,
    season_when_filling_binding,
    show_latest_season_number,
    stored_match_season,
)
from utils.task_extractor import TaskExtractor

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


def task(name, savepath='', season=None, tmdb_id=None, manual=False, replace=''):
    item = {
        'taskname': name,
        'savepath': savepath,
        'replace': replace,
        'calendar_info': {'match': {}},
    }
    if tmdb_id:
        item['calendar_info']['match']['tmdb_id'] = tmdb_id
    if season:
        item['calendar_info']['match']['latest_season_number'] = season
    if manual:
        item['calendar_info']['user_manual_season'] = True
    return item


def test_extract_season():
    print("季号提取")
    extractor = TaskExtractor()
    check("任务名 第一季", extractor.extract_season_number_from_text("书虫侦探 第一季"), 1)
    check("任务名 第1季", extractor.extract_season_number_from_text("书虫侦探 第1季"), 1)
    check("任务名 第二季", extractor.extract_season_number_from_text("书虫侦探 第二季"), 2)
    check("Season 1", extractor.extract_season_number_from_text("Bookworm Season 1"), 1)
    check("S01", extractor.extract_season_number_from_text("书虫侦探 S01"), 1)
    check("S01E{}", extractor.extract_season_number_from_text("书虫侦探.S01E{}"), 1)
    check("第1集不是季", extractor.extract_season_number_from_text("书虫侦探 第1集"), None)
    check(
        "路径 第一季",
        extractor.extract_season_number_from_path("/影视/书虫侦探/第一季"),
        1,
    )
    check(
        "路径靠后的季优先",
        extractor.extract_season_number_from_path("/影视/第二季/书虫侦探/第一季"),
        1,
    )
    check(
        "任务名优先于路径",
        extractor.extract_season_number_from_task({
            'taskname': '书虫侦探 第二季',
            'savepath': '/影视/书虫侦探/第一季',
        }),
        2,
    )
    check(
        "路径补任务名",
        extractor.extract_season_number_from_task({
            'taskname': '书虫侦探',
            'savepath': '/影视/书虫侦探/第一季',
            'replace': 'S02E{}',
        }),
        1,
    )
    check(
        "模板补季号",
        extractor.extract_season_number_from_task({
            'taskname': '书虫侦探',
            'savepath': '/影视/书虫侦探',
            'replace': '书虫侦探.S01E{}',
        }),
        1,
    )


def test_choose_and_correct():
    print("季号判定")
    seasons = [
        {'season_number': 1, 'air_date': '2024-01-01'},
        {'season_number': 2, 'air_date': '2025-01-01'},
    ]
    season_one = task('书虫侦探 第一季', season=2, tmdb_id=42)
    season_two = task('书虫侦探 第二季', season=2, tmdb_id=42)
    check("自动匹配用提取季而不是最新已播季", choose_match_season(season_one, 2), 1)
    check("第二季任务保持 2", choose_match_season(season_two, 2), 2)
    check("没有季标记时用最新已播季", choose_match_season(task('书虫侦探', tmdb_id=42), 2), 2)
    check("纠正第一季", correct_stored_season(season_one), True)
    check("纠正后季号是 1", season_one['calendar_info']['match']['latest_season_number'], 1)
    check("第二季不需要纠正", correct_stored_season(season_two), False)
    check("第二季仍是 2", season_two['calendar_info']['match']['latest_season_number'], 2)
    manual = task('书虫侦探 第一季', season=2, tmdb_id=42, manual=True)
    check("手动季不被纠正", correct_stored_season(manual), False)
    check("手动季保持 2", manual['calendar_info']['match']['latest_season_number'], 2)
    check("展示优先提取季", display_season_for_task(task('书虫侦探 第一季', season=2, tmdb_id=42), 2), 1)
    check("展示尊重手动季", display_season_for_task(manual, 1), 2)
    check("没有已播季数据时仍能选提取季", choose_match_season(task('书虫侦探 第一季'), None), 1)
    # seasons 参数只是说明夹具，避免未使用告警
    assert seasons[1]['season_number'] == 2


def test_sync_does_not_copy_show_latest():
    print("同步不覆盖任务季")
    season_one = task('书虫侦探 第一季', season=1, tmdb_id=42)
    check("同一 TMDB 不覆盖季号", binding_sync_should_overwrite_season(42, 42), False)
    check("不同 TMDB 才允许改绑定", binding_sync_should_overwrite_season(42, 99), True)
    check(
        "补绑定时第一季不用节目最新季",
        season_when_filling_binding(season_one, 2),
        1,
    )
    check(
        "无标记任务才回退到节目最新季",
        season_when_filling_binding(task('书虫侦探'), 2),
        2,
    )
    check(
        "节目表季号取各任务较大值",
        show_latest_season_number([season_one, task('书虫侦探 第二季', season=2, tmdb_id=42)], 42, 1),
        2,
    )


def test_extract_keeps_duplicate_task_index():
    print("同名任务保留索引")
    extractor = TaskExtractor()
    tasks = [
        task('书虫侦探', '/影视/书虫侦探/第一季', season=1, tmdb_id=42),
        task('书虫侦探', '/影视/书虫侦探/第二季', season=2, tmdb_id=42),
    ]
    infos = extractor.extract_all_tasks_info(tasks, {})
    check("两个同名任务都提取", len(infos), 2)
    check("第一个索引 0", infos[0].get('task_index'), 0)
    check("第二个索引 1", infos[1].get('task_index'), 1)
    check("第一个路径季", extractor.extract_season_number_from_task(tasks[0]), 1)
    check("第二个路径季", extractor.extract_season_number_from_task(tasks[1]), 2)


def test_resolve_duplicate_task_name():
    print("同名任务编辑定位")
    tasks = [
        task('书虫侦探', '/影视/书虫侦探/第一季', season=1, tmdb_id=42),
        task('书虫侦探', '/影视/书虫侦探/第二季', season=2, tmdb_id=42),
        task('别的剧', season=1, tmdb_id=1),
    ]
    found, err = resolve_task_for_edit(tasks, '书虫侦探', 1)
    check("按索引定位第二季", stored_match_season(found), 2)
    check("按索引无错误", err, None)
    found0, err0 = resolve_task_for_edit(tasks, '书虫侦探', 0)
    check("按索引定位第一季", stored_match_season(found0), 1)
    check("第一季无错误", err0, None)
    missing, err_dup = resolve_task_for_edit(tasks, '书虫侦探')
    check("同名无索引失败", missing, None)
    check("同名无索引提示", err_dup, '存在同名任务，无法唯一定位')
    unique, err_ok = resolve_task_for_edit(tasks, '别的剧')
    check("单任务名仍可用", stored_match_season(unique), 1)
    check("单任务名无错误", err_ok, None)
    mismatch, err_mis = resolve_task_for_edit(tasks, '别的剧', 0)
    check("索引与名称不一致失败", mismatch, None)
    check("索引与名称不一致提示", err_mis, '任务已变化，请刷新后重试')


def test_duplicate_task_transfer_metrics_are_isolated():
    print("同名任务转存进度隔离")
    with tempfile.TemporaryDirectory() as tmp:
        db = CalendarDB(os.path.join(tmp, 'calendar.db'))
        db.upsert_season_metrics(42, 1, 6, 6, 6, 100, 1)
        db.upsert_season_metrics(42, 2, 0, 0, 8, 0, 1)
        db.upsert_task_metrics('书虫侦探', 42, 1, 6, 100, 1, save_path='/影视/书虫侦探/第一季')
        db.upsert_task_metrics('书虫侦探', 42, 2, 0, 0, 1, save_path='/影视/书虫侦探/第二季')
        first = db.get_task_metrics('书虫侦探', '/影视/书虫侦探/第一季')
        second = db.get_task_metrics('书虫侦探', '/影视/书虫侦探/第二季')
        check("第一季按路径读取 6 集", first.get('transferred_count'), 6)
        check("第二季按路径读取 0 集", second.get('transferred_count'), 0)
        check("第一季总集数独立", first.get('total_count'), 6)
        check("第二季总集数独立", second.get('total_count'), 8)
        check("路径规范化", normalize_save_path('影视//书虫侦探/第一季/'), '/影视/书虫侦探/第一季')
        check("子目录归属", save_path_matches('/影视/书虫侦探/第一季/特别篇', '/影视/书虫侦探/第一季'), True)
        check("相邻季不串计", save_path_matches('/影视/书虫侦探/第二季', '/影视/书虫侦探/第一季'), False)
        db.close()


def test_duplicate_task_latest_files_are_isolated():
    print("同名任务最新文件隔离")
    extractor = TaskExtractor()
    tasks = [
        task('书虫侦探', '/影视/书虫侦探/第一季', season=1, tmdb_id=42),
        task('书虫侦探', '/影视/书虫侦探/第二季', season=2, tmdb_id=42),
    ]
    infos = extractor.extract_all_tasks_info(
        tasks,
        {
            '/影视/书虫侦探/第一季': 'S01E06',
            '/影视/书虫侦探/第二季': 'S02E01',
        },
    )
    check("第一季最新文件独立", infos[0].get('latest_file'), 'S01E06')
    check("第二季最新文件独立", infos[1].get('latest_file'), 'S02E01')
    check("第一季集数不串计", infos[0].get('episode_number'), 6)
    check("第二季集数不串计", infos[1].get('episode_number'), 1)


def test_database_binding_and_purge():
    print("精确绑定与清理")
    with tempfile.TemporaryDirectory() as tmp:
        db = CalendarDB(os.path.join(tmp, 'data.db'))
        db.upsert_show(42, '书虫侦探', '2024', '播出中', '', 2, 0, '', 'tv')
        db.bind_task_to_show(42, '书虫侦探 第二季')
        db.bind_task_to_show(42, '书虫侦探 第一季')
        check("子串任务名不能命中第二季", db.get_show_by_task_name('书虫侦探'), None)
        second = db.get_show_by_task_name('书虫侦探 第二季')
        first = db.get_show_by_task_name('书虫侦探 第一季')
        check("第二季精确命中", (second or {}).get('tmdb_id'), 42)
        check("第一季精确命中", (first or {}).get('tmdb_id'), 42)

        db.upsert_season(42, 1, 8, '/tv/42/season/1', '第一季')
        db.upsert_season(42, 2, 8, '/tv/42/season/2', '第二季')
        db.upsert_episode(42, 1, 1, '第一集', '', '2024-01-01', 20, '', 1)
        db.upsert_episode(42, 2, 1, '第一集', '', '2025-01-01', 20, '', 1)
        db.upsert_season_metrics(42, 1, 0, 1, 8, 0, 1)
        db.upsert_season_metrics(42, 2, 0, 1, 8, 0, 1)

        db.purge_seasons_not_in(42, [])
        check("空保留列表不删除第一季", (db.get_season(42, 1) or {}).get('season_name'), '第一季')
        check("空保留列表不删除第二季", (db.get_season(42, 2) or {}).get('season_name'), '第二季')

        db.purge_seasons_not_in(42, [1, 2])
        check("两季都被引用时第一季保留", (db.get_season(42, 1) or {}).get('season_name'), '第一季')
        check("两季都被引用时第二季保留", (db.get_season(42, 2) or {}).get('season_name'), '第二季')

        db.purge_seasons_not_in(42, [1])
        check("不再引用的第二季被删除", db.get_season(42, 2), None)
        check("仍引用的第一季保留", (db.get_season(42, 1) or {}).get('season_name'), '第一季')
        check("第二季指标一并删除", db.get_season_metrics(42, 2), None)
        db.close()


def main():
    test_extract_season()
    test_choose_and_correct()
    test_sync_does_not_copy_show_latest()
    test_extract_keeps_duplicate_task_index()
    test_resolve_duplicate_task_name()
    test_duplicate_task_transfer_metrics_are_isolated()
    test_duplicate_task_latest_files_are_isolated()
    test_database_binding_and_purge()
    print(f"\n通过 {PASSED}，失败 {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
