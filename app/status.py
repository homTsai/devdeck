"""服務狀態偵測：port 探測為主，PID 檔為輔助資訊。"""

import asyncio
import sys
from pathlib import Path


async def _can_connect(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def port_listening(port: int, timeout: float = 0.25) -> bool:
    # 同時探測 IPv4 (127.0.0.1) 與 IPv6 (::1)，任一先連上即短路回傳，避免被未監聽協定卡滿 timeout
    tasks = [
        asyncio.create_task(_can_connect("127.0.0.1", port, timeout=timeout)),
        asyncio.create_task(_can_connect("::1", port, timeout=timeout)),
    ]
    try:
        for done in asyncio.as_completed(tasks):
            try:
                if await done:
                    return True
            except Exception:
                pass
        return False
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
