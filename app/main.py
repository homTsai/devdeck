"""devdeck — 本機開發腳本啟動面板。只綁 127.0.0.1:7999。"""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

from typing import Literal
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, runner, status
from .paths import migrate_legacy_file

app = FastAPI(title="devdeck")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SCRIPT_EXTS = {".ps1", ".py", ".sh", ".mjs", ".js", ".cmd", ".bat"}

# 資料夾選擇器：devdeck 跑在使用者本機，所以由後端叫出系統原生「選擇資料夾」視窗，
# 回傳真實絕對路徑（瀏覽器的 file input 拿不到絕對路徑）。用短命子行程跑 tkinter，
# 避免和 uvicorn 的 async event loop 搶主執行緒。
_PICK_DIR_CODE = r"""
import os, sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as e:
    sys.stderr.write("tkinter unavailable: %s" % e)
    sys.exit(2)
initialdir = sys.argv[1] if len(sys.argv) > 1 else ""
title = sys.argv[2] if len(sys.argv) > 2 else "Select folder"
if initialdir and not os.path.isdir(initialdir):
    initialdir = ""
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
path = filedialog.askdirectory(initialdir=initialdir or None, title=title)
root.destroy()
if path:
    sys.stdout.write(os.path.normpath(path))
"""

_PICK_FILE_CODE = r"""
import os, sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as e:
    sys.stderr.write("tkinter unavailable: %s" % e)
    sys.exit(2)
raw_init = sys.argv[1] if len(sys.argv) > 1 else ""
title = sys.argv[2] if len(sys.argv) > 2 else "Select script file"
initialdir = ""
if raw_init:
    if os.path.isfile(raw_init):
        initialdir = os.path.dirname(raw_init)
    elif os.path.isdir(raw_init):
        initialdir = raw_init
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
path = filedialog.askopenfilename(
    initialdir=initialdir or None,
    title=title,
    filetypes=[
        ("Supported scripts", "*.ps1 *.py *.sh *.mjs *.js *.cmd *.bat"),
        ("All files", "*.*"),
    ],
)
root.destroy()
if path:
    sys.stdout.write(os.path.normpath(path))
"""

db.init_db()

LOCAL_NAMES = {"127.0.0.1", "localhost"}

# token 的信任根是「能讀本機檔案」：啟動腳本讀檔帶進網址，服務本身絕不線上發放
TOKEN_FILE = migrate_legacy_file("devdeck.token")


def _load_or_create_token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


API_TOKEN = _load_or_create_token()


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    """只服務本機來源：擋 DNS rebinding（Host 偽裝）與惡意網頁的跨站請求（Origin 非本機）。"""
    host = request.headers.get("host", "").split(":")[0].lower()
    if host not in LOCAL_NAMES:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in LOCAL_NAMES:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    if request.url.path.startswith("/api/"):
        supplied = request.headers.get("x-devdeck-token", "")
        if not secrets.compare_digest(supplied, API_TOKEN):
            return JSONResponse({"detail": "invalid token"}, status_code=401)
    return await call_next(request)


# ---------- models ----------

class ProjectIn(BaseModel):
    name: str
    path: str
    scripts_dir: str = "scripts"
    venv_path: str = ".venv"


class ServiceIn(BaseModel):
    name: str
    port: int
    pid_file: str | None = None
    url: str | None = None


class ActionServiceLink(BaseModel):
    service_id: int
    disable_when: Literal["running", "stopped"]


class ActionIn(BaseModel):
    script_dir_id: int | None = None
    script_file: str | None = None
    command: str | None = None
    arguments: str | None = None
    execution_mode: Literal["panel", "terminal"] = "panel"
    run_as_admin: bool = False
    confirm_before_run: bool = False
    confirm_message: str | None = None
    label: str
    services: list[ActionServiceLink] = []
    workdir: str | None = None
    category: str | None = None
    sort_order: int = 0

    def validate_source(self):
        has_script = bool(self.script_file and self.script_file.strip())
        has_cmd = bool(self.command and self.command.strip())
        if has_script == has_cmd:
            raise HTTPException(400, detail={"key": "err.scriptXorCommand"})

    def validate_execution(self):
        if self.run_as_admin and self.execution_mode != "terminal":
            raise HTTPException(400, detail={"key": "err.adminRequiresTerminal"})


