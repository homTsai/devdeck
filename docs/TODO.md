# devdeck 後續修改項目

工程健全度／品質清單，與 README 的「開發計畫（Roadmap）」（功能面）分開維護。

> 來源：Copilot review 建議（第 1～7 項）＋服務狀態管理 roadmap 討論（第 8、9 項），已對照專案現況去重。
> `.gitignore` 補充項已於 commit `a7ae24e` 完成，故不列入。
> 架構級的「後端行程生命週期管理」尚未定案，另立 `docs/service-lifecycle-plan.md`，不進本清單。

| # | 項目 | 優先度 | 現況 | 具體動作 |
|---|------|--------|------|----------|
| 1 | requirements.txt 版本鎖定 | 🔴 高 | ✅ 已完成 | 已改為 `fastapi>=0.104.0`、`uvicorn>=0.24.0` |
| 2 | README 補 **Requirements** 段 | 🟡 中 | 待辦 | 標明 Python 3.10+、支援範圍（**官方支援 Windows + macOS；Linux 未測試、非官方支援**）、`pwsh`（macOS 可選） |
| 3 | README 補 **Troubleshooting** 段 | 🟡 中 | 待辦 | 收錄「找不到 python/node/bash」「port 被占用 → `DEVDECK_PORT`」「macOS 無法雙擊 .command → 權限」 |
| 4 | 錯誤訊息友善化 | 🟡 中 | 待辦 | `app/runner.py` 訊息附「怎麼解決」提示 + 指向 README Troubleshooting 錨點 |
| 5 | 跨平台實測 | 🟡 中 | ✅ 完成 | macOS 已實測並修正（commits `0984f71`、`ef878d5`、`3491e00`）；Windows 為主要使用平台；**Linux 非官方支援、不列入實測**（見備註） |
| 6 | CHANGELOG | 🟢 低 | 待辦 | 有版本規劃再建，先擺著 |
| 7 | 前端 i18n（英文語系） | 🟡 中 | 待辦 | **純前端**：`navigator.language` 首載偵測 + 頁首手動切換 + `localStorage` 記憶；詳範圍見下方「i18n 範圍界定」 |
| 8 | 動作「外部終端機啟動」勾選（`in_terminal`） | 🟡 中 | 待辦 | 前端加勾選、後端依平台轉換啟動指令（**只做 Windows + macOS**）；詳見下方「服務生命週期相關」 |
| 9 | 動態 Port 偵測 + 動態健康檢查 | 🟡 中 | 待辦 | 用 PID 反查監聽中的 port，狀態探測由「設定檔固定值」改「動態捕捉值」；詳見下方「服務生命週期相關」 |

## 備註

- **第 4、5 項綁在一起**：`.command` / `.sh` 的權限、`create-mac-launcher.sh` 的行為，實測後才知道錯誤訊息該補什麼，建議一起做。
- **第 6 項（CHANGELOG）現在投報率低**：單人／早期工具，等真的要對外發版再建即可，已降到低優先。
- **第 3 項（Troubleshooting）補一則 cloudflared 關閉 know-how**：關閉動作的指令要不要加 `-Force`——見下方「服務生命週期相關」的說明，寫 Troubleshooting 時一併收錄。
- **Linux 支援政策（2026-07 決定）**：不為 Linux 桌面專門投入開發——不做 Linux 版 launcher、不做 `in_terminal` 的終端機 matrix、不測 `xdg-open` 跨發行版。現有 POSIX / XDG 碼（約 5 行，與 macOS 共用）保留為 best-effort，壞了不修，**不刪碼**（刪了會誤傷 macOS）。定位：**官方支援 Windows + macOS；Linux 非官方支援、未測試、不保證**。理由：個人工具，Linux 桌面族群慣用終端機、非受眾，且環境過於分歧。

## i18n 範圍界定（第 7 項）

Copilot 原提案是「通用 Web App」規格，套到本機單人工具過度設計。**採右尺寸後的純前端方案**：

