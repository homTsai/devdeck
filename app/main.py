"""devdeck — 本機開發腳本啟動面板。只綁 127.0.0.1:7999。"""

import asyncio
import json
import os
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, runner, status

app = FastAPI(title="devdeck")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SCRIPT_EXTS = {".ps1", ".py", ".sh", ".mjs", ".js", ".cmd", ".bat"}

db.init_db()


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


class ActionServiceLink(BaseModel):
    service_id: int
    disable_when: Literal["running", "stopped"]


class ActionIn(BaseModel):
    script_file: str | None = None
    command: str | None = None
    label: str
    services: list[ActionServiceLink] = []
    workdir: str | None = None
    category: str | None = None
    sort_order: int = 0

    def validate_source(self):
        if bool(self.script_file) == bool(self.command):
            raise HTTPException(400, "腳本檔案與直接指令必須擇一填寫")


# ---------- helpers ----------

def get_project(project_id: int) -> dict:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "找不到專案")
    return dict(row)


# ---------- projects ----------

@app.get("/api/projects")
def list_projects():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY name")]


@app.post("/api/projects")
def create_project(body: ProjectIn):
    if not Path(body.path).is_dir():
        raise HTTPException(400, f"專案路徑不存在：{body.path}")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, path, scripts_dir, venv_path) VALUES (?,?,?,?)",
            (body.name, body.path, body.scripts_dir, body.venv_path),
        )
        return {"id": cur.lastrowid}


@app.put("/api/projects/{project_id}")
def update_project(project_id: int, body: ProjectIn):
    get_project(project_id)
    if not Path(body.path).is_dir():
        raise HTTPException(400, f"專案路徑不存在：{body.path}")
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
        raise HTTPException(400, f"腳本目錄不存在：{scripts_dir}")
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
            "INSERT INTO services (project_id, name, port, pid_file) VALUES (?,?,?,?)",
            (project_id, body.name, body.port, body.pid_file),
        )
        return {"id": cur.lastrowid}


@app.put("/api/services/{service_id}")
def update_service(service_id: int, body: ServiceIn):
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE services SET name=?, port=?, pid_file=? WHERE id=?",
            (body.name, body.port, body.pid_file, service_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "找不到服務")
    return {"ok": True}


@app.delete("/api/services/{service_id}")
def delete_service(service_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM services WHERE id=?", (service_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "找不到服務")
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
            "INSERT INTO actions (project_id, script_file, command, label, workdir, category, sort_order)"
            " VALUES (?,?,?,?,?,?,?)",
            (project_id, body.script_file, body.command, body.label,
             body.workdir, body.category, body.sort_order),
        )
        _replace_links(conn, cur.lastrowid, body.services)
        return {"id": cur.lastrowid}


@app.put("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionIn):
    body.validate_source()
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE actions SET script_file=?, command=?, label=?, workdir=?, category=?, sort_order=?"
            " WHERE id=?",
            (body.script_file, body.command, body.label, body.workdir,
             body.category, body.sort_order, action_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "找不到動作")
        _replace_links(conn, action_id, body.services)
    return {"ok": True}


@app.delete("/api/actions/{action_id}")
def delete_action(action_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM actions WHERE id=?", (action_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "找不到動作")
    return {"ok": True}


# ---------- run (SSE) ----------

@app.get("/api/actions/{action_id}/run")
async def run_action(action_id: int):
    with db.get_conn() as conn:
        action = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    if not action:
        raise HTTPException(404, "找不到動作")
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
                    yield ev("error", f"腳本不存在：{script_path}")
                    return
                cmd = runner.resolve_command(script_path, project)
        except runner.RunError as e:
            yield ev("error", str(e))
            return
        cwd = action["workdir"] or project["path"]
        yield ev("start", {"cmd": cmd, "cwd": cwd})
        try:
            async for kind, payload in runner.stream_run(cmd, cwd, env):
                if kind == "line":
                    yield ev("line", payload)
                else:
                    yield ev("done", {"exit_code": payload})
        except runner.RunError as e:
            yield ev("error", str(e))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
