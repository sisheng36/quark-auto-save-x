#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动编辑元数据时电影 TMDB 匹配的回归测试。"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
sys.path.insert(0, ROOT)

import run


class FakeCalendarDB:
    instances = []

    def __init__(self):
        self.shows = {}
        self.seasons = {}
        self.episodes = {}
        self.bindings = []
        self.unbindings = []
        FakeCalendarDB.instances.append(self)

    def get_show(self, tmdb_id):
        return self.shows.get(int(tmdb_id))

    def upsert_show(self, tmdb_id, name, year, status, poster_local_path,
                    latest_season_number, last_refreshed_at=0,
                    bound_task_names='', content_type='', is_custom_poster=0):
        self.shows[int(tmdb_id)] = {
            'tmdb_id': int(tmdb_id),
            'name': name,
            'year': year,
            'status': status,
            'poster_local_path': poster_local_path,
            'latest_season_number': latest_season_number,
            'bound_task_names': bound_task_names,
            'content_type': content_type,
            'is_custom_poster': is_custom_poster,
        }

    def upsert_season(self, tmdb_id, season_number, episode_count, refresh_url, season_name=''):
        self.seasons[(int(tmdb_id), int(season_number))] = {
            'episode_count': episode_count,
            'refresh_url': refresh_url,
            'season_name': season_name,
        }

    def upsert_episode(self, **kwargs):
        key = (int(kwargs['tmdb_id']), int(kwargs['season_number']), int(kwargs['episode_number']))
        self.episodes[key] = kwargs

    def update_episode_air_date_local(self, tmdb_id, season_number, episode_number, air_date_local):
        key = (int(tmdb_id), int(season_number), int(episode_number))
        self.episodes[key]['air_date_local'] = air_date_local

    def bind_task_and_content_type(self, tmdb_id, task_name, content_type):
        self.bindings.append((int(tmdb_id), task_name, content_type))
        show = self.shows[int(tmdb_id)]
        show['content_type'] = content_type
        show['bound_task_names'] = task_name

    def unbind_task_from_show(self, tmdb_id, task_name):
        self.unbindings.append((int(tmdb_id), task_name))

    def get_season(self, tmdb_id, season_number):
        return self.seasons.get((int(tmdb_id), int(season_number)))


class FakeTMDBService:
    instances = []

    def __init__(self, api_key, poster_language):
        self.movie_ids = []
        self.tv_ids = []
        FakeTMDBService.instances.append(self)

    def get_movie_details(self, movie_id):
        self.movie_ids.append(int(movie_id))
        return {
            'title': 'Example Movie',
            'original_title': 'Example Movie',
            'release_date': '2024-01-02',
            'overview': 'movie overview',
            'runtime': 120,
            'poster_path': '/poster.jpg',
        }

    def get_tv_show_details(self, tv_id):
        self.tv_ids.append(int(tv_id))
        return None

    def get_chinese_movie_title_with_fallback(self, movie_id, original_title=''):
        return '示例电影'

    def get_poster_path_with_language(self, media_id, media_type='tv'):
        assert media_type == 'movie'
        return ''


def check(name, actual, expected):
    if actual != expected:
        raise AssertionError(f'{name}: 期望 {expected!r}，实际 {actual!r}')
    print(f'  ✅ {name}')


