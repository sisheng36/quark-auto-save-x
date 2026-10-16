#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热路径 DB 优化回归（P0 + P1）：

P1 —— CalendarDB / RecordDB 的建表与字段迁移每个库每进程只执行一次
      （原来每次 new 实例都跑一遍：一次保存实测 1501 次 init_db，累计 6~8 秒）
P0 —— 播出时间查询带短 TTL 缓存，_build_episode_local_air_dt 复用调用方的连接
      （原来每集 new 一次 CalendarDB，一次保存 1488 次）

运行：python3 tests/test_db_hot_path.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO, "app")
for p in (REPO, APP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.sdk.db import CalendarDB, RecordDB  # noqa: E402

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


def count_ddl(fn):
    """统计 fn() 期间真正执行的建表/迁移（_init_db_schema）次数"""
    orig_cal = CalendarDB._init_db_schema
    orig_rec = RecordDB._init_db_schema
    counter = {"n": 0}

    def wrap(orig):
        def inner(self, cursor):
            counter["n"] += 1
            return orig(self, cursor)

        return inner

    CalendarDB._init_db_schema = wrap(orig_cal)
    RecordDB._init_db_schema = wrap(orig_rec)
    try:
        fn()
    finally:
        CalendarDB._init_db_schema = orig_cal
        RecordDB._init_db_schema = orig_rec
    return counter["n"]


def test_schema_created_once():
    print("\n[1] 建表/迁移每进程只执行一次")
    tmp = tempfile.mkdtemp(prefix="qas_schema_once_")
    db_path = os.path.join(tmp, "data.db")

    first = count_ddl(lambda: (CalendarDB(db_path=db_path).close(), RecordDB(db_path=db_path).close()))
    check("首次实例化会建表", first > 0, True)

    later = count_ddl(
        lambda: [(CalendarDB(db_path=db_path).close(), RecordDB(db_path=db_path).close()) for _ in range(20)]
    )
    check("后续 20×2 次实例化不再执行任何建表/迁移语句", later, 0)

    # 连接仍然可用
    db = CalendarDB(db_path=db_path)
    db.upsert_season_metrics(100, 1, 3, 5, 10, 60, 1700000000)
    row = db.get_season_metrics(100, 1)
    check("建表跳过后仍能正常读写", bool(row), True)
    db.close()


def test_legacy_migration_still_runs():
    print("\n[2] 旧库结构迁移仍然生效（task_metrics 复合主键）")
    tmp = tempfile.mkdtemp(prefix="qas_schema_migrate_")
    db_path = os.path.join(tmp, "legacy.db")
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE task_metrics (task_name TEXT PRIMARY KEY, tmdb_id INTEGER, "
        "season_number INTEGER, transferred_count INTEGER, updated_at INTEGER)"
    )
    con.execute("INSERT INTO task_metrics VALUES ('t1', 7, 1, 4, 1700000000)")
    con.commit()
    con.close()

    db = CalendarDB(db_path=db_path)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(task_metrics)")]
    check("补齐 save_path 列", "save_path" in cols, True)
    row = db.conn.execute(
        "SELECT task_name, save_path, transferred_count FROM task_metrics"
    ).fetchone()
    check("旧数据迁移后保留", tuple(row), ("t1", "", 4))
    db.close()


def test_recreated_db_gets_schema():
    print("\n[3] 数据库文件被替换（inode 变化）时会重新建表")
    tmp = tempfile.mkdtemp(prefix="qas_schema_recreate_")
    db_path = os.path.join(tmp, "data.db")
    CalendarDB(db_path=db_path).close()

    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass

    db = CalendarDB(db_path=db_path)
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check("新库重新建出 shows 表", "shows" in tables, True)
    db.close()


def load_webapp():
    spec = importlib.util.spec_from_file_location("qas_hotpath_app", os.path.join(APP_DIR, "run.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_air_schedule_cache_and_db_reuse():
    print("\n[4] 播出时间缓存 + 复用连接（P0）")
    mod = load_webapp()

    calls = {"n": 0}

    class FakeDB:
        def get_show_air_schedule(self, tmdb_id):
            calls["n"] += 1
            return {"local_air_time": "21:30"}

    mod.clear_air_schedule_cache()
    got = mod._get_show_air_schedule_cached(999, FakeDB())
    check("首次查询走数据库", got.get("local_air_time"), "21:30")
    mod._get_show_air_schedule_cached(999, FakeDB())
    mod._get_show_air_schedule_cached(999)
    check("同一节目命中缓存，不再查库", calls["n"], 1)

    mod.clear_air_schedule_cache()
    mod._get_show_air_schedule_cached(999, FakeDB())
    check("清理缓存后重新查库（播出时间变更时调用）", calls["n"], 2)

    dt, used = mod._build_episode_local_air_dt(999, None, "2026-10-20", None, db=FakeDB())
    check("_build_episode_local_air_dt 复用传入连接", (used, dt.hour, dt.minute), ("21:30", 21, 30))

    src = open(os.path.join(APP_DIR, "run.py"), encoding="utf-8").read()
    check("热路径不再每次 new CalendarDB 查播出时间", "CalendarDB().get_show_air_schedule" not in src, True)
    check("is_episode_aired 复用线程内连接", "cal_db = _get_shared_calendar_db()" in src, True)


if __name__ == "__main__":
    test_schema_created_once()
    test_legacy_migration_still_runs()
    test_recreated_db_gets_schema()
    test_air_schedule_cache_and_db_reuse()
    print(f"\n结果: {PASSED} 通过, {FAILED} 失败")
    if FAILED:
        sys.exit(1)
    print("DB HOT PATH TEST PASSED")