class GlobalScriptDirIn(BaseModel):
    path: str


class ActionVisibilityIn(BaseModel):
    hidden: bool


class RunActionIn(BaseModel):
    project_id: int | None = None


class PickDirIn(BaseModel):
    initialdir: str | None = None  # 對話框起始資料夾（如專案路徑）；不存在則忽略
    title: str | None = None       # 對話框標題（由前端依語系帶入）


class PickFileIn(BaseModel):
    initialdir: str | None = None
    title: str | None = None


class CategoryReorderIn(BaseModel):
    categories: list[str | None]


class CategoryRenameIn(BaseModel):
    old_category: str | None = None
    new_category: str | None = None


class ProjectReorderIn(BaseModel):
    project_ids: list[int]


# ---------- helpers ----------

def get_project(project_id: int) -> dict:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, detail={"key": "err.projectNotFound"})
    return dict(row)


# ---------- projects ----------

@app.get("/api/projects")
def list_projects():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY sort_order, name, id")]


@app.post("/api/projects")
def create_project(body: ProjectIn):
    if not Path(body.path).is_dir():
        raise HTTPException(400, detail={"key": "err.projectPathMissing", "params": {"path": body.path}})
    with db.get_conn() as conn:
        next_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM projects").fetchone()[0] + 10
        cur = conn.execute(
            "INSERT INTO projects (name, path, scripts_dir, venv_path, sort_order) VALUES (?,?,?,?,?)",
            (body.name, body.path, body.scripts_dir, body.venv_path, next_order),
        )
        return {"id": cur.lastrowid}


@app.post("/api/projects/reorder")
def reorder_projects(body: ProjectReorderIn):
    with db.get_conn() as conn:
        existing = [
            r["id"] for r in conn.execute("SELECT id FROM projects ORDER BY sort_order, name, id")
        ]
        existing_set = set(existing)
        ordered_ids: list[int] = []
        for pid in body.project_ids:
            if pid in existing_set and pid not in ordered_ids:
                ordered_ids.append(pid)
        for pid in existing:
            if pid not in ordered_ids:
                ordered_ids.append(pid)
        for idx, pid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE projects SET sort_order=? WHERE id=?", (idx * 10, pid))
    return {"ok": True}


@app.put("/api/projects/{project_id}")
def update_project(project_id: int, body: ProjectIn):
    get_project(project_id)
    if not Path(body.path).is_dir():
        raise HTTPException(400, detail={"key": "err.projectPathMissing", "params": {"path": body.path}})
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE projects SET name=?, path=?, scripts_dir=?, venv_path=? WHERE id=?",
            (body.name, body.path, body.scripts_dir, body.venv_path, project_id),
        )
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    get_project(project_id)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"ok": True}


@app.get("/api/projects/{project_id}/scan")
def scan_scripts(project_id: int):
    project = get_project(project_id)
    scripts_dir = Path(project["path"]) / project["scripts_dir"]
    if not scripts_dir.is_dir():
        raise HTTPException(400, detail={"key": "err.scriptsDirMissing", "params": {"dir": str(scripts_dir)}})
    with db.get_conn() as conn:
        added = {
            r["script_file"]
            for r in conn.execute(
                "SELECT script_file FROM actions WHERE project_id=? AND script_file IS NOT NULL",
                (project_id,))
        }
    files = sorted(
        p.name for p in scripts_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SCRIPT_EXTS
    )
    return [{"file": f, "added": f in added} for f in files]


# ---------- services ----------

@app.get("/api/projects/{project_id}/services")
def list_services(project_id: int):
    get_project(project_id)
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM services WHERE project_id=? ORDER BY id", (project_id,))]


@app.post("/api/projects/{project_id}/services")
def create_service(project_id: int, body: ServiceIn):
    get_project(project_id)
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO services (project_id, name, port, pid_file, url) VALUES (?,?,?,?,?)",
            (project_id, body.name, body.port, body.pid_file, body.url),
        )
        return {"id": cur.lastrowid}


@app.put("/api/services/{service_id}")
def update_service(service_id: int, body: ServiceIn):
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE services SET name=?, port=?, pid_file=?, url=? WHERE id=?",
            (body.name, body.port, body.pid_file, body.url, service_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, detail={"key": "err.serviceNotFound"})
    return {"ok": True}


