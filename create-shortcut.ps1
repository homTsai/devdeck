# 在「開始功能表 > 所有應用程式」建立 devdeck 捷徑。
# 建立後可在開始功能表搜尋 devdeck，右鍵「釘選到開始畫面」或「釘選到工作列」。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
if (-not $pwshCmd) { $pwshCmd = Get-Command powershell }

$lnkPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\devdeck.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath = $pwshCmd.Source
$sc.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\start-devdeck.ps1`""
$sc.WorkingDirectory = $root
$sc.Description = "devdeck - 開發腳本啟動面板"
$sc.Save()
Write-Host "已建立捷徑：$lnkPath"
Write-Host "→ 開始功能表搜尋 devdeck，右鍵可釘選到開始畫面或工作列。"
