# devdeck 啟動腳本：建立/使用自己的 venv，啟動伺服器並開啟瀏覽器。
# 可直接建捷徑指向本檔（pwsh -File start-devdeck.ps1）。
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

# 用 /health 確認 port 上是 devdeck 本尊（單純探測 port 可能誤認別的程式）
function Test-Devdeck([int]$port) {
    try {
        return (Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2).app -eq "devdeck"
    } catch { return $false }
}

$port = Get-DevdeckPort
if (-not (Test-Devdeck $port)) {
    Start-Process -FilePath $python -ArgumentList "-m", "app" `
        -WorkingDirectory $root -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 300
        $port = Get-DevdeckPort
        if (Test-Devdeck $port) { break }
    }
}

$url = "http://127.0.0.1:$port"

# 伺服器啟動時會把 API token 寫到使用者資料目錄，帶在網址上交付給頁面
$tokenFile = Join-Path $dataDir "devdeck.token"
if (Test-Path $tokenFile) {
    $token = (Get-Content $tokenFile -Raw).Trim()
    if ($token) { $url = "$url/?token=$token" }
}

Start-Process $url
