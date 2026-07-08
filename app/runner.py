"""腳本執行：依副檔名分派直譯器，非同步串流輸出。"""

import asyncio
import os
import shutil
import sys
from pathlib import Path


class RunError(Exception):
    """執行前置錯誤：只帶 i18n error key 與參數；面向使用者的文字由前端依語系用 t() 組出。"""

    def __init__(self, key: str, **params):
        self.key = key
        self.params = params
        super().__init__(key)


def _venv_python(project) -> Path:
    venv = Path(project["path"]) / project["venv_path"]
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def resolve_command(script_path: Path, project) -> list[str]:
    ext = script_path.suffix.lower()
    if ext == ".ps1":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise RunError("err.noPwsh")
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    if ext == ".py":
        python = _venv_python(project)
        if not python.exists():
            raise RunError("err.noVenvPython", python=str(python))
        return [str(python), str(script_path)]
    if ext in (".mjs", ".js"):
        node = shutil.which("node")
        if not node:
            raise RunError("err.noNode")
        return [node, str(script_path)]
    if ext == ".sh":
        bash = shutil.which("bash")
        if not bash:
            raise RunError("err.noBash")
        return [bash, str(script_path)]
    if ext in (".cmd", ".bat"):
        return ["cmd", "/c", str(script_path)]
    raise RunError("err.unsupportedExt", ext=ext)


def resolve_shell_command(command: str) -> list[str]:
    """直接指令型動作：交給 shell 執行。"""
    if sys.platform == "win32":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise RunError("err.noPwsh")
        return [shell, "-NoProfile", "-Command", command]
    bash = shutil.which("bash")
    if not bash:
        raise RunError("err.noBash")
    return [bash, "-lc", command]


def venv_env(project) -> dict:
    """把專案 venv 掛進 PATH，讓直接指令能用到 venv 內的 alembic / python 等工具。"""
    env = os.environ.copy()
    venv = Path(project["path"]) / project["venv_path"]
    if venv.is_dir():
        bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(venv)
    return env


async def stream_run(cmd: list[str], cwd: str, env: dict | None = None):
    """執行命令，逐行 yield ("line", text)，結束時 yield ("done", exit_code)。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as e:
        raise RunError("err.spawnFailed", detail=str(e)) from e

    assert proc.stdout is not None
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield ("line", line.decode("utf-8", errors="replace").rstrip("\r\n"))
        code = await proc.wait()
        yield ("done", code)
    finally:
        # SSE 客戶端斷線時，這個產生器會被提前關閉；別讓前景子行程變孤兒。
        # 只終止直接子行程——腳本自己 nohup 出去的背景服務不受影響。
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            except ProcessLookupError:
                pass
