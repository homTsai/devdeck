"""SQLite 存取層。設定資料只存在本機，不進版控。"""

import sqlite3
from contextlib import contextmanager

from .paths import migrate_legacy_file

DB_PATH = migrate_legacy_file("devdeck.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    scripts_dir TEXT NOT NULL DEFAULT 'scripts',
    venv_path   TEXT NOT NULL DEFAULT '.venv'
);
CREATE TABLE IF NOT EXISTS services (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    port       INTEGER NOT NULL,
    pid_file   TEXT,
    url        TEXT                -- 選填：有值時狀態列顯示「開啟」連結
);
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    script_file TEXT,               -- 與 command 二選一：腳本目錄內的檔名
    command     TEXT,               -- 與 script_file 二選一：直接執行的指令
    label       TEXT NOT NULL,
    workdir     TEXT,
    category    TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS action_services (
    action_id    INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    service_id   INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    disable_when TEXT NOT NULL CHECK (disable_when IN ('running', 'stopped')),
    PRIMARY KEY (action_id, service_id)
);
"""

MIGRATE_ADD_COMMAND = """
ALTER TABLE actions RENAME TO actions_old;
CREATE TABLE actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    service_id  INTEGER REFERENCES services(id) ON DELETE SET NULL,
    script_file TEXT,
    command     TEXT,
    label       TEXT NOT NULL,
    workdir     TEXT,
    category    TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);
INSERT INTO actions (id, project_id, service_id, script_file, command,
                     label, workdir, category, sort_order)
    SELECT id, project_id, service_id, script_file, NULL,
           label, workdir, category, sort_order
    FROM actions_old;
DROP TABLE actions_old;
"""

MIGRATE_DROP_SERVICE_ID = """
ALTER TABLE actions RENAME TO actions_old;
CREATE TABLE actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    script_file TEXT,
    command     TEXT,
    label       TEXT NOT NULL,
    workdir     TEXT,
    category    TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);
INSERT INTO actions (id, project_id, script_file, command,
                     label, workdir, category, sort_order)
    SELECT id, project_id, script_file, command,
           label, workdir, category, sort_order
    FROM actions_old;
DROP TABLE actions_old;
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    # 先遷移舊表再套 SCHEMA：action_services 建立前重建 actions，避免 RENAME 改寫其外鍵
    _migrate()
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _migrate():
    conn = sqlite3.connect(DB_PATH)  # 遷移期間不開 foreign_keys，避免 RENAME 干擾
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(actions)")}
        if not cols:
            return  # 全新資料庫，交給 SCHEMA 建表
        # v1 → v2：加入 command 欄位（script_file 改為 nullable）
        if "command" not in cols:
            conn.executescript(MIGRATE_ADD_COMMAND)
            conn.commit()
            cols = {r[1] for r in conn.execute("PRAGMA table_info(actions)")}
        # v2 → v3：移除 service_id，關聯改由 action_services 多對多承載（舊關聯不轉換）
        if "service_id" in cols:
            conn.executescript(MIGRATE_DROP_SERVICE_ID)
            conn.commit()
        # v3 → v4：services 加 url 欄位
        svc_cols = {r[1] for r in conn.execute("PRAGMA table_info(services)")}
        if svc_cols and "url" not in svc_cols:
            conn.execute("ALTER TABLE services ADD COLUMN url TEXT")
            conn.commit()
    finally:
        conn.close()
