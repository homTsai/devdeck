"""跨平台的使用者資料目錄與舊位置遷移。"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "devdeck"

# 舊版資料位置（程式目錄旁），僅供一次性遷移偵測
APP_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def migrate_legacy_file(name: str) -> Path:
    """舊位置（程式目錄旁）有、新位置沒有 → 搬過去。回傳新路徑。"""
    new = data_dir() / name
    old = APP_ROOT / name
    if old.is_file() and not new.exists():
        shutil.move(str(old), str(new))  # 可能跨磁碟（repo 與使用者目錄不同槽）
    return new
