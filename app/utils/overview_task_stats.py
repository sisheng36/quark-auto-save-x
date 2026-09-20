# -*- coding: utf-8 -*-
"""总览页任务统计：类型/追更中/今日加入/待处理/状态分布。

纯函数，便于单测。日历元数据、完成判定由调用方预计算后传入。
"""

SERIES_CONTENT_TYPES = ("tv", "anime", "variety", "documentary")
CONTENT_TYPE_COUNT_KEYS = {
    "tv": "tv_count",
    "anime": "anime_count",
    "documentary": "documentary_count",
    "variety": "variety_count",
    "movie": "movie_count",
}
FINAL_STATUSES = ("本季终", "已完结", "已取消", "已上映")
KNOWN_FORMATTED_BANS = (
    "该分享已失效，不可访问",
    "该分享已过期，无法访问",
    "该分享已被删除，无法访问",
    "该分享已被取消，无法访问",
    "分享不存在",
)
_TMDB_STATUS_CN = {
    "returning_series": "播出中",
    "in_production": "制作中",
    "planned": "计划中",
    "ended": "已完结",
    "canceled": "已取消",
    "cancelled": "已取消",
    "pilot": "试播集",
    "rumored": "待确认",
    "released": "已上映",
}


def empty_overview_task_stats():
    return {
        "tv_count": 0,
        "anime_count": 0,
        "documentary_count": 0,
        "variety_count": 0,
        "movie_count": 0,
        "other_count": 0,
        "ongoing_count": 0,
        "today_count": 0,
        "failed_count": 0,
        "status_completed": 0,
        "status_airing": 0,
        "status_finale": 0,
        "status_ended": 0,
        "status_unmatched": 0,
        "failed_tasks": [],
    }


def task_display_name(task):
    if not task:
        return ""
    return str(task.get("taskname") or task.get("task_name") or "").strip()


def is_recoverable_share_error(message):
    if not message:
        return False
    text = str(message)
    return (
        "inner error" in text
        or "request error" in text
        or "网络错误" in text
        or "服务端错误" in text
        or "临时错误" in text
    )


def format_shareurl_ban_message(message):
    if not message:
        return message
    text = str(message)
    if is_recoverable_share_error(text):
        return None
    if (
        "分享者用户封禁链接查看受限" in text
        or "文件涉及违规内容" in text
        or "分享地址已失效" in text
        or "文件不存在" in text
    ):
        return "该分享已失效，不可访问"
    if "好友已取消了分享" in text:
        return "该分享已被取消，无法访问"
    if "文件已被分享者删除" in text or text == "文件已被分享者删除或文件夹为空":
        return "该分享已被删除，无法访问"
    if "分享地址已过期" in text:
        return "该分享已过期，无法访问"
    return text


def should_count_shareurl_ban(message):
    if not message or not str(message).strip():
        return False
    if is_recoverable_share_error(message):
        return False
    return True


def localize_show_status(raw_status, is_season_finale=False, aired=0, total=0):
    if not raw_status:
        return ""
    text = str(raw_status).strip()
    if not text:
        return ""
    if text in (
        "播出中",
        "本季终",
        "已完结",
        "已取消",
        "已上映",
        "制作中",
        "计划中",
        "电影",
        "试播集",
        "待确认",
    ):
        return text
    key = text.lower().replace(" ", "_")
    if key == "returning_series":
        try:
            aired_i = int(aired or 0)
            total_i = int(total or 0)
        except (TypeError, ValueError):
            aired_i, total_i = 0, 0
        if is_season_finale and total_i > 0 and aired_i >= total_i:
            return "本季终"
        return "播出中"
    return _TMDB_STATUS_CN.get(key, text)


def resolve_content_type(task, calendar_task=None):
    if not task:
        return "other"
    if task.get("content_type"):
        return task.get("content_type")
    extracted = ((task.get("calendar_info") or {}).get("extracted") or {})
    if extracted.get("content_type"):
        return extracted.get("content_type")
    if calendar_task and calendar_task.get("content_type"):
        return calendar_task.get("content_type")
    return "other"


