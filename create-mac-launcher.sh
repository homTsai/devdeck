#!/usr/bin/env bash
# devdeck macOS 啟動器產生器（對應 Windows 的 create-shortcut.ps1）。
#
# 用系統內建的 osacompile 把 start-devdeck.sh 包成 devdeck.app，之後可在
# Spotlight / Launchpad 搜尋、或拖到 Dock，體驗如同原生 app：不閃 Terminal
# 視窗、不會被誤開成編輯器。
#
# 關鍵：這個 app 是在本機「生成」的，不帶 Sourcetree 等工具 clone 時打上的
# 隔離標記（com.apple.quarantine），所以 Gatekeeper 不會跳「無法驗證」對話框。
#
# 用法：
#   ./create-mac-launcher.sh                 # 生成到 ~/Applications/devdeck.app
#   ./create-mac-launcher.sh /Applications   # 指定安裝目錄（第一個參數）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
START_SCRIPT="$ROOT/start-devdeck.sh"

if [ ! -f "$START_SCRIPT" ]; then
  echo "找不到 start-devdeck.sh：$START_SCRIPT" >&2
  exit 1
fi
chmod +x "$START_SCRIPT" 2>/dev/null || true

# 安裝位置：預設 ~/Applications（Spotlight / Launchpad 會收錄，且免 sudo）。
DEST_DIR="${1:-$HOME/Applications}"
mkdir -p "$DEST_DIR"
APP_PATH="$DEST_DIR/devdeck.app"

# 重新生成前先移除舊的，避免殘留舊路徑或圖示
rm -rf "$APP_PATH"

# AppleScript 以絕對路徑呼叫 start-devdeck.sh；quoted form 讓路徑含空白也安全。
# start-devdeck.sh 會自行用登入 shell 重建完整 PATH，故精簡環境下工具鏈仍齊全。
osacompile -o "$APP_PATH" \
  -e "set launcher to \"$START_SCRIPT\"" \
  -e "do shell script quoted form of launcher"

# 若 repo 根目錄放了 devdeck.icns，套用為 app 圖示（沒有就用預設 applet 圖示）。
ICON_SRC="$ROOT/devdeck.icns"
if [ -f "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APP_PATH/Contents/Resources/applet.icns"
  # 觸發 Finder / LaunchServices 重讀圖示
  touch "$APP_PATH"
  echo "已套用圖示：$ICON_SRC"
fi

echo "已生成：$APP_PATH"
echo "在 Spotlight 搜尋 devdeck、或從 $DEST_DIR 把它拖到 Dock 即可啟動。"
