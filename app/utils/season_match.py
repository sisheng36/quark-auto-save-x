#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务季号判定。

同一部剧的多个任务共用一个 TMDB ID。季号必须记在任务上，不能用节目表里
唯一的 latest_season_number 代表每一个任务。
"""

from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from utils.task_extractor import TaskExtractor


def task_has_manual_season(task: Optional[Dict]) -> bool:
    cal = (task or {}).get('calendar_info') or {}
    return bool(cal.get('user_manual_season'))


def stored_match_season(task: Optional[Dict]) -> Optional[int]:
    match = ((task or {}).get('calendar_info') or {}).get('match') or {}
    return _positive_int(match.get('latest_season_number'))


def pick_latest_aired_season_number(seasons: Optional[Sequence[Dict]], today: Optional[date] = None) -> int:
    """已播出季里播出日期最新的季号。没有则返回 0，由调用方决定是否回退到第 1 季。"""
    today = today or date.today()
    latest_number = 0
    latest_air = None
    for season in seasons or []:
        if not isinstance(season, dict):
            continue
        number = _positive_int(season.get('season_number'))
        air_date_text = season.get('air_date') or ''
        if not number or not air_date_text:
            continue
        try:
            air_date = datetime.strptime(str(air_date_text)[:10], '%Y-%m-%d').date()
        except ValueError:
            continue
        if air_date <= today and (latest_air is None or air_date > latest_air):
            latest_number = number
            latest_air = air_date
    return latest_number


def display_season_for_task(task: Optional[Dict], effective_latest=None) -> Optional[int]:
    """展示季号：手动锁定季 > 任务名/路径/模板提取的季 > 已保存季 > 最新已播季。"""
    if task_has_manual_season(task):
        stored = stored_match_season(task)
        if stored:
            return stored
    inferred = TaskExtractor().extract_season_number_from_task(task or {})
    if inferred:
        return int(inferred)
    stored = stored_match_season(task)
    if stored:
        return stored
    return _positive_int(effective_latest)


def choose_match_season(task: Optional[Dict], latest_aired_season=None) -> int:
    """手动季 > 任务名/路径/模板提取的季 > 最新已播季 > 已保存季 > 1。"""
    if task_has_manual_season(task):
        stored = stored_match_season(task)
        if stored:
            return stored
    inferred = TaskExtractor().extract_season_number_from_task(task or {})
    if inferred:
        return int(inferred)
    aired = _positive_int(latest_aired_season)
    if aired:
        return aired
    stored = stored_match_season(task)
    if stored:
        return stored
    return 1


def correct_stored_season(task: Optional[Dict]) -> bool:
    """
    名称或路径能提取出季号、且用户没有手动锁定时，把错误的最新季改回该季。

    只改已有 TMDB 匹配的任务，不在这里新建匹配。
    """
    if not isinstance(task, dict) or task_has_manual_season(task):
        return False
    inferred = TaskExtractor().extract_season_number_from_task(task)
    if not inferred:
        return False
    cal = task.get('calendar_info') or {}
    match = dict(cal.get('match') or {})
    tmdb_id = _positive_int(match.get('tmdb_id') or cal.get('tmdb_id'))
    if not tmdb_id:
        return False
    if stored_match_season(task) == int(inferred):
        return False
    match['tmdb_id'] = tmdb_id
    match['latest_season_number'] = int(inferred)
    match['latest_season_fetch_url'] = f"/tv/{tmdb_id}/season/{int(inferred)}"
    cal = dict(cal)
    cal['match'] = match
    task['calendar_info'] = cal
    return True


def collect_referenced_seasons(tasks: Optional[Iterable[Dict]]) -> List[Tuple[int, int]]:
    """当前任务仍在使用的 (tmdb_id, season) 。清理季数据时这些季必须保留。"""
    pairs = []
    seen = set()
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        match = ((task.get('calendar_info') or {}).get('match') or {})
        tmdb_id = _positive_int(match.get('tmdb_id') or (task.get('calendar_info') or {}).get('tmdb_id'))
        season = stored_match_season(task)
        if not tmdb_id or not season:
            continue
        key = (tmdb_id, season)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


def show_latest_season_number(tasks: Optional[Iterable[Dict]], tmdb_id, candidate=None) -> int:
    """节目表只能存一个季号时，保留该节目各任务季号里的较大值，供旧逻辑兼容。"""
    target_id = _positive_int(tmdb_id)
    seasons = []
    candidate_season = _positive_int(candidate)
    if candidate_season:
        seasons.append(candidate_season)
    if target_id:
        for show_id, season in collect_referenced_seasons(tasks):
            if show_id == target_id:
                seasons.append(season)
    return max(seasons) if seasons else 1


def binding_sync_should_overwrite_season(config_tmdb_id, db_tmdb_id) -> bool:
    """配置和数据库已经指向同一节目时，不能用节目级最新季覆盖任务季号。"""
    config_id = _positive_int(config_tmdb_id)
    db_id = _positive_int(db_tmdb_id)
    if config_id and db_id and config_id == db_id:
        return False
    return True


def season_when_filling_binding(task: Optional[Dict], show_latest_season) -> int:
    """从数据库补绑定时，仍优先任务自己的季，而不是节目最新季。"""
    if task_has_manual_season(task):
        stored = stored_match_season(task)
        if stored:
            return stored
    inferred = TaskExtractor().extract_season_number_from_task(task or {})
    if inferred:
        return int(inferred)
    show_season = _positive_int(show_latest_season)
    if show_season:
        return show_season
    return stored_match_season(task) or 1


def _positive_int(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number