def resolve_task_status(task, calendar_task=None):
    candidates = [
        calendar_task.get("matched_status") if calendar_task else None,
        calendar_task.get("status") if calendar_task else None,
        task.get("matched_status") if task else None,
        task.get("status") if task else None,
        ((task.get("calendar_info") or {}).get("match") or {}).get("status") if task else None,
        ((task.get("calendar_info") or {}).get("extracted") or {}).get("status") if task else None,
    ]
    for val in candidates:
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def is_task_matched_with_metadata(task, calendar_task=None):
    candidates = [
        (calendar_task or {}).get("match_tmdb_id"),
        ((calendar_task or {}).get("match") or {}).get("tmdb_id"),
        (calendar_task or {}).get("tmdb_id"),
        (task or {}).get("match_tmdb_id"),
        ((task or {}).get("match") or {}).get("tmdb_id"),
        (((task or {}).get("calendar_info") or {}).get("match") or {}).get("tmdb_id"),
        (task or {}).get("tmdb_id"),
    ]
    for item in candidates:
        if item is None:
            continue
        if str(item).strip() != "":
            return True
    return False


def progress_from_season_counts(season_counts):
    if not season_counts:
        return None
    try:
        transferred = int(season_counts.get("transferred_count") or 0)
        aired = int(season_counts.get("aired_count") or 0)
        total = int(season_counts.get("total_count") or 0)
    except (TypeError, ValueError):
        return None
    if transferred == 0 and aired == 0 and total == 0:
        return None
    if aired <= 0:
        return 0
    return max(0, min(100, transferred * 100 // aired))


def is_task_completed_by_status_and_progress(status, progress_value):
    if status not in FINAL_STATUSES:
        return False
    if progress_value is None:
        return False
    try:
        return int(progress_value) >= 100
    except (TypeError, ValueError):
        return False


def is_subscribed_on_date(since_value, today_str):
    if not since_value or not today_str:
        return False
    date_part = str(since_value).strip().split()[0]
    parts = date_part.split("-")
    if len(parts) != 3:
        return False
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except (TypeError, ValueError):
        return False
    return f"{year:04d}-{month:02d}-{day:02d}" == today_str


def _failed_task_entry(task_name, ban_message):
    formatted = format_shareurl_ban_message(ban_message)
    return {
        "taskname": task_name,
        "shareurl_ban": formatted if formatted else str(ban_message),
    }


def compute_overview_task_stats(
    tasks,
    calendar_by_name=None,
    complete_by_name=None,
    today=None,
):
    """按总览页口径汇总全部任务。

    calendar_by_name: 任务名 -> {content_type, matched_status, status, season_counts, match_tmdb_id, tmdb_id}
    complete_by_name: 任务名 -> 转存是否已全部完成（电影有记录 / 剧集转存数达总集数）
    today: YYYY-MM-DD，默认不统计「今日加入」除非传入
    """
    stats = empty_overview_task_stats()
    calendar_by_name = calendar_by_name or {}
    complete_by_name = complete_by_name or {}
    failed_tasks = []

    if not tasks:
        stats["failed_tasks"] = failed_tasks
        return stats

    for task in tasks:
        if not task or not isinstance(task, dict):
            continue
        name = task_display_name(task)
        cal_task = calendar_by_name.get(name) if name else None
        content_type = resolve_content_type(task, cal_task)
        count_key = CONTENT_TYPE_COUNT_KEYS.get(content_type, "other_count")
        stats[count_key] = stats.get(count_key, 0) + 1

        season_counts = None
        if cal_task and cal_task.get("season_counts"):
            season_counts = cal_task.get("season_counts")
        elif task.get("season_counts"):
            season_counts = task.get("season_counts")
        progress = progress_from_season_counts(season_counts)

        if content_type in SERIES_CONTENT_TYPES and (progress is None or progress < 100):
            stats["ongoing_count"] += 1

        if today and is_subscribed_on_date(task.get("shareurl_subscribed_since"), today):
            stats["today_count"] += 1

        is_complete = bool(name and complete_by_name.get(name))
        ban = task.get("shareurl_ban")
        if (not is_complete) and should_count_shareurl_ban(ban):
            failed_tasks.append(_failed_task_entry(name, ban))

        status = resolve_task_status(task, cal_task)
        is_status_completed = is_task_completed_by_status_and_progress(status, progress)
        is_matched = is_task_matched_with_metadata(task, cal_task)
        if status == "播出中":
            stats["status_airing"] += 1
        elif status == "本季终":
            stats["status_finale"] += 1
        elif status == "已完结":
            stats["status_ended"] += 1
        elif is_status_completed:
            stats["status_completed"] += 1
        elif not is_matched:
            stats["status_unmatched"] += 1

    stats["failed_count"] = len(failed_tasks)
    stats["failed_tasks"] = failed_tasks
    return stats
