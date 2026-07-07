#!/usr/bin/env bash
# devdeck 啟動腳本（macOS / Linux）：建立/使用自己的 venv，背景啟動伺服器並開啟瀏覽器。
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [ "$(uname)" = "Darwin" ]; then
  DATA_DIR="$HOME/Library/Application Support/devdeck"
else
  DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/devdeck"
fi

# 從 Finder 雙擊（或 launchd）啟動時只會拿到精簡 PATH，動作子行程會找不到
# nvm / Homebrew（含 Apple Silicon 的 /opt/homebrew/bin）裝的 node 等工具。
# 先用登入 shell 解析出使用者的完整 PATH 再帶給背景伺服器，讓不論從終端機或
# Finder 啟動都拿到一致的工具鏈。stdin 導向 /dev/null 避免 rc 讀輸入卡住。
LOGIN_SHELL="${SHELL:-/bin/zsh}"
FULL_PATH="$("$LOGIN_SHELL" -ilc 'printf %s "$PATH"' </dev/null 2>/dev/null || true)"
if [ -n "$FULL_PATH" ]; then
  export PATH="$FULL_PATH"
fi

if [ ! -x "$PYTHON" ]; then
  echo "首次啟動：建立 venv 並安裝相依套件..."
  python3 -m venv "$ROOT/.venv"
  "$PYTHON" -m pip install -q -r "$ROOT/requirements.txt"
fi

# port 由伺服器選定（預設 7999，占用時往下 fallback）並寫入 devdeck.port
get_port() { cat "$DATA_DIR/devdeck.port" 2>/dev/null || echo 7999; }

# 用 /health 確認 port 上是 devdeck 本尊（單純探測 port 可能誤認別的程式）
is_devdeck() {
  curl -s --max-time 2 "http://127.0.0.1:$1/health" 2>/dev/null | grep -q '"app":[[:space:]]*"devdeck"'
}

PORT="$(get_port)"
if ! is_devdeck "$PORT"; then
  cd "$ROOT"
  nohup "$PYTHON" -m app >/dev/null 2>&1 &
  for _ in $(seq 1 20); do
    sleep 0.3
    PORT="$(get_port)"
    if is_devdeck "$PORT"; then break; fi
  done
fi

URL="http://127.0.0.1:$PORT"

# 伺服器啟動時會把 API token 寫到使用者資料目錄，帶在網址上交付給頁面
if [ -s "$DATA_DIR/devdeck.token" ]; then
  URL="$URL/?token=$(tr -d '[:space:]' <"$DATA_DIR/devdeck.token")"
fi

if command -v open >/dev/null 2>&1; then
  open "$URL"          # macOS
else
  xdg-open "$URL"      # Linux
fi
