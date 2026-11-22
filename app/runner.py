"""腳本執行：依副檔名分派直譯器，非同步串流輸出。"""

import asyncio
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
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


def resolve_workdir(workdir: str | None, project_path: str) -> str:
    """解析工作目錄：留空回傳專案路徑；相對路徑解析為 project_path / workdir。"""
    cleaned = (workdir or "").strip()
    if not cleaned:
        return project_path
    p = Path(cleaned)
    if p.is_absolute():
        return str(p)
    return str(Path(project_path) / p)


def _system_python() -> str | None:
    if sys.platform == "win32":
        return shutil.which("python") or shutil.which("python3")
    return shutil.which("python3") or shutil.which("python")


def resolve_command(
    script_path: Path, project, *, allow_system_python: bool = False
) -> list[str]:
    ext = script_path.suffix.lower()
    if ext == ".ps1":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise RunError("err.noPwsh")
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    if ext == ".py":
        python = _venv_python(project)
        if python.exists():
            return [str(python), str(script_path)]
        if allow_system_python:
            sys_python = _system_python()
            if sys_python:
                return [sys_python, str(script_path)]
            raise RunError("err.noPython")
        raise RunError("err.noVenvPython", python=str(python))
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


def parse_arguments(arguments: str | None) -> list[str]:
    """將設定中的引數文字拆為 argv；引號可保留含空白的單一引數。"""
    if not arguments or not arguments.strip():
        return []
    try:
        return shlex.split(arguments)
    except ValueError as e:
        raise RunError("err.invalidArguments", detail=str(e)) from e


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


def _powershell_literal(value: str) -> str:
    """將單一 argv 元素轉為 PowerShell 單引號字串。"""
    return "'" + value.replace("'", "''") + "'"


def _build_win_terminal_command(
    cmd: list[str], cwd: str, env: dict | None = None, inject_venv: bool = False
) -> str:
    """組合 Windows 外部終端機執行指令；UAC 提權時可內嵌專案 venv 環境變數。"""
    parts: list[str] = []
    if inject_venv and env and env.get("VIRTUAL_ENV"):
        venv_dir = env["VIRTUAL_ENV"]
        venv_bin = str(Path(venv_dir) / "Scripts")
        parts.append(f"$env:VIRTUAL_ENV = {_powershell_literal(venv_dir)}")
        parts.append(f"$env:PATH = {_powershell_literal(venv_bin)} + ';' + $env:PATH")
    parts.append(f"Set-Location -LiteralPath {_powershell_literal(cwd)}")
    parts.append("& " + " ".join(_powershell_literal(arg) for arg in cmd))
    return "; ".join(parts)


def _encode_powershell_command(script: str) -> str:
    """將 PowerShell 腳本轉為 -EncodedCommand 所需的 UTF-16LE Base64 字串。"""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _shell_execute_runas(executable: str, parameters: str, cwd: str) -> None:
    """透過 Win32 ShellExecuteExW(runas) 觸發原生 UAC 提權啟動外部終端機。"""
    import ctypes
    from ctypes import wintypes

    class _SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_FLAG_NO_UI = 0x00000400
    SW_SHOWNORMAL = 1
    ERROR_CANCELLED = 1223
    COINIT_APARTMENTTHREADED = 0x2
    COINIT_DISABLE_OLE1DDE = 0x4
    S_OK = 0
    S_FALSE = 1

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL

    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE)
    need_uninit = hr in (S_OK, S_FALSE)
    try:
        sei = _SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
        sei.fMask = SEE_MASK_FLAG_NO_UI
        sei.lpVerb = "runas"
        sei.lpFile = executable
        sei.lpParameters = parameters
        sei.lpDirectory = cwd
        sei.nShow = SW_SHOWNORMAL
        if not shell32.ShellExecuteExW(ctypes.byref(sei)):
            err_code = ctypes.get_last_error()
            if err_code == ERROR_CANCELLED:
                raise RunError("err.adminCancelled")
            raise RunError("err.spawnFailed", detail=str(ctypes.WinError(err_code)))
    finally:
        if need_uninit:
            ole32.CoUninitialize()


