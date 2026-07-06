#!/usr/bin/env bash
# devdeck 啟動腳本（macOS / Linux）：建立/使用自己的 venv，背景啟動伺服器並開啟瀏覽器。
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
URL="http://127.0.0.1:7999"

if [ ! -x "$PYTHON" ]; then
  echo "首次啟動：建立 venv 並安裝相依套件..."
  python3 -m venv "$ROOT/.venv"
  "$PYTHON" -m pip install -q -r "$ROOT/requirements.txt"
fi

port_up() { (echo -n >/dev/tcp/127.0.0.1/7999) 2>/dev/null; }

if ! port_up; then
  cd "$ROOT"
  nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 7999 >/dev/null 2>&1 &
  for _ in $(seq 1 20); do
    if port_up; then break; fi
    sleep 0.3
  done
fi

if command -v open >/dev/null 2>&1; then
  open "$URL"          # macOS
else
  xdg-open "$URL"      # Linux
fi