@app.delete("/api/services/{service_id}")
def delete_service(service_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM services WHERE id=?", (service_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, detail={"key": "err.serviceNotFound"})
    return {"ok": True}


@app.get("/api/projects/{project_id}/status")
async def project_status(project_id: int):
    project = get_project(project_id)
    with db.get_conn() as conn:
        services = [dict(r) for r in conn.execute(
            "SELECT * FROM services WHERE project_id=? ORDER BY id", (project_id,))]
    result = []
    for svc in services:
        listening = await status.port_listening(svc["port"])
        pid = pid_alive = None
        if svc["pid_file"]:
            pid = status.read_pid(Path(project["path"]) / svc["pid_file"])
            if pid is not None:
                pid_alive = status.pid_alive(pid)
        result.append({**svc, "listening": listening, "pid": pid, "pid_alive": pid_alive})
    return result


# ---------- actions ----------

def _norm_confirm_message(msg: str | None) -> str | None:
    if msg is None:
        return None
    cleaned = msg.replace("\r\n", "\n").strip()
    return cleaned or None


def _norm_category(cat: str | None) -> str | None:
    if cat is None:
        return None
    cleaned = cat.strip()
    return cleaned or None


def _norm_path(path: str) -> str:
    return os.path.normpath(path.strip())


def _validate_global_script(conn, body: ActionIn):
    if body.command and body.command.strip():
        return
    script_file = (body.script_file or "").strip()
    if body.script_dir_id is not None:
        row = conn.execute(
            "SELECT id FROM global_script_dirs WHERE id=?", (body.script_dir_id,)
        ).fetchone()
        if not row:
            raise HTTPException(400, detail={"key": "err.scriptDirNotFound"})
    else:
        if not Path(script_file).is_absolute():
            raise HTTPException(400, detail={"key": "err.scriptPathMustBeAbsolute"})


def _format_action_row(
    row: dict, *, services: list | None = None, hidden: bool | None = None
) -> dict:
    script_dir_path = row.pop("script_dir_path", None)
    is_global = row["project_id"] is None
    row["run_as_admin"] = bool(row.get("run_as_admin"))
    row["confirm_before_run"] = bool(row.get("confirm_before_run"))
    row["is_global"] = is_global
    row["services"] = services if services is not None else []
    if is_global and row.get("script_file"):
        if row.get("script_dir_id") is not None and script_dir_path:
            row["resolved_script_path"] = str(Path(script_dir_path) / row["script_file"])
        else:
            row["resolved_script_path"] = row["script_file"]
    else:
        row["resolved_script_path"] = None
    if hidden is not None:
        row["hidden"] = hidden
    return row


def _replace_links(conn, action_id: int, links: list[ActionServiceLink]):
    conn.execute("DELETE FROM action_services WHERE action_id=?", (action_id,))
    for link in links:
        conn.execute(
            "INSERT INTO action_services (action_id, service_id, disable_when) VALUES (?,?,?)",
            (action_id, link.service_id, link.disable_when),
        )


# ---------- global script dirs ----------

@app.get("/api/global-script-dirs")
def list_global_script_dirs():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM global_script_dirs ORDER BY sort_order, id"
        ).fetchall()
    return [
        {**dict(r), "exists": Path(r["path"]).is_dir()}
        for r in rows
    ]


@app.post("/api/global-script-dirs")
def create_global_script_dir(body: GlobalScriptDirIn):
    norm = _norm_path(body.path)
    if not norm or not Path(norm).is_dir():
        raise HTTPException(400, detail={"key": "err.scriptsDirMissing", "params": {"dir": body.path}})
    norm_key = os.path.normcase(norm)
    with db.get_conn() as conn:
        for existing in conn.execute("SELECT id, path FROM global_script_dirs"):
            if os.path.normcase(existing["path"]) == norm_key:
                return {"id": existing["id"], "path": existing["path"], "created": False}
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM global_script_dirs"
        ).fetchone()[0] + 10
        cur = conn.execute(
            "INSERT INTO global_script_dirs (path, sort_order) VALUES (?,?)",
            (norm, next_order),
        )
        return {"id": cur.lastrowid, "path": norm, "created": True}