def test_manual_movie_rematch_uses_movie_endpoint():
    original = {
        'CalendarDB': run.CalendarDB,
        'TMDBService': run.TMDBService,
        'is_login': run.is_login,
        'sync_task_config_with_database_bindings': run.sync_task_config_with_database_bindings,
        'notify_calendar_changed': run.notify_calendar_changed,
        'download_poster_local': run.download_poster_local,
        'config_data': run.config_data,
        'write_json': run.Config.write_json,
    }
    try:
        FakeCalendarDB.instances = []
        FakeTMDBService.instances = []
        task = {
            'taskname': '示例电影',
            'savepath': '/电影/示例电影',
            'calendar_info': {'match': {}, 'extracted': {}},
        }
        run.CalendarDB = FakeCalendarDB
        run.TMDBService = FakeTMDBService
        run.is_login = lambda: True
        run.sync_task_config_with_database_bindings = lambda: False
        run.notify_calendar_changed = lambda *args, **kwargs: None
        run.download_poster_local = lambda *args, **kwargs: ''
        run.Config.write_json = lambda *args, **kwargs: None
        run.config_data = {'tasklist': [task], 'tmdb_api_key': 'test-key'}

        response = run.app.test_client().post(
            '/api/calendar/edit_metadata',
            json={
                'task_name': '示例电影',
                'task_index': 0,
                'new_task_name': '示例电影',
                'new_content_type': 'movie',
                'new_tmdb_id': '12345',
            },
        )
        body = response.get_json()
        db = FakeCalendarDB.instances[0]
        service = FakeTMDBService.instances[-1]

        check('保存成功', body.get('success'), True)
        check('使用电影详情接口', service.movie_ids, [12345])
        check('不使用电视剧详情接口', service.tv_ids, [])
        check('电影内容类型', db.shows[12345]['content_type'], 'movie')
        check('电影虚拟季地址', db.seasons[(12345, 1)]['refresh_url'], '/movie/12345')
        check('电影虚拟集类型', db.episodes[(12345, 1, 1)]['ep_type'], 'movie')
        check('匹配媒体类型', task['calendar_info']['match']['media_type'], 'movie')
        check('响应内容类型', body.get('content_type'), 'movie')
    finally:
        run.CalendarDB = original['CalendarDB']
        run.TMDBService = original['TMDBService']
        run.is_login = original['is_login']
        run.sync_task_config_with_database_bindings = original['sync_task_config_with_database_bindings']
        run.notify_calendar_changed = original['notify_calendar_changed']
        run.download_poster_local = original['download_poster_local']
        run.config_data = original['config_data']
        run.Config.write_json = original['write_json']


def test_invalid_movie_does_not_unbind_old_match():
    class InvalidMovieService(FakeTMDBService):
        def get_movie_details(self, movie_id):
            self.movie_ids.append(int(movie_id))
            return None

    original = {
        'CalendarDB': run.CalendarDB,
        'TMDBService': run.TMDBService,
        'is_login': run.is_login,
        'config_data': run.config_data,
    }
    try:
        FakeCalendarDB.instances = []
        InvalidMovieService.instances = []
        task = {
            'taskname': '旧电影',
            'savepath': '/电影/旧电影',
            'content_type': 'movie',
            'calendar_info': {
                'match': {'tmdb_id': 10, 'media_type': 'movie'},
                'extracted': {'content_type': 'movie'},
            },
        }
        run.CalendarDB = FakeCalendarDB
        run.TMDBService = InvalidMovieService
        run.is_login = lambda: True
        run.config_data = {'tasklist': [task], 'tmdb_api_key': 'test-key'}

        response = run.app.test_client().post(
            '/api/calendar/edit_metadata',
            json={
                'task_name': '旧电影',
                'task_index': 0,
                'new_task_name': '旧电影',
                'new_content_type': 'movie',
                'new_tmdb_id': '99999',
            },
        )
        body = response.get_json()
        db = FakeCalendarDB.instances[0]
        check('无效电影 ID 返回失败', body.get('success'), False)
        check('无效电影不解绑旧匹配', db.unbindings, [])
    finally:
        run.CalendarDB = original['CalendarDB']
        run.TMDBService = original['TMDBService']
        run.is_login = original['is_login']
        run.config_data = original['config_data']


if __name__ == '__main__':
    print('手动电影 TMDB 匹配')
    test_manual_movie_rematch_uses_movie_endpoint()
    test_invalid_movie_does_not_unbind_old_match()
    print('结果：测试通过')
