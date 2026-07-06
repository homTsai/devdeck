"""服務狀態偵測：port 探測為主，PID 檔為輔助資訊。"""

import asyncio
import sys
from pathlib import Path


async def port_listening(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=0.5
        )
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def read_pid(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # 注意：Windows 上 os.kill(pid, 0) 會直接殺掉程序，只能用 OpenProcess 查詢
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    import os

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