@app.delete("/api/global-script-dirs/{dir_id}")
def delete_global_script_dir(dir_id: int):
    with db.get_conn() as conn:
        dir_row = conn.execute(
            "SELECT * FROM global_script_dirs WHERE id=?", (dir_id,)
        ).fetchone()
        if not dir_row:
            raise HTTPException(404, detail={"key": "err.scriptDirNotFound"})
        affected = conn.execute(
            "SELECT id, script_file FROM actions WHERE script_dir_id=?", (dir_id,)
        ).fetchall()
        converted = 0
        for act in affected:
            sf = act["script_file"]
            if sf:
                p = Path(sf)
                abs_path = str(p if p.is_absolute() else (Path(dir_row["path"]) / p))
                conn.execute(
                    "UPDATE actions SET script_dir_id=NULL, script_file=? WHERE id=?",
                    (abs_path, act["id"]),
                )
                converted += 1
            else:
                conn.execute("UPDATE actions SET script_dir_id=NULL WHERE id=?", (act["id"],))
        conn.execute("DELETE FROM global_script_dirs WHERE id=?", (dir_id,))
    return {"ok": True, "converted": converted}


@app.get("/api/global-script-dirs/{dir_id}/scan")
def scan_global_script_dir(dir_id: int):
    with db.get_conn() as conn:
        dir_row = conn.execute(
            "SELECT * FROM global_script_dirs WHERE id=?", (dir_id,)
        ).fetchone()
        if not dir_row:
            raise HTTPException(404, detail={"key": "err.scriptDirNotFound"})
        scripts_dir = Path(dir_row["path"])
        if not scripts_dir.is_dir():
            raise HTTPException(400, detail={"key": "err.scriptsDirMissing", "params": {"dir": str(scripts_dir)}})
        added = {
            r["script_file"]
            for r in conn.execute(
                "SELECT script_file FROM actions"
                " WHERE project_id IS NULL AND script_dir_id=? AND script_file IS NOT NULL",
                (dir_id,),
            )
        }
    files = sorted(
        p.name for p in scripts_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SCRIPT_EXTS
    )
    return [{"file": f, "added": f in added} for f in files]


# ---------- project & global actions ----------

@app.get("/api/projects/{project_id}/actions")
def list_actions(project_id: int):
    get_project(project_id)
    with db.get_conn() as conn:
        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM actions WHERE project_id=? ORDER BY sort_order, id", (project_id,))]
        links: dict[int, list] = {}
        for r in conn.execute(
            "SELECT l.action_id, l.service_id, l.disable_when"
            " FROM action_services l JOIN actions a ON a.id = l.action_id"
            " WHERE a.project_id=?", (project_id,)
        ):
            links.setdefault(r["action_id"], []).append(
                {"service_id": r["service_id"], "disable_when": r["disable_when"]})
    return [_format_action_row(a, services=links.get(a["id"], [])) for a in actions]


@app.post("/api/projects/{project_id}/actions")
def create_action(project_id: int, body: ActionIn):
    get_project(project_id)
    body.validate_source()
    body.validate_execution()
    confirm_msg = _norm_confirm_message(body.confirm_message)
    script_file = body.script_file.strip() if body.script_file else None
    command = body.command.strip() if body.command else None
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO actions (project_id, script_dir_id, script_file, command, arguments, execution_mode, run_as_admin, confirm_before_run, confirm_message, label, workdir, category, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, None, script_file, command, body.arguments, body.execution_mode, int(body.run_as_admin),
             int(body.confirm_before_run), confirm_msg, body.label, body.workdir, body.category, body.sort_order),
        )
        _replace_links(conn, cur.lastrowid, body.services)
        return {"id": cur.lastrowid}


@app.get("/api/global-actions")
def list_global_actions(project_id: int | None = None):
    if project_id is not None:
        get_project(project_id)
    with db.get_conn() as conn:
        actions = [dict(r) for r in conn.execute(
            "SELECT a.*, d.path AS script_dir_path"
            " FROM actions a LEFT JOIN global_script_dirs d ON d.id = a.script_dir_id"
            " WHERE a.project_id IS NULL ORDER BY a.sort_order, a.id"
        )]
        hidden_ids: set[int] = set()
        if project_id is not None:
            hidden_ids = {
                r["action_id"]
                for r in conn.execute(
                    "SELECT action_id FROM project_hidden_actions WHERE project_id=?",
                    (project_id,),
                )
            }
    return [
        _format_action_row(a, services=[], hidden=(a["id"] in hidden_ids))
        for a in actions
    ]


