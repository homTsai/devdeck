# devdeck

[繁體中文](#繁體中文) | [English](#english)

---

## 繁體中文

本機開發腳本啟動面板：把各專案 `scripts/` 目錄裡的腳本設定成按鈕，點擊即執行、即時看輸出，
常駐服務（FastAPI / Vite）以 port 探測顯示運行狀態燈。

### 啟動與關閉

Windows：

```powershell
.\start-devdeck.ps1      # 啟動（背景執行、無視窗）並開啟瀏覽器
.\create-shortcut.ps1    # 建立開始功能表捷徑（執行一次即可）
```

macOS / Linux：

```bash
./start-devdeck.sh       # 同上；macOS 也可在 Finder 雙擊 devdeck.command（可拖到 Dock）
```

首次執行會自動建立 `.venv` 並安裝相依套件，之後開啟 <http://127.0.0.1:7999>。
伺服器在背景執行、不顯示視窗；若已在執行，再次啟動只會開啟瀏覽器。

Port 預設 `7999`；被其他程式占用時自動往下改用 `7998`–`7990`（實際 port 記錄在資料目錄的
`devdeck.port`，啟動腳本會自動讀取，並以 `/health` 端點確認是 devdeck 本尊而非別的程式）。
也可用環境變數 `DEVDECK_PORT` 明確指定（指定後不做 fallback）。

Windows 建立捷徑後，可在開始功能表搜尋 **devdeck**，右鍵「釘選到開始畫面」或「釘選到工作列」。

關閉：面板右上角「關閉工具」按鈕會停止 devdeck 伺服器（不影響已啟動的專案服務）。

若頁面顯示「驗證失效」（例如清除過瀏覽器資料），重新點一次啟動捷徑即可重新取得授權。

### 使用流程

1. **新增專案**：設定專案名稱、路徑、腳本目錄（預設 `scripts`）、venv 路徑（預設 `.venv`）。
2. **編輯專案**內可加入**服務**（名稱 + port + 選填 PID 檔），例如 `fastapi :8000`、`vite :5173`，
   面板上方會顯示各服務的狀態燈（port 有人聽 = 綠燈）。勾選「**開網頁**」的服務會多一個
   「開啟 ↗」連結，直接開 `http://localhost:{port}` 首頁（服務停止時連結變暗但仍可點）；
   不是網頁的 port 不勾即可。
3. **新增動作**：兩種類型擇一——
   - **腳本檔案**：從腳本目錄掃描結果挑選；
   - **直接指令**：直接輸入指令（如 `alembic upgrade head`），會在工作目錄以 shell 執行，
     且專案 venv 已掛入 PATH（指令可直接使用 venv 內的 alembic / python 等工具）。

   再設定顯示名稱、分類、工作目錄（預設專案路徑），並可勾選**按鈕狀態關聯**：
   對每個勾選的服務選擇「運行中時停用」或「停止時停用」，勾選的條件**全部成立**時該按鈕會停用
   （例：start 按鈕勾 fastapi「運行中時停用」→ 服務在跑就按不了；dev stop 勾兩個服務
   「停止時停用」→ 兩個都停了才鎖住，只剩一個在跑仍可按）。
4. 日常使用：選專案 → 點按鈕 → 下方面板即時串流輸出。
5. 勾選右上角**管理模式**才會顯示編輯/刪除按鈕，避免誤觸。

### 設計說明

- 設定資料（`devdeck.db`）與 API token（`devdeck.token`）存在各平台的使用者資料目錄：
  Windows `%LOCALAPPDATA%\devdeck\`、macOS `~/Library/Application Support/devdeck/`、
  Linux `${XDG_DATA_HOME:-~/.local/share}/devdeck/`；舊版放在程式目錄旁的資料會在啟動時
  自動搬移。設定**不進版控**——不同電腦可用的腳本本來就不同（Windows/Mac），
  各機器維護自己的設定，換機器後需重新登記專案與動作。
- 腳本路徑存相對於腳本目錄的檔名，專案搬家只需改專案路徑。
- 依副檔名分派執行器：`.ps1` → pwsh、`.py` → **該專案 venv 的 python**、`.mjs/.js` → node、
  `.sh` → bash、`.cmd/.bat` → cmd。`.ps1` 在 macOS 需另裝 pwsh，建議在 Mac 上改用
  `.sh`/`.py` 腳本或指令型動作。
- 狀態偵測以 port 探測為主；若服務設定了 PID 檔（如 `uvicorn.pid`），會額外顯示 PID 與殘留提示。

### 安全性

- 伺服器只綁 `127.0.0.1`，外部機器在網路層連不進來。
- 所有請求檢查 Host/Origin 必須為本機，防 DNS rebinding 與惡意網頁跨站觸發。
- 執行端點為 POST + JSON，跨來源會被瀏覽器 preflight 擋下。
- **API token**：伺服器產生隨機 token 寫入使用者資料目錄的 `devdeck.token`，
  啟動腳本讀檔後帶在網址上交付給頁面，頁面存入 localStorage 後從網址列清除；
  之後所有 API 呼叫以 `X-Devdeck-Token` header 驗證。token 只透過本機檔案發放，
  服務本身不提供任何線上取得 token 的端點。想輪替 token：關閉工具、刪除
  `devdeck.token`、重新啟動即可。

### 支援的腳本副檔名

`.ps1` `.py` `.sh` `.mjs` `.js` `.cmd` `.bat`

### 開發計畫（Roadmap）

- 腳本檔案型動作可設定**固定附加參數**（存於動作設定）。
- 腳本檔案型動作支援**右鍵開啟對話框**，臨時輸入僅此一次的命令參數後執行。
- **非專案型指令的歸納**（全域動作群組）；現階段可先把使用者家目錄
  （如 `C:\Users\{user}`）新增為一個「專案」暫代。

---

## English

A local dev-script launcher panel: turn the scripts in each project's `scripts/` directory into
buttons — click to run, watch live output, and monitor long-running services (FastAPI / Vite)
with port-probe status lights.

### Start & stop

Windows:

```powershell
.\start-devdeck.ps1      # start in the background (no window) and open the browser
.\create-shortcut.ps1    # create a Start Menu shortcut (run once)
```

macOS / Linux:

```bash
./start-devdeck.sh       # same; on macOS you can also double-click devdeck.command (dock-able)
```

The first run creates `.venv` and installs dependencies, then opens <http://127.0.0.1:7999>.
The server runs in the background with no console window; if it is already running, launching
again just opens the browser.

The port defaults to `7999`; if another program occupies it, devdeck falls back down through
`7998`–`7990` (the actual port is written to `devdeck.port` in the data directory — launchers
read it and verify via the `/health` endpoint that it is really devdeck). Set the
`DEVDECK_PORT` environment variable to pin a port explicitly (no fallback then).

On Windows, after creating the shortcut, search for **devdeck** in the Start Menu and pin it
to Start or the taskbar.

To stop: the "close tool" button at the top right shuts down the devdeck server (it does not
touch any project services you started).

If the page says the token is missing or invalid (e.g. after clearing browser data), simply
launch devdeck from its shortcut again.

### Workflow

1. **Add a project**: name, path, scripts directory (default `scripts`), venv path (default `.venv`).
2. **Edit the project** to add **services** (name + port + optional PID file), e.g.
   `fastapi :8000`, `vite :5173`. The panel shows a status light per service (green when the
   port is listening). Services with **open homepage** checked get an "open ↗" link to
   `http://localhost:{port}` (dimmed while stopped, still clickable). Leave it unchecked for
   non-web ports.
3. **Add an action**, one of two kinds:
   - **Script file**: picked from a scan of the scripts directory;
   - **Raw command**: e.g. `alembic upgrade head`, executed via shell in the working directory
     with the project venv prepended to PATH (so venv tools like alembic/python resolve directly).

   Then set the label, category, working directory (defaults to the project path), and
   optionally **button-state rules**: for each checked service choose "disable while running"
   or "disable while stopped"; the button is disabled only when **all** checked conditions hold
   (e.g. a start button checked with fastapi "disable while running" locks while the service is
   up; a combined dev-stop checked with both services "disable while stopped" only locks when
   both are down).
4. Daily use: pick a project → click a button → output streams live in the bottom panel.
5. Enable **manage mode** (top right) to reveal edit/delete buttons and avoid accidental clicks.

### Design notes

- Configuration (`devdeck.db`) and the API token (`devdeck.token`) live in the per-platform
  user data directory: `%LOCALAPPDATA%\devdeck\` on Windows,
  `~/Library/Application Support/devdeck/` on macOS,
  `${XDG_DATA_HOME:-~/.local/share}/devdeck/` on Linux (files from the legacy location next
  to the app are migrated automatically on startup). Configuration is **not under version
  control** — the scripts available differ per machine (Windows/Mac), so each machine keeps
  its own config.
- Actions store the script filename relative to the scripts directory; moving a project only
  requires updating the project path.
- Interpreter dispatch by extension: `.ps1` → pwsh, `.py` → **the project venv's python**,
  `.mjs/.js` → node, `.sh` → bash, `.cmd/.bat` → cmd. Running `.ps1` on macOS requires pwsh;
  prefer `.sh`/`.py` scripts or raw commands there.
- Status detection is port-probe first; when a service has a PID file (e.g. `uvicorn.pid`),
  the PID and stale-file hints are shown as auxiliary info.

### Security

- The server binds `127.0.0.1` only; other machines cannot connect at the network level.
- Every request must carry a local Host/Origin, blocking DNS rebinding and cross-site triggering
  from malicious webpages.
- The run endpoint is POST + JSON, so cross-origin calls hit the browser's CORS preflight.
- **API token**: the server writes a random token to `devdeck.token` in the user data
  directory. The launcher reads it and hands it to the page via the URL; the page stores it
  in localStorage and scrubs the URL. All API calls are then authenticated with the
  `X-Devdeck-Token` header. The token is only ever issued through the local file — the service
  has no online endpoint to obtain one. To rotate: close the tool, delete `devdeck.token`,
  and start again.

### Supported script extensions

`.ps1` `.py` `.sh` `.mjs` `.js` `.cmd` `.bat`

### Roadmap

- Persistent extra arguments for script-file actions (stored with the action).
- Right-click a script-file action to enter one-time arguments in a dialog before running.
- A proper home for non-project commands (a global action group); for now, adding your home
  directory (e.g. `C:\Users\{user}`) as a "project" works as a stopgap.

---

## License

Copyright (C) 2026 homTsai <hom5473@gmail.com>

本專案以 GNU General Public License v3.0 授權釋出：可自由使用、修改、散布，但改作對外發布時必須以相同授權開源。

Released under the [GNU General Public License v3.0](LICENSE): free to use, modify and
distribute, but published derivatives must remain open source under the same license.
