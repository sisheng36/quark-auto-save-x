#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务列表终态展示快照回归测试。"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
sys.path.insert(0, ROOT)

import run
from sdk.db import CalendarDB


def check(name, actual, expected):
    if actual != expected:
        raise AssertionError(f'{name}: 期望 {expected!r}，实际 {actual!r}')
    print(f'  ✅ {name}')


class EmptyRecordCursor:
    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []


class EmptyRecordConnection:
    def cursor(self):
        return EmptyRecordCursor()


class EmptyRecordDB:
    conn = EmptyRecordConnection()

    def close(self):
        return None


def test_cache_isolated_by_save_path():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = CalendarDB(os.path.join(temp_dir, 'data.db'))
        db.upsert_task_display_cache(
            '同名任务',
            '/影视/第一季',
            tmdb_id=42,
            season_number=1,
            content_type='tv',
            matched_status='本季终',
            total_count=6,
            aired_count=6,
            is_terminal=True,
            terminal_reason='season_final',
            source_version='v1',
            finalized_at=1,
            updated_at=1,
        )
        first = db.get_task_display_cache('同名任务', '/影视/第一季')
        second = db.get_task_display_cache('同名任务', '/影视/第二季')
        check('第一季快照存在', first.get('matched_status'), '本季终')
        check('第二季不会串用快照', second, None)
        db.close()


def test_terminal_cache_skips_aired_recalculation():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = CalendarDB(os.path.join(temp_dir, 'data.db'))
        db.upsert_show(42, '书虫侦探', '2024', 'returning_series', '', 1, 0, '书虫侦探', 'tv')
        db.upsert_season(42, 1, 6, '/tv/42/season/1', '第一季')
        source_version = run._task_display_source_version(42, 1, 'tv', 'returning_series', 6, '第一季')
        db.upsert_task_display_cache(
            '书虫侦探',
            '/影视/书虫侦探/第一季',
            tmdb_id=42,
            season_number=1,
            content_type='tv',
            matched_show_name='书虫侦探',
            matched_year='2024',
            latest_season_name='第一季',
            matched_status='本季终',
            total_count=6,
            aired_count=6,
            is_terminal=True,
            terminal_reason='season_final',
            source_version=source_version,
            finalized_at=1,
            updated_at=1,
        )

        originals = {
            'CalendarDB': run.CalendarDB,
            'RecordDB': run.RecordDB,
            'config_data': run.config_data,
            'compute_aired_count_by_episode_check': run.compute_aired_count_by_episode_check,
        }
        try:
            run.CalendarDB = lambda: db
            run.RecordDB = lambda: EmptyRecordDB()
            run.config_data = {'performance': {}}

            def fail_if_recalculated(*args, **kwargs):
                raise AssertionError('终态快照命中后不应重新计算已播集数')

            run.compute_aired_count_by_episode_check = fail_if_recalculated
            result = run.enrich_tasks_with_calendar_meta([
                {
                    'task_name': '书虫侦探',
                    'save_path': '/影视/书虫侦探/第一季',
                    'content_type': 'tv',
                    'match_tmdb_id': 42,
                    'matched_latest_season_number': 1,
                    'matched_show_name': '书虫侦探',
                    'matched_year': '2024',
                }
            ])[0]
            check('命中本季终快照', result.get('matched_status'), '本季终')
            check('快照总集数', result['season_counts']['total_count'], 6)
            check('快照已播集数', result['season_counts']['aired_count'], 6)
        finally:
            run.CalendarDB = originals['CalendarDB']
            run.RecordDB = originals['RecordDB']
            run.config_data = originals['config_data']
            run.compute_aired_count_by_episode_check = originals['compute_aired_count_by_episode_check']
            db.close()


