# devdeck 啟動腳本：建立/使用自己的 venv，啟動伺服器並開啟瀏覽器。
# 可直接建捷徑指向本檔（pwsh -File start-devdeck.ps1）。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "首次啟動：建立 venv 並安裝相依套件..."
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install -q -r (Join-Path $root "requirements.txt")
}

$url = "http://127.0.0.1:7999"
$alreadyRunning = Test-NetConnection -ComputerName 127.0.0.1 -Port 7999 -InformationLevel Quiet -WarningAction SilentlyContinue

if (-not $alreadyRunning) {
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "7999" `
        -WorkingDirectory $root -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-NetConnection -ComputerName 127.0.0.1 -Port 7999 -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
        Start-Sleep -Milliseconds 300
    }
}

# 伺服器啟動時會把 API token 寫到使用者資料目錄，帶在網址上交付給頁面
$tokenFile = Join-Path $env:LOCALAPPDATA "devdeck\devdeck.token"
if (Test-Path $tokenFile) {
    $token = (Get-Content $tokenFile -Raw).Trim()
    if ($token) { $url = "$url/?token=$token" }
}

Start-Process $url
