# -*- coding: utf-8 -*-
# 一键打包：python build_exe.ps1
# 产物：dist\基金纪律面板.exe（单文件，双击即用），并自动复制到项目根目录、刷新桌面快捷方式

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $proj

$candidates = @(
  "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
)
$PY = $null
foreach ($c in $candidates) { if (Test-Path $c) { $PY = $c; break } }
if (-not $PY) {
  try { $PY = (py -3 -c "import sys;print(sys.executable)") } catch { }
}
if (-not $PY) { Write-Host "找不到 Python，请先安装（需要带 tkinter 的完整版）。" -ForegroundColor Red; exit 1 }
Write-Host "使用 Python: $PY"

# 1. 确认 PyInstaller
& $PY -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "未检测到 PyInstaller，正在安装……"
  & $PY -m pip install --disable-pip-version-check pyinstaller
  if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller 安装失败，请检查网络或改用国内源。" -ForegroundColor Red; exit 1 }
}

# 2. 清理旧产物
foreach ($d in @("build", "dist")) { if (Test-Path $d) { Remove-Item $d -Recurse -Force } }
Get-ChildItem -Filter "*.spec" -ErrorAction SilentlyContinue | Remove-Item -Force

# 3. 打包（--noconsole：双击不弹黑窗；--onefile：单个 exe）
& $PY -m PyInstaller `
  --noconfirm --clean --onefile --noconsole `
  --name "基金纪律面板" `
  --add-data "web;web" `
  --add-data "tools;tools" `
  --add-data "pack\config.json;." `
  --hidden-import api --hidden-import api.server --hidden-import api.paths `
  --hidden-import api.engine --hidden-import api.store --hidden-import api.service `
  --hidden-import api.ai --hidden-import api.ocr --hidden-import api.quotes `
  --hidden-import api.keybox --hidden-import desktop --hidden-import desktop.app `
  desktop.py

if ($LASTEXITCODE -ne 0) { Write-Host "打包失败，请看上面的报错。" -ForegroundColor Red; exit 1 }

$exe = Join-Path $proj "dist\基金纪律面板.exe"
if (-not (Test-Path $exe)) { Write-Host "没生成 exe，异常退出。" -ForegroundColor Red; exit 1 }
Write-Host ("打包完成：" + $exe) -ForegroundColor Green
Write-Host ("大小：" + [math]::Round((Get-Item $exe).Length / 1MB, 1) + " MB")

# 4. 复制一份到项目根目录（和 config.json / state.json 放一起，数据才会落在 G:\money）
Copy-Item $exe (Join-Path $proj "基金纪律面板.exe") -Force
Write-Host ("已复制到：" + (Join-Path $proj "基金纪律面板.exe"))

# 5. 桌面快捷方式指向 exe（原来指向 .bat 的话顺便升级）
$desk = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desk "基金纪律面板.lnk"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = (Join-Path $proj "基金纪律面板.exe")
$lnk.WorkingDirectory = $proj
$lnk.IconLocation = $lnk.TargetPath + ",0"
$lnk.Description = "基金持仓纪律面板"
$lnk.Save()
Write-Host ("桌面快捷方式已更新：" + $lnkPath) -ForegroundColor Green

Write-Host ""
Write-Host "用法：双击桌面「基金纪律面板」，或在 G:\money 里双击 基金纪律面板.exe"
Write-Host "数据目录：exe 所在文件夹（state.json / data\fundlife.db / reports\ 都在这里）"
