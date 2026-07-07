# 服務生命週期管理 — 設計討論（探索中，未排期）

> **決策狀態：探索中，尚未定案，不進 `docs/TODO.md`。**
> 這是架構級轉向，會改變 devdeck 的核心模型，先在此收攏取捨與開放問題，決定要不要做之後再排期。

## 目標

讓 devdeck 具備完整的行程生命週期控制權：服務可在網頁內一鍵啟動、一鍵停止，狀態即時反映，不再需要外部終端機或手動下關閉指令。所有開發工具的啟停都在 devdeck 內閉環。

## 現況模型（為什麼這是「轉向」而非「加功能」）

devdeck 目前是**「射後不理 + 外部監看」**：

- 動作透過 `asyncio.create_subprocess_exec` + SSE 串流執行（`app/runner.py`）；請求結束或斷線就清掉前景子行程。
- **長駐服務不是 devdeck 管的**：慣例是使用者腳本自己把服務背景化、寫 PID 檔，devdeck 只靠 **port 探測**（`app/status.py`）+ 選配 PID 檔存活檢查來**監看**（`app/main.py` 的 `project_status`）。
- devdeck **不持有**任何服務行程的 handle，因此**無法**主動停止它。

要做到「一鍵停止」，devdeck 必須反過來**擁有**這些行程 —— 這是模型的根本改變。

## 提案

### 階段三之一：後端行程常駐管理（Process Registry）

- 服務型動作改用 `subprocess.Popen` 啟動並**保留 handle**。
- FastAPI 後端維護記憶體內字典，例如 `active_processes = { action_id: popen }`，追蹤所有 devdeck 派生的子行程。

### 階段三之二：介面「一鍵終止」（⏹）

- 服務綠燈（運行中）時，前端按鈕旁動態顯示停止小圖示。
- 點擊 → 後端 `popen.terminate()` 或送平滑關閉信號。
- 成果：捨棄外部終端機 / 手動關閉指令的需求。

## 開放問題（決定可行性的關鍵）

1. **重啟後 handle 消失**：`active_processes` 是記憶體內字典，devdeck 一重啟（或 uvicorn reload）就全丟，但子行程還活著 → 變成孤兒、狀態失聯。這正是 commit `aa41c09`（重啟前清理殘留實例）在處理的同一類問題。需要落地方案（PID 檔持久化？重啟後重新認領？）。
2. **與 SSE 串流模型的關係**：現在輸出走 SSE 串流；常駐服務的輸出要怎麼接（持續串流？寫檔輪詢？）需重新設計。
3. **Windows 無真正的 SIGINT**：`popen.terminate()` 在 Windows 是 `TerminateProcess`（硬砍），要優雅關閉得對 process group 送 `CTRL_C_EVENT`，跨平台語意不一致。
4. **與第 8 項（`in_terminal`）衝突**：外部終端機啟動的行程 devdeck 拿不到 handle，兩條路線的邊界要先講清楚（哪些服務走 registry、哪些走外部終端機）。
5. **單人本機工具的必要性**：這麼大的改動，對「一個人、一台機」的使用情境投報率是否足夠？還是第 8、9 項（外部終端機 + 動態 port）就已經覆蓋多數痛點？

## 相關項目

- `docs/TODO.md` 第 8 項（`in_terminal` 外部終端機啟動）、第 9 項（動態 Port + 動態健康檢查）—— 這兩項是**低成本、不需轉向**就能解掉多數痛點的路線，建議先做完再評估本文是否仍需要。
