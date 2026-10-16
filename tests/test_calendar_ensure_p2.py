#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日历元数据补全（P2）回归：

背景：保存配置后会在后台跑 ensure_calendar_info_for_tasks()，原来
      1) 对所有电影任务无条件重跑 TMDB（127 任务中 54 部电影 ≈ 60 秒）
      2) 和保存响应 / 前端刷任务列表抢资源
      3) 拉不到的任务每次保存都重试

现在：延后 + 单飞 + 时间/请求预算 + 失败冷却期 + 已匹配电影直接跳过。

运行：python3 tests/test_calendar_ensure_p2.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO, "app")

# 必须在导入 run.py 之前指向临时配置，避免测试真的写仓库配置
_tmp_cfg = os.path.join(tempfile.mkdtemp(prefix="qas_p2_cfg_"), "quark_config.json")
with open(_tmp_cfg, "w", encoding="utf-8") as f:
    json.dump({"tasklist": []}, f)
os.environ["CONFIG_PATH"] = _tmp_cfg

for p in (REPO, APP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

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
    spec = importlib.util.spec_from_file_location("qas_p2_app", os.path.join(APP_DIR, "run.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeTMDB:
    """记录调用次数的假 TMDB 客户端"""

    calls = []

    def __init__(self, api_key=None, language=None):
        self.api_key = api_key
        self.language = language

    def search_tv_show(self, name, year=None):
        FakeTMDB.calls.append(("search_tv_show", name))
        return {"id": 999, "name": name}

    def get_tv_show_details(self, tmdb_id):
        FakeTMDB.calls.append(("get_tv_show_details", tmdb_id))
        return {"first_air_date": "2026-01-01", "seasons": [{"season_number": 1}]}

    def get_chinese_title_with_fallback(self, tmdb_id, fallback=""):
        FakeTMDB.calls.append(("get_chinese_title_with_fallback", tmdb_id))
        return fallback or "剧名"

    def search_movie_all(self, name, year=None):
        FakeTMDB.calls.append(("search_movie_all", name))
        return []


def movie_task(name="电影A", matched=True):
    cal = {
        "extracted": {"show_name": name, "year": "2026", "content_type": "movie"},
    }
    if matched:
        cal["match"] = {"tmdb_id": 111, "matched_show_name": name}
    return {
        "taskname": name,
        "savepath": f"媒体库/电影/{name} (2026)",
        "content_type": "movie",
        "calendar_info": cal,
    }


def tv_task(name="剧名B", matched=False):
    cal = {"extracted": {"show_name": name, "year": "2026", "content_type": "tv"}}
    if matched:
        cal["match"] = {"tmdb_id": 222, "matched_show_name": name}
    return {
        "taskname": name,
        "savepath": f"媒体库/剧集/{name} (2026)/Season 01",
        "content_type": "tv",
        "calendar_info": cal,
    }


def reset_state(mod):
    mod._MATCH_RETRY_BLOCK.clear()
    mod._AIR_SCHEDULE_CACHE.clear() if hasattr(mod, "_AIR_SCHEDULE_CACHE") else None
    with mod._CALENDAR_ENSURE_LOCK:
        mod._CALENDAR_ENSURE_TIMER = None
        mod._CALENDAR_ENSURE_PENDING = False
        mod._CALENDAR_ENSURE_RUNNING = False


def test_matched_movies_skipped():
    print("\n[1] 已匹配的电影不再重跑 TMDB（原来每次保存把 54 部电影全部重跑）")
    mod = load_webapp()
    reset_state(mod)
    calls = []
    mod.TMDBService = FakeTMDB
    mod.process_movie_task_async = lambda task, svc, db: (calls.append(task.get("taskname")), False)[1]

    mod.config_data.clear()
    mod.config_data.update({
        "tasklist": [movie_task("电影A", matched=True), movie_task("电影B", matched=True)],
        "tmdb_api_key": "test-key",
        "task_settings": {},
    })
    mod.ensure_calendar_info_for_tasks()
    check("已匹配电影不调用 process_movie_task_async", calls, [])

    calls.clear()
    mod.ensure_calendar_info_for_tasks(force=True)
    check("force=True 时才重新处理", calls, ["电影A", "电影B"])


def test_unmatched_retry_cooldown():
    print("\n[2] 拉取失败的任务有冷却期，不会每次保存都重试")
    mod = load_webapp()
    reset_state(mod)
    mod.TMDBService = FakeTMDB

    def fake_movie(task, svc, db):
        # 真实实现内部会走 TMDB，这里同样发起一次调用，便于断言冷却期
        svc.search_movie_all(task.get("taskname"), None)
        return False

    mod.process_movie_task_async = fake_movie

    mod.config_data.clear()
    mod.config_data.update({
        "tasklist": [movie_task("未匹配电影", matched=False)],
        "tmdb_api_key": "test-key",
        "task_settings": {},
    })
    FakeTMDB.calls.clear()
    mod.ensure_calendar_info_for_tasks()
    first = list(FakeTMDB.calls)
    check("首次尝试会查 TMDB", len(first) > 0, True)

    FakeTMDB.calls.clear()
    mod.ensure_calendar_info_for_tasks()
    check("冷却期内不再重试", FakeTMDB.calls, [])

    FakeTMDB.calls.clear()
    mod.ensure_calendar_info_for_tasks(force=True)
    check("force=True 忽略冷却期", len(FakeTMDB.calls) > 0, True)


def test_budget_limits_network_tasks():
    print("\n[3] 单次预算限制联网任务数")
    mod = load_webapp()
    reset_state(mod)
    mod.TMDBService = FakeTMDB
    processed = []
    mod.process_movie_task_async = lambda task, svc, db: (processed.append(task.get("taskname")), True)[1]

    mod.config_data.clear()
    mod.config_data.update({
        "tasklist": [movie_task(f"电影{i}", matched=False) for i in range(5)],
        "tmdb_api_key": "test-key",
        "task_settings": {},
    })
    mod.ensure_calendar_info_for_tasks(max_network_tasks=2)
    check("只处理预算内的 2 个任务", processed, ["电影0", "电影1"])


def test_forced_run_unlimited():
    print("\n[4] force 全量刷新不受预算限制（bootstrap/手动刷新用）")
    mod = load_webapp()
    reset_state(mod)
    mod.TMDBService = FakeTMDB
    processed = []
    mod.process_movie_task_async = lambda task, svc, db: (processed.append(task.get("taskname")), True)[1]

    mod.config_data.clear()
    mod.config_data.update({
        "tasklist": [movie_task(f"电影{i}", matched=False) for i in range(4)],
        "tmdb_api_key": "test-key",
        "task_settings": {},
    })
    mod.ensure_calendar_info_for_tasks(force=True)
    check("force 且不传预算时处理全部任务（bootstrap 场景）", len(processed), 4)


def test_tv_matched_skipped_and_failure_marked():
    print("\n[5] 已匹配剧集不查 TMDB；未匹配失败会记冷却")
    mod = load_webapp()
    reset_state(mod)
    mod.TMDBService = FakeTMDB
    mod.process_movie_task_async = lambda task, svc, db: False

    mod.config_data.clear()
    mod.config_data.update({
        "tasklist": [tv_task("已匹配剧", matched=True), tv_task("未匹配剧", matched=False)],
        "tmdb_api_key": "test-key",
        "task_settings": {},
    })
    FakeTMDB.calls.clear()
    mod.ensure_calendar_info_for_tasks()
    searched = [c for c in FakeTMDB.calls if c[0] == "search_tv_show"]
    check("只对未匹配剧集发起搜索", searched, [("search_tv_show", "未匹配剧")])

    FakeTMDB.calls.clear()
    mod.ensure_calendar_info_for_tasks()
    check("同一未匹配剧集冷却期内不再搜索", FakeTMDB.calls, [])


def test_schedule_ensure_debounce_and_single_flight():
    print("\n[6] 延后执行 + 单飞（同一时刻只跑一个，重复调用合并）")
    mod = load_webapp()
    reset_state(mod)
    runs = []

    def slow_ensure(**kwargs):
        runs.append(("start", time.time()))
        time.sleep(0.4)
        runs.append(("end", time.time()))

    mod.ensure_calendar_info_for_tasks = slow_ensure

    check("首次调度成功", mod.schedule_calendar_info_ensure("t1", delay=0.05), True)
    check("排队期间重复调度被合并", mod.schedule_calendar_info_ensure("t2", delay=0.05), False)
    time.sleep(0.6)
    check("已执行一次", [r[0] for r in runs], ["start", "end"])
    check("单飞后状态复位", mod._CALENDAR_ENSURE_RUNNING, False)
    check("排队的补跑已消化", mod._CALENDAR_ENSURE_PENDING, False)
    reset_state(mod)


def _seed_config(mod, tasks, with_crontab=True):
    mod.config_data.clear()
    mod.config_data.update({
        "webui": {"username": "admin", "password": "admin"},
        "tasklist": tasks,
        "tmdb_api_key": "",
        "task_settings": {},
        # reload_tasks() 需要 crontab 才返回 True（通知/清缓存分支才会走到）
        "crontab": "0 8 * * *" if with_crontab else "",
    })


def test_save_only_clears_cache_when_tasks_changed():
    print("\n[7] 保存时只在任务数据真的变化后才清缓存（payload 指纹）")
    mod = load_webapp()
    reset_state(mod)
    mod._LAST_SAVED_TASKLIST_SIGNATURE = None
    mod._post_update_tasks = lambda *a, **k: None
    mod.process_new_tasks_async = lambda *a, **k: None
    _seed_config(mod, [tv_task("缓存任务", matched=True)])

    client = mod.app.test_client()
    tok = mod.get_login_token()
    payload = json.loads(json.dumps(mod.config_data))
    count = lambda: (mod._calendar_tasks_cache_lock.acquire(), len(mod._calendar_tasks_cache), mod._calendar_tasks_cache_lock.release())[1]

    client.post(f"/update?token={tok}", json=payload)   # 第一次保存：建立基准指纹
    client.get(f"/api/calendar/tasks?token={tok}")      # 预热
    check("预热后有缓存", count() > 0, True)

    client.post(f"/update?token={tok}", json=payload)   # 内容未变的保存
    check("内容未变的保存不清缓存", count() > 0, True)

    changed_payload = json.loads(json.dumps(payload))
    changed_payload["tasklist"].append(tv_task("新任务", matched=False))
    resp = client.post(f"/update?token={tok}", json=changed_payload)
    check("变化后的保存成功", bool(resp.get_json().get("success")), True)
    check("任务数据变化后清缓存", count(), 0)
    try:
        mod.scheduler.pause()
        mod.scheduler.remove_all_jobs()
    except Exception:
        pass


def test_post_update_thread_clear_is_conditional():
    print("\n[8] 保存后的收尾线程不再无条件清缓存")
    mod = load_webapp()
    reset_state(mod)
    mod._LAST_SAVED_TASKLIST_SIGNATURE = None
    # 收尾线程里所有可能改数据的步骤都返回"无变化"
    mod.sync_task_config_with_database_bindings = lambda *a, **k: False
    mod.sync_content_type_between_config_and_database = lambda *a, **k: False
    mod.purge_calendar_by_tmdb_id_internal = lambda *a, **k: None
    mod.ensure_calendar_info_for_tasks = lambda *a, **k: False
    mod.cleanup_orphaned_posters = lambda *a, **k: None
    # 收尾线程里的孤儿数据清理：桩成"没删任何东西"，避免依赖宿主机上的 DB 现状
    import app.sdk.db as dbmod

    class _FakeCalDB:
        def __init__(self, *a, **k):
            pass

        def cleanup_orphan_data(self, *a, **k):
            return False

    _orig_caldb = dbmod.CalendarDB
    dbmod.CalendarDB = _FakeCalDB
    _seed_config(mod, [tv_task("线程任务", matched=True)])

    client = mod.app.test_client()
    tok = mod.get_login_token()
    payload = json.loads(json.dumps(mod.config_data))
    count = lambda: (mod._calendar_tasks_cache_lock.acquire(), len(mod._calendar_tasks_cache), mod._calendar_tasks_cache_lock.release())[1]

    client.post(f"/update?token={tok}", json=payload)
    time.sleep(0.4)
    client.get(f"/api/calendar/tasks?token={tok}")
    check("预热后有缓存", count() > 0, True)

    client.post(f"/update?token={tok}", json=payload)
    time.sleep(0.8)  # 等收尾线程跑完
    check("无变化时收尾线程不清缓存", count() > 0, True)

    mod.sync_task_config_with_database_bindings = lambda *a, **k: True
    client.post(f"/update?token={tok}", json=payload)
    time.sleep(0.8)
    check("有变化时收尾线程清缓存", count(), 0)
    dbmod.CalendarDB = _orig_caldb
    try:
        mod.scheduler.pause()
        mod.scheduler.remove_all_jobs()
    except Exception:
        pass


def test_tasklist_signature():
    print("\n[9] 任务列表指纹")
    mod = load_webapp()
    base = [tv_task("剧A", matched=True)]
    sig1 = mod._tasklist_signature(base)
    check("相同数据指纹一致", mod._tasklist_signature([tv_task("剧A", matched=True)]), sig1)

    other = [tv_task("剧A", matched=True)]
    other[0]["savepath"] = "媒体库/剧集/改名/Season 01"
    check("保存路径变化会改变指纹", mod._tasklist_signature(other) != sig1, True)

    other2 = [tv_task("剧A", matched=True)]
    other2[0]["calendar_info"]["match"]["tmdb_id"] = 333
    check("TMDB 匹配变化会改变指纹", mod._tasklist_signature(other2) != sig1, True)


if __name__ == "__main__":
    test_matched_movies_skipped()
    test_unmatched_retry_cooldown()
    test_budget_limits_network_tasks()
    test_forced_run_unlimited()
    test_tv_matched_skipped_and_failure_marked()
    test_schedule_ensure_debounce_and_single_flight()
    test_save_only_clears_cache_when_tasks_changed()
    test_post_update_thread_clear_is_conditional()
    test_tasklist_signature()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    if FAILED:
        sys.exit(1)
    print("CALENDAR ENSURE P2 TEST PASSED")
