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


if __name__ == '__main__':
    print('任务列表终态展示快照')
    test_cache_isolated_by_save_path()
    test_terminal_cache_skips_aired_recalculation()
    print('结果：测试通过')
