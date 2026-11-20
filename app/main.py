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
    script_file: str | None = None
    command: str | None = None
    arguments: str | None = None
    execution_mode: Literal["panel", "terminal"] = "panel"
    label: str
    services: list[ActionServiceLink] = []
    workdir: str | None = None
    category: str | None = None
    sort_order: int = 0

    def validate_source(self):
        if bool(self.script_file) == bool(self.command):
            raise HTTPException(400, detail={"key": "err.scriptXorCommand"})


class PickDirIn(BaseModel):
    initialdir: str | None = None  # 對話框起始資料夾（如專案路徑）；不存在則忽略
    title: str | None = None       # 對話框標題（由前端依語系帶入）


class CategoryReorderIn(BaseModel):
    categories: list[str | None]


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

def _replace_links(conn, action_id: int, links: list[ActionServiceLink]):
    conn.execute("DELETE FROM action_services WHERE action_id=?", (action_id,))
    for link in links:
        conn.execute(
            "INSERT INTO action_services (action_id, service_id, disable_when) VALUES (?,?,?)",
            (action_id, link.service_id, link.disable_when),
        )


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
    for a in actions:
        a["services"] = links.get(a["id"], [])
    return actions


@app.post("/api/projects/{project_id}/actions")
def create_action(project_id: int, body: ActionIn):
    get_project(project_id)
    body.validate_source()
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO actions (project_id, script_file, command, arguments, execution_mode, label, workdir, category, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, body.script_file, body.command, body.arguments, body.execution_mode, body.label,
             body.workdir, body.category, body.sort_order),
        )
        _replace_links(conn, cur.lastrowid, body.services)
        return {"id": cur.lastrowid}


@app.put("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionIn):
    body.validate_source()
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE actions SET script_file=?, command=?, arguments=?, execution_mode=?, label=?, workdir=?, category=?, sort_order=?"
            " WHERE id=?",
            (body.script_file, body.command, body.arguments, body.execution_mode, body.label, body.workdir,
             body.category, body.sort_order, action_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, detail={"key": "err.actionNotFound"})
        _replace_links(conn, action_id, body.services)
    return {"ok": True}


@app.delete("/api/actions/{action_id}")
def delete_action(action_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM actions WHERE id=?", (action_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, detail={"key": "err.actionNotFound"})
    return {"ok": True}


@app.post("/api/projects/{project_id}/categories/reorder")
def reorder_categories(project_id: int, body: CategoryReorderIn):
    get_project(project_id)
    with db.get_conn() as conn:
        actions = [dict(r) for r in conn.execute(
            "SELECT id, category, sort_order FROM actions WHERE project_id=? ORDER BY sort_order, id",
            (project_id,)
        )]
        groups: dict[str | None, list[dict]] = {}
        for a in actions:
            cat = a["category"].strip() if a["category"] and a["category"].strip() else None
            groups.setdefault(cat, []).append(a)

        ordered_keys: list[str | None] = []
        for c in body.categories:
            norm_c = c.strip() if c and c.strip() else None
            if norm_c not in ordered_keys:
                ordered_keys.append(norm_c)

        for cat in groups.keys():
            if cat not in ordered_keys:
                ordered_keys.append(cat)

        current_sort = 10
        for cat in ordered_keys:
            cat_actions = groups.get(cat, [])
            for act in cat_actions:
                conn.execute(
                    "UPDATE actions SET sort_order=? WHERE id=?",
                    (current_sort, act["id"])
                )
                current_sort += 10
            current_sort += 10
    return {"ok": True}


# ---------- run (SSE) ----------

@app.post("/api/actions/{action_id}/run")
async def run_action(action_id: int, _body: dict = Body(default={})):
    # POST + JSON body：跨來源時瀏覽器必先 preflight，惡意網頁無法直接觸發執行
    with db.get_conn() as conn:
        action = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    if not action:
        raise HTTPException(404, detail={"key": "err.actionNotFound"})
    action = dict(action)
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
                script_path = Path(project["path"]) / project["scripts_dir"] / action["script_file"]
                if not script_path.is_file():
                    yield ev("error", {"key": "err.scriptNotFound", "params": {"path": str(script_path)}})
                    return
                cmd = runner.resolve_command(script_path, project)
                cmd.extend(runner.parse_arguments(action["arguments"]))
        except runner.RunError as e:
            yield ev("error", {"key": e.key, "params": e.params})
            return
        cwd = action["workdir"] or project["path"]
        yield ev("start", {"cmd": cmd, "cwd": cwd})
        if action["execution_mode"] == "terminal":
            try:
                runner.launch_external_terminal(cmd, cwd, env)
                yield ev("terminal", {})
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


# ---------- pick directory ----------

@app.post("/api/pick-directory")
async def pick_directory(body: PickDirIn):
    """開系統原生資料夾選擇視窗，回傳選定的絕對路徑（取消回 null）。

    dialog 在跑 uvicorn 的機器桌面彈出——devdeck 只綁 127.0.0.1，所以就是使用者本機。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _PICK_DIR_CODE,
            body.initialdir or "", body.title or "Select folder",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError as e:
        raise HTTPException(500, detail={"key": "err.pickerFailed", "params": {"detail": str(e)}})
    if proc.returncode != 0:
        # 多半是缺 tkinter（例如 Linux 未安裝 python3-tk）
        detail = err.decode("utf-8", "replace").strip()[-300:]
        raise HTTPException(500, detail={"key": "err.pickerUnavailable", "params": {"detail": detail}})
    path = out.decode("utf-8", errors="replace").strip()
    return {"path": path or None}


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
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico_path = STATIC_DIR / "favicon.ico"
    if ico_path.exists():
        return FileResponse(ico_path)
    return Response(status_code=404)