**要做**
- `data-i18n="key"` 屬性替換靜態外殼文字；缺字 fallback 回預設語系。
- 首載用 `navigator.language` 偵測，比對支援語系 prefix，預設 `zh-TW`。
- 頁首下拉手動切換，切換後立即生效並存 `localStorage`。
- 同步 `document.documentElement.lang`。
- 語系字典**直接 inline 進 `static/index.html`**（zh-TW / en 兩個小物件），不額外 `fetch` locale JSON，省一次往返並避免首載未翻譯閃爍（FOUC）。

**明確不做（砍掉 Copilot 提案的這些）**
- ❌ FastAPI `LocaleMiddleware` / Accept-Language / 後端塞 cookie — 後端只回 JSON API + 送靜態 HTML，伺服端沒有要翻譯的文字，中間層是白工。
- ❌ cookie 儲存偏好 — 後端不用，`localStorage` 一個就夠。
- ❌ URL 參數 / 帳號設定 優先層 — 無登入、無帳號。
- ⏸ RTL / `dir` — zh-TW / en 皆 LTR，等真有 RTL 語言再處理。

**主要工作量提醒**：偵測/切換邏輯是小事；真正花時間的是 `static/index.html` 內**由 inline JS 動態 render 的文字**（如 `執行`/`停止`、空狀態字串），需把 `t('key')` helper 穿進既有 render 函式逐處替換——這是唯一會碰到既有邏輯、要防 regression 的部分，可分批進行。

## 服務生命週期相關（第 8、9 項）

來自服務狀態管理 roadmap 討論，已對照現況取捨。**架構級的 Process Registry / 一鍵終止不在此列，見 `docs/service-lifecycle-plan.md`。**

### 第 8 項：動作「外部終端機啟動」（`in_terminal`）

把某動作改成在**獨立終端機視窗**啟動，而非串進 devdeck 的 SSE 輸出。適合 tunnel / 長駐服務（要自己的視窗、能 Ctrl-C、獨立於 devdeck 存活）。

- 前端：動作設定新增 `in_terminal` 勾選方塊。
- 後端：依平台轉換啟動指令 —— Windows `cmd /c start`、macOS `osascript`（彈新視窗）。
- **Linux 不特別處理**：終端機百家爭鳴（`gnome-terminal` / `konsole` / `xterm`…），依「不為 Linux 專門投入」政策略過（見備註）；Linux 使用者本就慣用終端機，可自行下指令。
- **附帶好處**：這也是 cloudflared「優雅關閉」在 Windows 上最實際的解——開在外部終端機直接 Ctrl-C，tunnel 自然 drain（見下方 ② know-how）。

### 第 9 項：動態 Port 偵測 + 動態健康檢查

解「cloudflared 之類隨機 port 服務也能自動亮綠燈、免手填 port」。

- 後端用 PID 反查該行程正在 `LISTEN` 的本機 port（`psutil` 是乾淨作法）。
- 狀態探測（`app/status.py` / `app/main.py:213` 的 `project_status`）由「設定檔固定 `svc["port"]`」改為可接受「動態捕捉值」。
- ⚠️ **代價**：多一個 `psutil` 依賴（目前只有 fastapi / uvicorn，是明顯的量級跳升）。
- ⚠️ **前提**：得先拿得到服務的 PID（現況只有設了 `pid_file` 的服務才有），否則無從反查。

### ② 關閉指令 -Force 的 know-how（歸屬第 3 項 Troubleshooting）

背景：使用者在動作內（存於 `devdeck.db`）自訂了關閉 cloudflared 的指令，問要不要加 `-Force`。這**不是 devdeck 程式碼問題**，是使用建議：

- PowerShell 的 `Stop-Process` **無論加不加 `-Force`，對 console 程式（cloudflared）都是硬砍**（底層 `Process.Kill()` → `TerminateProcess`）。`-Force` 只管「跳不跳確認 / 能否砍非自己擁有的程序」，**與優雅登出無關**。
- 要 cloudflared **優雅登出（drain + 向 edge 註銷）**：
  - **Unix**：`kill -2 <pid>`（SIGINT）或預設 SIGTERM，cloudflared 會處理。
  - **Windows**：`Stop-Process` 做不到；最實際是走**第 8 項外部終端機 + Ctrl-C**。