def test_provisional_count_does_not_end_task():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = CalendarDB(os.path.join(temp_dir, 'data.db'))
        db.upsert_show(43, '假面骑士麦斯', '2025', '播出中', '', 1, 0, '假面骑士麦斯', 'tv')
        db.upsert_season(43, 1, 4, '/tv/43/season/1', '第一季')

        originals = {
            'CalendarDB': run.CalendarDB,
            'RecordDB': run.RecordDB,
            'config_data': run.config_data,
            'compute_aired_count_by_episode_check': run.compute_aired_count_by_episode_check,
        }
        try:
            run.CalendarDB = lambda: db
            run.RecordDB = lambda: EmptyRecordDB()
            run.config_data = {'performance': {}}
            run.compute_aired_count_by_episode_check = lambda *args, **kwargs: 4
            result = run.enrich_tasks_with_calendar_meta([
                {
                    'task_name': '假面骑士麦斯',
                    'save_path': '/影视/假面骑士麦斯/第一季',
                    'content_type': 'tv',
                    'match_tmdb_id': 43,
                    'matched_latest_season_number': 1,
                    'matched_show_name': '假面骑士麦斯',
                    'matched_year': '2025',
                }
            ])[0]
            check('未知后续集时仍为更新中', result.get('matched_status'), '播出中')
            check('未知后续集时不是终态', result.get('is_terminal'), False)
            check('未知后续集时继续刷新', result.get('refresh_enabled'), True)
            check('已知集数标记为临时', result['season_counts'].get('is_count_provisional'), True)
            check('已知集数保留为4', result['season_counts'].get('total_count'), 4)
        finally:
            run.CalendarDB = originals['CalendarDB']
            run.RecordDB = originals['RecordDB']
            run.config_data = originals['config_data']
            run.compute_aired_count_by_episode_check = originals['compute_aired_count_by_episode_check']
            db.close()


def test_manual_ended_task_skips_aired_recalculation():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = CalendarDB(os.path.join(temp_dir, 'data.db'))
        db.upsert_show(44, '手动完结剧', '2025', '播出中', '', 1, 0, '手动完结剧', 'tv')
        db.upsert_season(44, 1, 4, '/tv/44/season/1', '第一季')
        db.upsert_task_status_override(
            '手动完结剧',
            '/影视/手动完结剧/第一季',
            tmdb_id=44,
            season_number=1,
            status_override='ended',
            updated_at=1,
        )

        originals = {
            'CalendarDB': run.CalendarDB,
            'RecordDB': run.RecordDB,
            'config_data': run.config_data,
            'compute_aired_count_by_episode_check': run.compute_aired_count_by_episode_check,
            'is_login': run.is_login,
            'notify_calendar_changed': run.notify_calendar_changed,
            'invalidate_task_display_cache': run.invalidate_task_display_cache,
        }
        try:
            run.CalendarDB = lambda: db
            run.RecordDB = lambda: EmptyRecordDB()
            run.config_data = {'performance': {}}

            def fail_if_recalculated(*args, **kwargs):
                raise AssertionError('手动完结任务不应重新计算已播集数')

            run.compute_aired_count_by_episode_check = fail_if_recalculated
            result = run.enrich_tasks_with_calendar_meta([
                {
                    'task_name': '手动完结剧',
                    'save_path': '/影视/手动完结剧/第一季',
                    'content_type': 'tv',
                    'match_tmdb_id': 44,
                    'matched_latest_season_number': 1,
                    'matched_show_name': '手动完结剧',
                    'matched_year': '2025',
                }
            ])[0]
            check('手动状态显示已完结', result.get('matched_status'), '已完结')
            check('手动状态进入终态', result.get('is_terminal'), True)
            check('手动状态关闭刷新', result.get('refresh_enabled'), False)
            check('手动状态来源', result.get('status_source'), 'manual')
            check('手动状态写入展示数据', result['season_counts'].get('manual_status'), 'ended')

            # 通过实际 Flask 路由验证“标记已完结 / 恢复自动判断”。
            route_task = {
                'task_name': '手动完结剧',
                'save_path': '/影视/手动完结剧/第一季',
                'calendar_info': {'match': {'tmdb_id': 44, 'latest_season_number': 1}},
            }
            run.config_data = {'tasklist': [route_task], 'performance': {}}
            run.is_login = lambda: True
            run.notify_calendar_changed = lambda *args, **kwargs: None
            run.invalidate_task_display_cache = lambda *args, **kwargs: None
            client = run.app.test_client()
            response = client.post(
                '/api/calendar/task_status_override',
                json={'task_name': '手动完结剧', 'task_index': 0, 'status': None},
            )
            check('状态接口恢复自动判断', response.get_json().get('success'), True)
            check('恢复后没有手动状态', db.get_task_status_override('手动完结剧', '/影视/手动完结剧/第一季'), None)
            response = client.post(
                '/api/calendar/task_status_override',
                json={'task_name': '手动完结剧', 'task_index': 0, 'status': 'ended'},
            )
            check('状态接口标记已完结', response.get_json().get('success'), True)
            check('接口写入手动状态', db.get_task_status_override('手动完结剧', '/影视/手动完结剧/第一季').get('status_override'), 'ended')
        finally:
            run.CalendarDB = originals['CalendarDB']
            run.RecordDB = originals['RecordDB']
            run.config_data = originals['config_data']
            run.compute_aired_count_by_episode_check = originals['compute_aired_count_by_episode_check']
            run.is_login = originals['is_login']
            run.notify_calendar_changed = originals['notify_calendar_changed']
            run.invalidate_task_display_cache = originals['invalidate_task_display_cache']
            db.close()


