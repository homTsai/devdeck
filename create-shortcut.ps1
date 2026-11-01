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

$icoPath = Join-Path $root "devdeck.ico"
if (Test-Path $icoPath) {
    $sc.IconLocation = "$icoPath,0"
} else {
    # 若沒有 devdeck.ico，且 pwsh 是 WindowsApps 0-byte 別名（缺少 Win32 圖示資源），
    # fallback 到系統內建 powershell.exe，避免開始選單捷徑圖示壞掉或破圖
    if ($pwshCmd.Source -match 'Microsoft\\WindowsApps') {
        $realPs = (Get-Command powershell -ErrorAction SilentlyContinue).Source
        if ($realPs) { $sc.IconLocation = "$realPs,0" }
    }
}

$sc.Save()

# 通知 Windows Shell 刷新圖示關聯快取
try {
    $code = @'
using System;
using System.Runtime.InteropServices;
public class ShellNotify {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
}
'@
    Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue
    [ShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero) # SHCNE_ASSOCCHANGED
} catch {}
Write-Host "已建立捷徑：$lnkPath"
Write-Host "→ 開始功能表搜尋 devdeck，右鍵可釘選到開始畫面或工作列。"