def launch_external_terminal(
    cmd: list[str], cwd: str, env: dict | None = None, run_as_admin: bool = False
):
    """在可互動的外部終端機執行命令，不接管其 stdin/stdout。"""
    try:
        if sys.platform == "win32":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                raise RunError("err.noPwsh")
            if run_as_admin:
                ps_script = _build_win_terminal_command(cmd, cwd, env, inject_venv=True)
                encoded = _encode_powershell_command(ps_script)
                _shell_execute_runas(shell, f"-NoExit -EncodedCommand {encoded}", cwd)
                return
            command = _build_win_terminal_command(cmd, cwd)
            subprocess.Popen(
                [shell, "-NoExit", "-Command", command],
                cwd=cwd,
                env=env,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return
        if sys.platform == "darwin":
            if run_as_admin:
                env_pairs = (
                    [f"{key}={env[key]}" for key in ("PATH", "VIRTUAL_ENV") if env.get(key)]
                    if env else []
                )
                exec_cmd = ["sudo", "--", "env", *env_pairs, *cmd] if env_pairs else ["sudo", "--", *cmd]
            else:
                exec_cmd = cmd
            command = f"cd {shlex.quote(cwd)} && {shlex.join(exec_cmd)}"
            if env:
                exports = [
                    f"export {key}={shlex.quote(env[key])}"
                    for key in ("PATH", "VIRTUAL_ENV") if env.get(key)
                ]
                command = "; ".join(exports + [command])
            script = f'tell application "Terminal" to do script {json.dumps(command)}'
            subprocess.Popen(["osascript", "-e", script], cwd=cwd, env=env)
            return
    except OSError as e:
        raise RunError("err.spawnFailed", detail=str(e)) from e
    raise RunError("err.noExternalTerminal")


def _build_win_shell_command(
    cwd: str, env: dict | None = None, inject_venv: bool = False
) -> str:
    """組合 Windows 開啟互動式外部終端機的 PowerShell 指令。"""
    parts: list[str] = []
    if inject_venv and env and env.get("VIRTUAL_ENV"):
        venv_dir = env["VIRTUAL_ENV"]
        venv_bin = str(Path(venv_dir) / "Scripts")
        parts.append(f"$env:VIRTUAL_ENV = {_powershell_literal(venv_dir)}")
        parts.append(f"$env:PATH = {_powershell_literal(venv_bin)} + ';' + $env:PATH")
    parts.append(f"Set-Location -LiteralPath {_powershell_literal(cwd)}")
    return "; ".join(parts)


def open_external_terminal(
    cwd: str, env: dict | None = None, run_as_admin: bool = False
) -> None:
    """以指定工作目錄開啟互動式外部終端機。"""
    try:
        if sys.platform == "win32":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                raise RunError("err.noPwsh")
            if run_as_admin:
                ps_script = _build_win_shell_command(cwd, env, inject_venv=True)
                encoded = _encode_powershell_command(ps_script)
                _shell_execute_runas(shell, f"-NoExit -EncodedCommand {encoded}", cwd)
                return
            ps_script = _build_win_shell_command(cwd)
            subprocess.Popen(
                [shell, "-NoExit", "-Command", ps_script],
                cwd=cwd,
                env=env,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return
        if sys.platform == "darwin":
            exports = (
                [
                    f"export {key}={shlex.quote(env[key])}"
                    for key in ("PATH", "VIRTUAL_ENV")
                    if env.get(key)
                ]
                if env
                else []
            )
            if run_as_admin:
                env_pairs = (
                    [
                        f"{key}={env[key]}"
                        for key in ("PATH", "VIRTUAL_ENV")
                        if env.get(key)
                    ]
                    if env
                    else []
                )
                login_shell = os.environ.get("SHELL") or "/bin/zsh"
                sudo_cmd = (
                    ["sudo", "--", "env", *env_pairs, login_shell]
                    if env_pairs
                    else ["sudo", "-s"]
                )
                command = f"cd {shlex.quote(cwd)} && {shlex.join(sudo_cmd)}"
            else:
                command = f"cd {shlex.quote(cwd)}"
            if exports:
                command = "; ".join(exports + [command])
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    'tell application "Terminal"',
                    "-e",
                    "activate",
                    "-e",
                    f"do script {json.dumps(command)}",
                    "-e",
                    "end tell",
                ],
                cwd=cwd,
                env=env,
            )
            return
    except OSError as e:
        raise RunError("err.spawnFailed", detail=str(e)) from e
    raise RunError("err.noExternalTerminal")


