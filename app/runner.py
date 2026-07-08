"""腳本執行：依副檔名分派直譯器，非同步串流輸出。"""

import asyncio
import os
import shutil
import sys
from pathlib import Path


class RunError(Exception):
    pass


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
            raise RunError("找不到 pwsh / powershell——請安裝 PowerShell（macOS 需另裝 pwsh）並確認已在 PATH 上；解法詳見 README「疑難排解」。")
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    if ext == ".py":
        python = _venv_python(project)
        if not python.exists():
            raise RunError(f"找不到專案 venv 的 python：{python}——請確認專案設定的 venv 路徑正確，或先在專案目錄建立 venv；解法詳見 README「疑難排解」。")
        return [str(python), str(script_path)]
    if ext in (".mjs", ".js"):
        node = shutil.which("node")
        if not node:
            raise RunError("找不到 node——請安裝 Node.js 並確認 node 已在 PATH 上；macOS 從 Finder 啟動時 PATH 較精簡，解法詳見 README「疑難排解」。")
        return [node, str(script_path)]
    if ext == ".sh":
        bash = shutil.which("bash")
        if not bash:
            raise RunError("找不到 bash——請安裝 bash（Windows 可用 Git Bash）並確認已在 PATH 上；解法詳見 README「疑難排解」。")
        return [bash, str(script_path)]
    if ext in (".cmd", ".bat"):
        return ["cmd", "/c", str(script_path)]
    raise RunError(f"不支援的副檔名：{ext}")


def resolve_shell_command(command: str) -> list[str]:
    """直接指令型動作：交給 shell 執行。"""
    if sys.platform == "win32":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise RunError("找不到 pwsh / powershell——請安裝 PowerShell（macOS 需另裝 pwsh）並確認已在 PATH 上；解法詳見 README「疑難排解」。")
        return [shell, "-NoProfile", "-Command", command]
    bash = shutil.which("bash")
    if not bash:
        raise RunError("找不到 bash——請安裝 bash（Windows 可用 Git Bash）並確認已在 PATH 上；解法詳見 README「疑難排解」。")
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
        raise RunError(f"無法啟動程序：{e}") from e

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