def test_auto_refresh_updates_known_episode_count_and_skips_manual_task():
    class FakeTMDBService:
        def __init__(self, *args, **kwargs):
            pass

        def get_tv_show_episodes(self, tmdb_id, season_number):
            return {
                'name': '第一季',
                'episodes': [
                    {
                        'episode_number': number,
                        'name': f'第{number}集',
                        'overview': '',
                        'air_date': f'2025-10-{number:02d}',
                        'runtime': 45,
                        'episode_type': 'standard',
                    }
                    for number in range(1, 6)
                ],
            }

        def get_tv_show_details(self, tmdb_id):
            return {'status': 'returning_series'}

        def process_season_name(self, name):
            return name

    with tempfile.TemporaryDirectory() as temp_dir:
        db = CalendarDB(os.path.join(temp_dir, 'data.db'))
        db.upsert_show(45, '自动追踪剧', '2025', '播出中', '', 1, 0, '自动追踪剧', 'tv')
        db.upsert_season(45, 1, 4, '/tv/45/season/1', '第一季')

        originals = {
            'CalendarDB': run.CalendarDB,
            'TMDBService': run.TMDBService,
            'config_data': run.config_data,
            'notify_calendar_changed': run.notify_calendar_changed,
            '_trigger_airtime_reschedule': run._trigger_airtime_reschedule,
            'set_calendar_last_full_refresh_at': run.set_calendar_last_full_refresh_at,
        }
        task = {
            'task_name': '自动追踪剧',
            'save_path': '/影视/自动追踪剧/第一季',
            'calendar_info': {
                'match': {
                    'tmdb_id': 45,
                    'latest_season_number': 1,
                },
            },
        }
        try:
            run.CalendarDB = lambda: db
            run.TMDBService = FakeTMDBService
            run.config_data = {'tmdb_api_key': 'test', 'tasklist': [task], 'performance': {}}
            run.notify_calendar_changed = lambda *args, **kwargs: None
            run._trigger_airtime_reschedule = lambda *args, **kwargs: None
            run.set_calendar_last_full_refresh_at = lambda *args, **kwargs: None
            run.run_calendar_refresh_all_internal()
            refreshed = db.get_season(45, 1)
            check('自动刷新发现第5集', refreshed.get('episode_count'), 5)

            db.upsert_season(45, 1, 4, '/tv/45/season/1', '第一季')
            db.upsert_task_status_override(
                '自动追踪剧',
                '/影视/自动追踪剧/第一季',
                tmdb_id=45,
                season_number=1,
                status_override='ended',
                updated_at=1,
            )
            run.run_calendar_refresh_all_internal()
            skipped = db.get_season(45, 1)
            check('手动完结任务跳过自动刷新', skipped.get('episode_count'), 4)
        finally:
            run.CalendarDB = originals['CalendarDB']
            run.TMDBService = originals['TMDBService']
            run.config_data = originals['config_data']
            run.notify_calendar_changed = originals['notify_calendar_changed']
            run._trigger_airtime_reschedule = originals['_trigger_airtime_reschedule']
            run.set_calendar_last_full_refresh_at = originals['set_calendar_last_full_refresh_at']
            db.close()


if __name__ == '__main__':
    print('任务列表终态展示快照')
    test_cache_isolated_by_save_path()
    test_terminal_cache_skips_aired_recalculation()
    test_provisional_count_does_not_end_task()
    test_manual_ended_task_skips_aired_recalculation()
    test_auto_refresh_updates_known_episode_count_and_skips_manual_task()
    print('结果：测试通过')
