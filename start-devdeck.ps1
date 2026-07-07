# devdeck 啟動腳本：建立/使用自己的 venv，啟動伺服器並開啟瀏覽器。
# 可直接建捷徑指向本檔（pwsh -File start-devdeck.ps1）。
# -NoBrowser：只確保伺服器就緒並印出網址，不開瀏覽器（供測試/自動化）。
param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$dataDir = Join-Path $env:LOCALAPPDATA "devdeck"

if (-not (Test-Path $python)) {
    Write-Host "首次啟動：建立 venv 並安裝相依套件..."
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install -q -r (Join-Path $root "requirements.txt")
}

# port 由伺服器選定（預設 7999，占用時往下 fallback）並寫入 devdeck.port
function Get-DevdeckPort {
    $portFile = Join-Path $dataDir "devdeck.port"
    if (Test-Path $portFile) { return [int](Get-Content $portFile -Raw).Trim() }
    return 7999
}

function Get-DevdeckToken {
    $tokenFile = Join-Path $dataDir "devdeck.token"
    if (Test-Path $tokenFile) { return (Get-Content $tokenFile -Raw).Trim() }
    return ""
}

# 就緒檢查：不只 /health，還要「token 能通過 /api/」。
# 只探 /health 會誤判——壞掉、token 不同步的實例對 /health（免 token）照樣回 200，
# 導致啟動腳本以為在跑而跳過重啟，把瀏覽器指向一個永遠 401 的實例。
function Test-DevdeckReady([int]$port, [string]$token) {
    try {
        if ((Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2).app -ne "devdeck") { return $false }
    } catch { return $false }
    if (-not $token) { return $false }
    try {
        Invoke-RestMethod "http://127.0.0.1:$port/api/projects" `
            -Headers @{ "X-Devdeck-Token" = $token } -TimeoutSec 3 | Out-Null
        return $true   # 200 => token 有效，是健康的本尊
    } catch {
        return $false  # 401/連不上 => 壞實例或未就緒
    }
}

# 砍掉本 devdeck 的伺服器程序（含 venv 父程序與它 spawn 的實際伺服器子程序）。
# 判斷依據：命令列是 "-m app" 且該程序或其父程序的命令列指向本 $root。
function Stop-Devdeck {
    $rootEsc = [regex]::Escape($root)
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -and $_.CommandLine -match '-m\s+app' }
    $ids = @{}
    foreach ($p in $procs) {
        $ours = $p.CommandLine -match $rootEsc
        if (-not $ours -and $p.ParentProcessId) {
            $par = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue
            if ($par -and $par.CommandLine -match $rootEsc) { $ours = $true }
        }
        if ($ours) {
            $ids[[int]$p.ProcessId] = $true
            if ($p.ParentProcessId) { $ids[[int]$p.ParentProcessId] = $true }
        }
    }
    foreach ($id in $ids.Keys) { try { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } catch {} }
    if ($ids.Count) { Start-Sleep -Milliseconds 500 }
}

$token = Get-DevdeckToken
$port  = Get-DevdeckPort

# 只有在「現有實例不健康（沒在跑，或跑著但 token 驗不過）」時才重啟；
# 健康的實例不動它，避免打斷正在執行的動作。
if (-not (Test-DevdeckReady $port $token)) {
    Stop-Devdeck   # 清掉壞掉/殘留的實例，讓連接埠與 token 重新對齊
    Start-Process -FilePath $python -ArgumentList "-m", "app" `
        -WorkingDirectory $root -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 300
        $port  = Get-DevdeckPort       # 新實例可能因連接埠占用而 fallback
        $token = Get-DevdeckToken      # 新實例可能剛建立 token 檔
        if (Test-DevdeckReady $port $token) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Warning "devdeck 已啟動但 token 驗證未在時限內通過；請再執行一次，或查看伺服器輸出。"
    }
}

$token = Get-DevdeckToken
$url = "http://127.0.0.1:$port"
# 伺服器啟動時會把 API token 寫到使用者資料目錄，帶在網址上交付給頁面
if ($token) { $url = "$url/?token=$token" }

if ($NoBrowser) { Write-Host $url } else { Start-Process $url }
