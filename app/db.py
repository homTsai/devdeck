"""SQLite 存取層。設定資料只存在本機，不進版控。"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "devdeck.db"

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
    pid_file   TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    service_id  INTEGER REFERENCES services(id) ON DELETE SET NULL,
    script_file TEXT,               -- 與 command 二選一：腳本目錄內的檔名
    command     TEXT,               -- 與 script_file 二選一：直接執行的指令
    label       TEXT NOT NULL,
    workdir     TEXT,
    category    TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
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
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    _migrate()


def _migrate():
    # 舊版 actions 沒有 command 欄位（script_file NOT NULL），需重建表
    conn = sqlite3.connect(DB_PATH)  # 遷移期間不開 foreign_keys，避免 RENAME 干擾
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(actions)")}
        if "command" not in cols:
            conn.executescript(MIGRATE_ADD_COMMAND)
            conn.commit()
    finally:
        conn.close()
