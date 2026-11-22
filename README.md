# devdeck

[繁體中文](#繁體中文) | [English](#english)

---

## 繁體中文

本機開發腳本啟動面板：把各專案 `scripts/` 目錄裡的腳本設定成按鈕，點擊即執行、即時看輸出，
常駐服務（FastAPI / Vite）以 port 探測顯示運行狀態燈。

### 需求（Requirements）

- **Python 3.10+**（程式用到 `X | None` 型別語法）。Windows 需 PATH 上有 `python`、macOS 需 `python3`；
  首次啟動腳本會自動建立 `.venv` 並安裝 `fastapi` / `uvicorn`。
- **支援平台**：官方支援 **Windows** 與 **macOS**；**Linux 未測試、屬非官方 best-effort**（見下方設計說明）。
- **依腳本類型另需**（只在你真的用到該類型時才需要）：
  - `.ps1`：PowerShell —— Windows 內建 `powershell` 即可（建議裝 PowerShell 7 / `pwsh`）；**macOS 需自行安裝 `pwsh`**。
  - `.mjs` / `.js`：PATH 上要有 `node`。
  - `.sh`：需 `bash`（Windows 可用 Git Bash 提供）。
  - `.py`：用**該專案自己的 venv**（非 devdeck 的 venv）內的 python，需在專案設定指好 venv 路徑。
  - 直接指令型動作走各平台的 shell（Windows `pwsh` / `powershell`、macOS / Linux `bash`），預設都已具備。

### 啟動與關閉

Windows：

```powershell
.\start-devdeck.ps1      # 啟動（背景執行、無視窗）並開啟瀏覽器
.\create-shortcut.ps1    # 建立開始功能表捷徑（執行一次即可）
```

macOS / Linux：

```bash
./start-devdeck.sh          # 啟動（背景執行、無視窗）並開啟瀏覽器
./create-mac-launcher.sh    # （macOS）生成 devdeck.app 到 ~/Applications，執行一次即可
```

macOS 推薦跑一次 `create-mac-launcher.sh` 生成 **devdeck.app**（對應 Windows 的
`create-shortcut.ps1`）：之後可在 Spotlight / Launchpad 搜尋 devdeck、或拖到 Dock，
雙擊即啟動、不閃 Terminal 視窗。因為 app 是在本機生成、不帶 clone 來的隔離標記，
**不會觸發 Gatekeeper 封鎖**（詳見下方說明）。

首次執行會自動建立 `.venv` 並安裝相依套件，之後開啟 <http://127.0.0.1:7999>。
伺服器在背景執行、不顯示視窗；若已在執行，再次啟動只會開啟瀏覽器。

Port 預設 `7999`；被其他程式占用時自動往下改用 `7998`–`7990`（實際 port 記錄在資料目錄的
`devdeck.port`，啟動腳本會自動讀取，並以 `/health` 端點確認是 devdeck 本尊而非別的程式）。
也可用環境變數 `DEVDECK_PORT` 明確指定（指定後不做 fallback）。

Windows 建立捷徑後，可在開始功能表搜尋 **devdeck**，右鍵「釘選到開始畫面」或「釘選到工作列」。

關閉：面板右上角「關閉工具」按鈕會停止 devdeck 伺服器（不影響已啟動的專案服務）。

若頁面顯示「驗證失效」（例如清除過瀏覽器資料），重新點一次啟動捷徑即可重新取得授權。

### macOS：雙擊被 Gatekeeper 擋住怎麼辦

雙擊入口是 **`devdeck.command`**（不是 `.sh`——Finder 雙擊 `.sh` 只會用關聯的編輯器打開、不會執行）。

**最省事的做法：跑 `./create-mac-launcher.sh` 改用生成的 `devdeck.app`** —— 它在本機生成、
不帶隔離標記，Gatekeeper 完全不會攔。

若仍想用 `devdeck.command`，而雙擊時出現「Apple 無法驗證是否為惡意軟體」、對話框只給
「完成 / 丟到垃圾桶」，表示檔案被加上了隔離標記（常見於用 Sourcetree 等 GUI 工具 clone）。
三選一即可解除：

- 終端機清除隔離標記：`xattr -d com.apple.quarantine devdeck.command`（或整包 `xattr -cr .`）；
- 系統設定 → 隱私權與安全性 → 往下找到「仍要打開」放行；
- 或直接在終端機執行 `./start-devdeck.sh`——終端機明確執行不受 Gatekeeper 管制。

### 使用流程

1. **新增專案**：設定專案名稱、路徑、腳本目錄（預設 `scripts`）、venv 路徑（預設 `.venv`）。
2. **編輯專案**內可加入**服務**（名稱 + port + 選填 PID 檔），例如 `fastapi :8000`、`vite :5173`，
   面板上方會顯示各服務的狀態燈（port 有人聽 = 綠燈）。勾選「**開網頁**」的服務會多一個
   「開啟 ↗」連結，直接開 `http://localhost:{port}` 首頁（服務停止時連結變暗但仍可點）；
   不是網頁的 port 不勾即可。
3. **新增動作**：兩種類型擇一——
   - **腳本檔案**：從腳本目錄掃描結果挑選；可填固定的**附加指令參數**（例如
     `--port 8000 --name "My App"`），每次按下按鈕都會附加到腳本後；
   - **直接指令**：直接輸入指令（如 `alembic upgrade head`），會在工作目錄以 shell 執行，
     且專案 venv 已掛入 PATH（指令可直接使用 venv 內的 alembic / python 等工具）。

   每個動作都可選擇執行方式：**面板執行**（預設，輸出串流回 devdeck）或**外部終端機**
   （使用相同工作目錄與參數另開可互動的 PowerShell／Terminal；輸出與輸入都在該視窗）。

   再設定顯示名稱、分類、工作目錄（預設專案路徑），並可勾選**按鈕狀態關聯**：
   對每個勾選的服務選擇「運行中時停用」或「停止時停用」，勾選的條件**全部成立**時該按鈕會停用
   （例：start 按鈕勾 fastapi「運行中時停用」→ 服務在跑就按不了；dev stop 勾兩個服務
   「停止時停用」→ 兩個都停了才鎖住，只剩一個在跑仍可按）。
4. 日常使用：選專案 → 點按鈕 → 下方面板即時串流輸出。
5. 開啟按鈕面板右上角的**動作管理**開關才會顯示編輯／隱藏按鈕與分類排序，避免誤觸；專案面板標題列的排序圖示則用於拖曳調整專案順序。

### 設計說明

- 設定資料（`devdeck.db`）與 API token（`devdeck.token`）存在各平台的使用者資料目錄：
  Windows `%LOCALAPPDATA%\devdeck\`、macOS `~/Library/Application Support/devdeck/`、
  Linux `${XDG_DATA_HOME:-~/.local/share}/devdeck/`；舊版放在程式目錄旁的資料會在啟動時
  自動搬移。設定**不進版控**——不同電腦可用的腳本本來就不同（Windows/Mac），
  各機器維護自己的設定，換機器後需重新登記專案與動作。
- 腳本路徑存相對於腳本目錄的檔名，專案搬家只需改專案路徑。腳本動作的附加參數會以
  引數陣列直接交給執行器，而非透過 shell；含空白的單一參數請用雙引號包住。
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
- **直接指令動作會原封不動執行、不做任何過濾**——這是刻意的：這類動作的用途就是
  跑你自己設定的整條 shell 指令。它的安全邊界是「只綁 `127.0.0.1` + 本機檔案發放的
  token」，不是指令內容驗證；能寫入指令的人本來就已具備你的本機權限。請只加入你信任
  的指令，不要把 devdeck 暴露到不受信任的環境。

### 支援的腳本副檔名

`.ps1` `.py` `.sh` `.mjs` `.js` `.cmd` `.bat`

### 疑難排解（Troubleshooting）

- **動作輸出顯示某個直譯器「找不到」（pwsh / node / bash）**：對應直譯器不在 PATH 上。裝好該工具、
  確認終端機能直接呼叫；devdeck 依副檔名分派（見上方設計說明）。
  - macOS 從 Finder / Dock 啟動只會拿到精簡 PATH，`start-devdeck.sh` 已用登入 shell 解析完整 PATH 再帶給
    伺服器；若仍找不到，確認該工具有寫進你的登入 shell rc（`~/.zshrc` 等），或改從終端機執行
    `./start-devdeck.sh`。
- **動作輸出顯示「找不到專案 venv 的 python」**：該專案的 venv 路徑（預設 `.venv`）不存在或設錯。到專案
  設定確認 venv 路徑，或先在專案目錄建好 venv。
- **Port 被占用 / 想釘死固定 port**：devdeck 預設 `7999`，被占用時自動往下試 `7998`–`7990`，全滿則退到
  隨機臨時埠；實際 port 記在資料目錄的 `devdeck.port`，啟動腳本會自動讀。要指定固定 port，設環境變數
  `DEVDECK_PORT`（如 `DEVDECK_PORT=8080`）——**指定後不做 fallback**，該 port 若被占用會直接啟動失敗。
- **macOS 雙擊 `.command` 沒反應或被擋**：
  - 被 Gatekeeper 擋（只給「完成 / 丟到垃圾桶」）→ 見上方〈macOS：雙擊被 Gatekeeper 擋住怎麼辦〉。
  - 雙擊沒反應、或被編輯器打開 → 檔案可能少了執行權限：終端機執行 `chmod +x devdeck.command`。`.sh` 在
    Finder 雙擊本來就不會執行（會用編輯器開），請改用 `.command` 或 `devdeck.app`。
- **關閉 cloudflared（或其他常駐服務）要不要加 `-Force`？** 這是使用建議、非 devdeck 行為：PowerShell 的
  `Stop-Process` **無論加不加 `-Force`，對 console 程式都是硬砍**（底層 `TerminateProcess`）；`-Force` 只決定
  「跳不跳確認 / 能否砍非自己擁有的程序」，**與優雅登出無關**。要讓 cloudflared 優雅 drain 並向 edge 註銷：
  **Unix** 用 `kill -2 <pid>`（SIGINT）；**Windows** 的 `Stop-Process` 做不到，最實際是把該服務開在**外部
  終端機**再按 Ctrl-C（後續規劃的 `in_terminal` 動作會直接支援）。
- **按「瀏覽…」選資料夾時沒反應**：路徑欄位的資料夾選擇器由後端叫出系統原生視窗，需要 Python 的
  tkinter。Windows／macOS 的官方 Python 已內建；**Linux**（非官方支援）多半要另裝，例如
  `sudo apt install python3-tk`。若無法安裝也不影響——路徑欄位一律可手動輸入。

### 開發計畫（Roadmap）

- 腳本檔案型動作支援**右鍵開啟對話框**，臨時輸入僅此一次的命令參數後執行。
- **非專案型指令的歸納**（全域動作群組）；現階段可先把使用者家目錄
  （如 `C:\Users\{user}`）新增為一個「專案」暫代。
- （探索中）**後端行程生命週期管理**，讓服務可在 devdeck 內一鍵啟停；設計討論見 `docs/service-lifecycle-plan.md`。

---

## English

A local dev-script launcher panel: turn the scripts in each project's `scripts/` directory into
buttons — click to run, watch live output, and monitor long-running services (FastAPI / Vite)
with port-probe status lights.

### Requirements

- **Python 3.10+** (the code uses the `X | None` type syntax). Windows needs `python` on PATH; macOS needs
  `python3`. The first launch auto-creates `.venv` and installs `fastapi` / `uvicorn`.
- **Supported platforms**: **Windows** and **macOS** are officially supported; **Linux is untested,
  unofficial best-effort** (see the design notes below).
- **Per-script-type extras** (only needed if you actually use that type):
  - `.ps1`: PowerShell — Windows ships `powershell` (PowerShell 7 / `pwsh` recommended); **macOS needs `pwsh`
    installed separately**.
  - `.mjs` / `.js`: `node` on PATH.
  - `.sh`: `bash` (on Windows, e.g. from Git Bash).
  - `.py`: run with **the project's own venv** python (not devdeck's), so set the venv path in project settings.
  - Raw-command actions run through the platform shell (Windows `pwsh` / `powershell`, macOS / Linux `bash`),
    all present by default.

### Start & stop

Windows:

```powershell
.\start-devdeck.ps1      # start in the background (no window) and open the browser
.\create-shortcut.ps1    # create a Start Menu shortcut (run once)
```

macOS / Linux:

```bash
./start-devdeck.sh          # start in the background (no window) and open the browser
./create-mac-launcher.sh    # (macOS) generate devdeck.app into ~/Applications (run once)
```

On macOS, run `create-mac-launcher.sh` once to generate **devdeck.app** (the counterpart of
Windows' `create-shortcut.ps1`): afterwards you can find devdeck in Spotlight / Launchpad or
drag it to the Dock, and double-click to launch with no Terminal window. Because the app is
generated locally — with no quarantine flag from cloning — it **does not trip Gatekeeper**
(see below).

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

### macOS: first launch blocked by Gatekeeper

The double-click entry point is **`devdeck.command`** (not `.sh` — double-clicking a `.sh` in
Finder only opens it in the associated editor, it does not run it).

**Easiest fix: run `./create-mac-launcher.sh` and use the generated `devdeck.app` instead** —
it is generated locally, carries no quarantine flag, and never trips Gatekeeper.

If you still prefer `devdeck.command` and double-clicking shows "Apple could not verify … is
free of malware" with only "Done / Move to Trash", the file carries a quarantine flag (common
when cloned via a GUI tool such as Sourcetree). Clear it any one of three ways:

- Remove the flag in a terminal: `xattr -d com.apple.quarantine devdeck.command`
  (or `xattr -cr .` for the whole repo);
- System Settings → Privacy & Security → scroll down and click "Open Anyway";
- Or just run `./start-devdeck.sh` in a terminal — explicit execution is not subject to Gatekeeper.

### Workflow

1. **Add a project**: name, path, scripts directory (default `scripts`), venv path (default `.venv`).
2. **Edit the project** to add **services** (name + port + optional PID file), e.g.
   `fastapi :8000`, `vite :5173`. The panel shows a status light per service (green when the
   port is listening). Services with **open homepage** checked get an "open ↗" link to
   `http://localhost:{port}` (dimmed while stopped, still clickable). Leave it unchecked for
   non-web ports.
3. **Add an action**, one of two kinds:
   - **Script file**: picked from a scan of the scripts directory; it can have persistent
     **extra arguments** such as `--port 8000 --name "My App"`, appended on every run;
   - **Raw command**: e.g. `alembic upgrade head`, executed via shell in the working directory
     with the project venv prepended to PATH (so venv tools like alembic/python resolve directly).

   Then set the label, category, working directory (defaults to the project path), and
   optionally **button-state rules**: for each checked service choose "disable while running"
   or "disable while stopped"; the button is disabled only when **all** checked conditions hold
   (e.g. a start button checked with fastapi "disable while running" locks while the service is
   up; a combined dev-stop checked with both services "disable while stopped" only locks when
   both are down).
4. Daily use: pick a project → click a button → output streams live in the bottom panel.
5. Enable the **Manage actions** switch at the top right of the action panel to reveal edit/hide buttons and category reordering without accidental clicks, and use the sort icon in the project sidebar header to reorder projects.

### Design notes

- Configuration (`devdeck.db`) and the API token (`devdeck.token`) live in the per-platform
  user data directory: `%LOCALAPPDATA%\devdeck\` on Windows,
  `~/Library/Application Support/devdeck/` on macOS,
  `${XDG_DATA_HOME:-~/.local/share}/devdeck/` on Linux (files from the legacy location next
  to the app are migrated automatically on startup). Configuration is **not under version
  control** — the scripts available differ per machine (Windows/Mac), so each machine keeps
  its own config.
- Actions store the script filename relative to the scripts directory; moving a project only
  requires updating the project path. Script extra arguments are passed directly as an argument
  list, never through a shell; quote a single argument containing spaces with double quotes.
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
- **Direct-command actions run verbatim, with no filtering** — this is deliberate: the whole
  point of such an action is to run the exact shell command you configured. Its security
  boundary is "bound to `127.0.0.1` only + a token issued through a local file," not command
  validation; anyone who can write a command already has your local privileges. Only add
  commands you trust, and never expose devdeck to an untrusted environment.

### Supported script extensions

`.ps1` `.py` `.sh` `.mjs` `.js` `.cmd` `.bat`

### Troubleshooting

- **An action's output says an interpreter is "not found" (pwsh / node / bash)**: the matching interpreter
  isn't on PATH. Install it and make sure your terminal can call it directly; devdeck dispatches by file
  extension (see design notes).
  - On macOS, launching from Finder / the Dock only inherits a minimal PATH. `start-devdeck.sh` already
    resolves your full login-shell PATH before starting the server; if a tool is still missing, make sure it
    is exported in your login-shell rc (`~/.zshrc`, …), or run `./start-devdeck.sh` from a terminal.
- **An action says the project venv's python is "not found"**: the project's venv path (default `.venv`) is
  missing or wrong. Check the venv path in the project settings, or create the venv in the project directory
  first.
- **Port already in use / pin a fixed port**: devdeck defaults to `7999`, falling back down through
  `7998`–`7990`, then to a random ephemeral port; the actual port is recorded in `devdeck.port` in the data
  directory and read by the launchers. To pin a port, set the `DEVDECK_PORT` environment variable (e.g.
  `DEVDECK_PORT=8080`) — **no fallback then**, so startup fails outright if that port is taken.
- **macOS: double-clicking `.command` does nothing or is blocked**:
  - Blocked by Gatekeeper (only "Done / Move to Trash") → see "macOS: first launch blocked by Gatekeeper"
    above.
  - Nothing happens / it opens in an editor → the file may lack the execute bit: run
    `chmod +x devdeck.command`. Double-clicking a `.sh` in Finder never runs it (it opens in an editor) — use
    `.command` or `devdeck.app` instead.
- **Should I add `-Force` when stopping cloudflared (or other long-running services)?** This is usage
  guidance, not devdeck behavior: PowerShell's `Stop-Process` **hard-kills console programs with or without
  `-Force`** (underlying `TerminateProcess`); `-Force` only governs confirmation prompts / killing processes
  you don't own — it has **nothing to do with graceful shutdown**. To let cloudflared drain gracefully and
  deregister from the edge: **Unix** — `kill -2 <pid>` (SIGINT); **Windows** — `Stop-Process` can't, so the
  practical route is to run the service with the action's **external terminal** mode and press Ctrl-C there.
- **Clicking "Browse…" to pick a folder does nothing**: the folder picker opens a native OS dialog from the
  backend, which needs Python's tkinter. The official Python builds on Windows / macOS bundle it; on **Linux**
  (unofficial) you usually need it separately, e.g. `sudo apt install python3-tk`. If you can't install it,
  that's fine — every path field can still be typed in by hand.

### Roadmap

- Right-click a script-file action to enter one-time arguments in a dialog before running.
- A proper home for non-project commands (a global action group); for now, adding your home
  directory (e.g. `C:\Users\{user}`) as a "project" works as a stopgap.

---

## License

Copyright (C) 2026 homTsai <hom5473@gmail.com>

本專案以 GNU General Public License v3.0 授權釋出：可自由使用、修改、散布，但改作對外發布時必須以相同授權開源。

Released under the [GNU General Public License v3.0](LICENSE): free to use, modify and
distribute, but published derivatives must remain open source under the same license.