@app.post("/api/global-actions")
def create_global_action(body: ActionIn):
    body.validate_source()
    body.validate_execution()
    confirm_msg = _norm_confirm_message(body.confirm_message)
    script_file = body.script_file.strip() if body.script_file else None
    command = body.command.strip() if body.command else None
    script_dir_id = None if command else body.script_dir_id
    with db.get_conn() as conn:
        _validate_global_script(conn, body)
        cur = conn.execute(
            "INSERT INTO actions (project_id, script_dir_id, script_file, command, arguments, execution_mode, run_as_admin, confirm_before_run, confirm_message, label, workdir, category, sort_order)"
            " VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
            (script_dir_id, script_file, command, body.arguments, body.execution_mode, int(body.run_as_admin),
             int(body.confirm_before_run), confirm_msg, body.label, body.workdir, body.category, body.sort_order),
        )
        return {"id": cur.lastrowid}


@app.put("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionIn):
    body.validate_source()
    body.validate_execution()
    confirm_msg = _norm_confirm_message(body.confirm_message)
    script_file = body.script_file.strip() if body.script_file else None
    command = body.command.strip() if body.command else None
    with db.get_conn() as conn:
        existing = conn.execute(
            "SELECT id, project_id FROM actions WHERE id=?", (action_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, detail={"key": "err.actionNotFound"})
        is_global = existing["project_id"] is None
        script_dir_id = None
        if is_global:
            _validate_global_script(conn, body)
            if not command:
                script_dir_id = body.script_dir_id
        conn.execute(
            "UPDATE actions SET script_dir_id=?, script_file=?, command=?, arguments=?, execution_mode=?, run_as_admin=?, confirm_before_run=?, confirm_message=?, label=?, workdir=?, category=?, sort_order=?"
            " WHERE id=?",
            (script_dir_id, script_file, command, body.arguments, body.execution_mode, int(body.run_as_admin),
             int(body.confirm_before_run), confirm_msg, body.label, body.workdir, body.category, body.sort_order, action_id),
        )
        if is_global:
            conn.execute("DELETE FROM action_services WHERE action_id=?", (action_id,))
        else:
            _replace_links(conn, action_id, body.services)
    return {"ok": True}


@app.delete("/api/actions/{action_id}")
def delete_action(action_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM actions WHERE id=?", (action_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, detail={"key": "err.actionNotFound"})
    return {"ok": True}


@app.put("/api/projects/{project_id}/hidden-actions/{action_id}")
def set_hidden_action(project_id: int, action_id: int, body: ActionVisibilityIn):
    get_project(project_id)
    with db.get_conn() as conn:
        act = conn.execute(
            "SELECT id, project_id FROM actions WHERE id=?", (action_id,)
        ).fetchone()
        if not act:
            raise HTTPException(404, detail={"key": "err.actionNotFound"})
        if act["project_id"] is not None:
            raise HTTPException(400, detail={"key": "err.notGlobalAction"})
        if body.hidden:
            conn.execute(
                "INSERT OR IGNORE INTO project_hidden_actions (project_id, action_id) VALUES (?,?)",
                (project_id, action_id),
            )
        else:
            conn.execute(
                "DELETE FROM project_hidden_actions WHERE project_id=? AND action_id=?",
                (project_id, action_id),
            )
    return {"ok": True, "hidden": body.hidden}


def _reorder_categories_scope(conn, project_id: int | None, categories: list[str | None]):
    if project_id is None:
        actions = [dict(r) for r in conn.execute(
            "SELECT id, category, sort_order FROM actions WHERE project_id IS NULL ORDER BY sort_order, id"
        )]
    else:
        actions = [dict(r) for r in conn.execute(
            "SELECT id, category, sort_order FROM actions WHERE project_id=? ORDER BY sort_order, id",
            (project_id,),
        )]
    groups: dict[str | None, list[dict]] = {}
    for a in actions:
        cat = _norm_category(a["category"])
        groups.setdefault(cat, []).append(a)

    ordered_keys: list[str | None] = []
    for c in categories:
        norm_c = _norm_category(c)
        if norm_c not in ordered_keys:
            ordered_keys.append(norm_c)

    for cat in groups.keys():
        if cat not in ordered_keys:
            ordered_keys.append(cat)

    current_sort = 10
    for cat in ordered_keys:
        for act in groups.get(cat, []):
            conn.execute(
                "UPDATE actions SET sort_order=? WHERE id=?",
                (current_sort, act["id"]),
            )
            current_sort += 10
        current_sort += 10


def _rename_category_scope(
    conn, project_id: int | None, old_category: str | None, new_category: str | None
) -> dict:
    old_cat = _norm_category(old_category)
    new_cat = _norm_category(new_category)
    if project_id is None:
        actions = [dict(r) for r in conn.execute(
            "SELECT id, category, sort_order FROM actions WHERE project_id IS NULL ORDER BY sort_order, id"
        )]
    else:
        actions = [dict(r) for r in conn.execute(
            "SELECT id, category, sort_order FROM actions WHERE project_id=? ORDER BY sort_order, id",
            (project_id,),
        )]
    groups: dict[str | None, list[dict]] = {}
    for a in actions:
        cat = _norm_category(a["category"])
        groups.setdefault(cat, []).append(a)

    source_actions = groups.get(old_cat, [])
    if not source_actions:
        return {"ok": True, "updated": 0, "merged": False}

    if old_cat == new_cat:
        for act in source_actions:
            if act["category"] != new_cat:
                conn.execute(
                    "UPDATE actions SET category=? WHERE id=?",
                    (new_cat, act["id"]),
                )
        return {"ok": True, "updated": 0, "merged": False}

    merged = new_cat in groups
    for act in source_actions:
        conn.execute(
            "UPDATE actions SET category=? WHERE id=?",
            (new_cat, act["id"]),
        )

    if merged:
        current_sort = 10
        for cat, cat_actions in groups.items():
            if cat == old_cat:
                continue
            ordered_group = cat_actions + source_actions if cat == new_cat else cat_actions
            for act in ordered_group:
                conn.execute(
                    "UPDATE actions SET sort_order=? WHERE id=?",
                    (current_sort, act["id"]),
                )
                current_sort += 10
            current_sort += 10

    return {"ok": True, "updated": len(source_actions), "merged": merged}


@app.post("/api/projects/{project_id}/categories/reorder")
def reorder_categories(project_id: int, body: CategoryReorderIn):
    get_project(project_id)
    with db.get_conn() as conn:
        _reorder_categories_scope(conn, project_id, body.categories)
    return {"ok": True}


@app.post("/api/projects/{project_id}/categories/rename")
def rename_category(project_id: int, body: CategoryRenameIn):
    get_project(project_id)
    with db.get_conn() as conn:
        return _rename_category_scope(conn, project_id, body.old_category, body.new_category)


@app.post("/api/global-actions/categories/reorder")
def reorder_global_categories(body: CategoryReorderIn):
    with db.get_conn() as conn:
        _reorder_categories_scope(conn, None, body.categories)
    return {"ok": True}


@app.post("/api/global-actions/categories/rename")
def rename_global_category(body: CategoryRenameIn):
    with db.get_conn() as conn:
        return _rename_category_scope(conn, None, body.old_category, body.new_category)


# ---------- run (SSE) ----------

@app.post("/api/actions/{action_id}/run")
async def run_action(action_id: int, body: RunActionIn = Body(default_factory=RunActionIn)):
    # POST + JSON body：跨來源時瀏覽器必先 preflight，惡意網頁無法直接觸發執行
    with db.get_conn() as conn:
        action = conn.execute(
            "SELECT a.*, d.path AS script_dir_path"
            " FROM actions a LEFT JOIN global_script_dirs d ON d.id = a.script_dir_id"
            " WHERE a.id=?",
            (action_id,),
        ).fetchone()
    if not action:
        raise HTTPException(404, detail={"key": "err.actionNotFound"})
    action = dict(action)
    is_global = action["project_id"] is None
    if is_global:
        if body.project_id is None:
            raise HTTPException(400, detail={"key": "err.projectRequiredForGlobal"})
        project = get_project(body.project_id)
    else:
        project = get_project(action["project_id"])

    def ev(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def event_stream():
        env = None
        try:
            if action["command"]:
                cmd = runner.resolve_shell_command(action["command"])
                env = runner.venv_env(project)
            else:
                if is_global:
                    if action["script_dir_id"] is not None:
                        if not action["script_dir_path"]:
                            yield ev("error", {"key": "err.scriptDirNotFound", "params": {}})
                            return
                        script_path = Path(action["script_dir_path"]) / action["script_file"]
                    else:
                        script_path = Path(action["script_file"])
                    env = runner.venv_env(project)
                else:
                    script_path = Path(project["path"]) / project["scripts_dir"] / action["script_file"]
                if not script_path.is_file():
                    yield ev("error", {"key": "err.scriptNotFound", "params": {"path": str(script_path)}})
                    return
                cmd = runner.resolve_command(
                    script_path, project, allow_system_python=is_global
                )
                cmd.extend(runner.parse_arguments(action["arguments"]))
        except runner.RunError as e:
            yield ev("error", {"key": e.key, "params": e.params})
            return
        cwd = runner.resolve_workdir(action["workdir"], project["path"])
        if not Path(cwd).is_dir():
            yield ev("error", {"key": "err.workdirMissing", "params": {"path": cwd}})
            return
        run_as_admin = bool(action.get("run_as_admin"))
        if run_as_admin and action["execution_mode"] != "terminal":
            yield ev("error", {"key": "err.adminRequiresTerminal", "params": {}})
            return
        yield ev("start", {"cmd": cmd, "cwd": cwd})
        if action["execution_mode"] == "terminal":
            try:
                await asyncio.to_thread(
                    runner.launch_external_terminal, cmd, cwd, env, run_as_admin=run_as_admin
                )
                yield ev("terminal", {"run_as_admin": run_as_admin})
            except runner.RunError as e:
                yield ev("error", {"key": e.key, "params": e.params})
            return
        try:
            async for kind, payload in runner.stream_run(cmd, cwd, env):
                if kind == "line":
                    yield ev("line", payload)
                else:
                    yield ev("done", {"exit_code": payload})
        except runner.RunError as e:
            yield ev("error", {"key": e.key, "params": e.params})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------- pick directory / file ----------

async def _run_picker(
    code: str, initialdir: str, title: str, *, unavail_key: str, failed_key: str
) -> dict:
    """用短命子行程開啟系統原生資料夾或檔案選擇視窗。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            initialdir, title,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError as e:
        raise HTTPException(500, detail={"key": failed_key, "params": {"detail": str(e)}})
    if proc.returncode != 0:
        detail = err.decode("utf-8", "replace").strip()[-300:]
        raise HTTPException(500, detail={"key": unavail_key, "params": {"detail": detail}})
    path = out.decode("utf-8", errors="replace").strip()
    return {"path": path or None}


@app.post("/api/pick-directory")
async def pick_directory(body: PickDirIn):
    """開系統原生資料夾選擇視窗，回傳選定的絕對路徑（取消回 null）。"""
    return await _run_picker(
        _PICK_DIR_CODE,
        body.initialdir or "",
        body.title or "Select folder",
        unavail_key="err.pickerUnavailable",
        failed_key="err.pickerFailed",
    )


@app.post("/api/pick-file")
async def pick_file(body: PickFileIn):
    """開系統原生檔案選擇視窗，回傳選定的腳本絕對路徑（取消回 null）。"""
    return await _run_picker(
        _PICK_FILE_CODE,
        body.initialdir or "",
        body.title or "Select script file",
        unavail_key="err.filePickerUnavailable",
        failed_key="err.filePickerFailed",
    )


# ---------- health ----------

@app.get("/health")
def health():
    # 免 token（不在 /api/ 下）：供啟動腳本確認 port 上是不是 devdeck 本尊
    return {"app": "devdeck"}


# ---------- shutdown ----------

@app.post("/api/shutdown")
async def shutdown():
    # 本機小工具，直接結束程序即可；延遲一下讓回應先送出
    asyncio.get_running_loop().call_later(0.3, os._exit, 0)
    return {"ok": True}


# ---------- static ----------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico_path = STATIC_DIR / "favicon.ico"
    if ico_path.exists():
        return FileResponse(ico_path)
    return Response(status_code=404)