def _list_win_explorer_windows() -> list[tuple[int, str]]:
    """列舉目前可見的 Windows 檔案總管（CabinetWClass）視窗。"""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        windows: list[tuple[int, str]] = []
        cls_buf = ctypes.create_unicode_buffer(64)

        @WNDENUMPROC
        def _enum_cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetClassNameW(hwnd, cls_buf, 64) > 0 and cls_buf.value == "CabinetWClass":
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    title_buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, title_buf, length + 1)
                    title = title_buf.value
                windows.append((int(hwnd), title))
            return True

        user32.EnumWindows(_enum_cb, 0)
        return windows
    except Exception:
        return []


def _bring_win_window_to_front(hwnd: int) -> None:
    """將指定 Windows 視窗帶到前景，避免僅在工作列閃爍。"""
    import ctypes
    from ctypes import wintypes

    SW_SHOW = 5
    SW_RESTORE = 9
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040
    HWND_TOPMOST = wintypes.HWND(-1)
    HWND_NOTOPMOST = wintypes.HWND(-2)

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    target = wintypes.HWND(hwnd)
    if user32.IsIconic(target):
        user32.ShowWindow(target, SW_RESTORE)
    else:
        user32.ShowWindow(target, SW_SHOW)

    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
    cur_tid = kernel32.GetCurrentThreadId()
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        user32.SetWindowPos(target, HWND_TOPMOST, 0, 0, 0, 0, flags)
        try:
            user32.BringWindowToTop(target)
            user32.SetForegroundWindow(target)
        finally:
            user32.SetWindowPos(target, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def _focus_win_explorer_after_open(
    path: str,
    before: list[tuple[int, str]],
    timeout: float = 1.5,
    poll_interval: float = 0.05,
) -> None:
    """背景輪詢剛開啟或切換分頁的檔案總管視窗，並將其帶到前景。"""
    try:
        before_map = dict(before)
        norm = os.path.normpath(path)
        target_hint = (Path(norm).name or norm.rstrip("\\")).lower()
        deadline = time.monotonic() + timeout
        start = time.monotonic()

        while time.monotonic() < deadline:
            current = _list_win_explorer_windows()
            for hwnd, _title in current:
                if hwnd not in before_map:
                    _bring_win_window_to_front(hwnd)
                    return

            for hwnd, title in current:
                if before_map.get(hwnd) != title and (not target_hint or target_hint in title.lower()):
                    _bring_win_window_to_front(hwnd)
                    return

            if time.monotonic() - start >= 0.35 and target_hint:
                for hwnd, title in current:
                    if target_hint in title.lower():
                        _bring_win_window_to_front(hwnd)
                        return

            time.sleep(poll_interval)
    except Exception:
        pass


def open_folder(path: str) -> None:
    """以系統預設檔案管理員開啟指定資料夾。"""
    try:
        if sys.platform == "win32":
            norm_path = os.path.normpath(path)
            before = _list_win_explorer_windows()
            os.startfile(norm_path)
            threading.Thread(
                target=_focus_win_explorer_after_open,
                args=(norm_path, before),
                daemon=True,
            ).start()
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return
        opener = shutil.which("xdg-open")
        if not opener:
            raise RunError("err.noFileManager")
        subprocess.Popen([opener, path])
    except OSError as e:
        raise RunError("err.spawnFailed", detail=str(e)) from e


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
