"""devdeck 啟動進入點：python -m app

選埠規則：DEVDECK_PORT 環境變數優先；否則從 7999 往下找到 7990；
都被占用則退到隨機臨時埠。實際使用的 port 寫入資料目錄的 devdeck.port，
供啟動腳本組網址。
"""

import os
import socket

import uvicorn

from .main import app
from .paths import data_dir

HOST = "127.0.0.1"


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def pick_port() -> int:
    env = os.environ.get("DEVDECK_PORT")
    if env:
        return int(env)  # 明確指定就不 fallback，占用時讓 uvicorn 直接報錯
    for port in range(7999, 7989, -1):
        if _port_free(port):
            return port
    with socket.socket() as s:  # 最後手段：隨機臨時埠
        s.bind((HOST, 0))
        return s.getsockname()[1]


def main():
    port = pick_port()
    (data_dir() / "devdeck.port").write_text(str(port), encoding="utf-8")
    uvicorn.run(app, host=HOST, port=port)


main()
