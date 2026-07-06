"""腳本執行：依副檔名分派直譯器，非同步串流輸出。"""

import asyncio
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
            raise RunError("找不到 pwsh / powershell")
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    if ext == ".py":
        python = _venv_python(project)
        if not python.exists():
            raise RunError(f"找不到專案 venv 的 python：{python}（請確認專案的 venv 路徑設定）")
        return [str(python), str(script_path)]
    if ext in (".mjs", ".js"):
        node = shutil.which("node")
        if not node:
            raise RunError("找不到 node")
        return [node, str(script_path)]
    if ext == ".sh":
        bash = shutil.which("bash")
        if not bash:
            raise RunError("找不到 bash")
        return [bash, str(script_path)]
    if ext in (".cmd", ".bat"):
        return ["cmd", "/c", str(script_path)]
    raise RunError(f"不支援的副檔名：{ext}")


async def stream_run(cmd: list[str], cwd: str):
    """執行命令，逐行 yield ("line", text)，結束時 yield ("done", exit_code)。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as e:
        raise RunError(f"無法啟動程序：{e}") from e

    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        yield ("line", line.decode("utf-8", errors="replace").rstrip("\r\n"))
    code = await proc.wait()
    yield ("done", code)
