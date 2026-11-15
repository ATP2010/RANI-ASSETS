<#
.SYNOPSIS
  Pasang handler "raniaction://" di PC pengguna (tanpa admin — HKCU).
.DESCRIPTION
  1. Salin rani-action.ps1 ke %ProgramData%\RaniAction\rani-action.ps1
  2. Tulis %ProgramData%\RaniAction\config.json = { "server_url": "<url>" }
  3. Daftarkan protokol raniaction:// di HKCU\Software\Classes\raniaction
     -> browser memanggil handler saat klik action RANI.
.PARAMETER ServerUrl
  Origin RANI, mis. https://rani.corp.local:8091 (tanpa path).
.PARAMETER Uninstall
  Hapus registrasi protokol + file handler.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-action-handler.ps1 -ServerUrl https://rani.corp.local:8091
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ServerUrl,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'

$destDir = Join-Path $env:ProgramData 'RaniAction'
$dest = Join-Path $destDir 'rani-action.ps1'
$cfgPath = Join-Path $destDir 'config.json'
$regRoot = 'HKCU:\Software\Classes\raniaction'

if ($Uninstall) {
    if (Test-Path $regRoot) { Remove-Item -Path $regRoot -Recurse -Force }
    if (Test-Path $destDir) { Remove-Item -Path $destDir -Recurse -Force }
    Write-Host 'raniaction:// dihapus.'
    exit 0
}

if ($ServerUrl -notmatch '^https?://[A-Za-z0-9._\-]+(:[0-9]{1,5})?/?$') {
    throw "ServerUrl tidak valid: '$ServerUrl'. Contoh: https://rani.corp.local:8091"
}
$origin = $ServerUrl.TrimEnd('/')

New-Item -ItemType Directory -Force -Path $destDir | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot 'rani-action.ps1') -Destination $dest -Force

$cfg = [ordered]@{ server_url = $origin } | ConvertTo-Json
Set-Content -Path $cfgPath -Value $cfg -Encoding UTF8

Remove-Item -Path $regRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -Path $regRoot -Force | Out-Null
Set-ItemProperty -Path $regRoot -Name '(Default)' -Value 'URL:RANI Action Protocol'
Set-ItemProperty -Path $regRoot -Name 'URL Protocol' -Value ''
New-Item -Path (Join-Path $regRoot 'shell') -Force | Out-Null
New-Item -Path (Join-Path $regRoot 'shell\open') -Force | Out-Null
$cmdKey = Join-Path $regRoot 'shell\open\command'
New-Item -Path $cmdKey -Force | Out-Null
$cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $dest + '" "%1"'
Set-ItemProperty -Path $cmdKey -Name '(Default)' -Value $cmd

Write-Host ""
Write-Host "Handler raniaction:// terpasang." -ForegroundColor Green
Write-Host "  server_url : $origin"
Write-Host "  handler    : $dest"
Write-Host "  config     : $cfgPath"
Write-Host ""
Write-Host "Coba: buka $origin di browser -> Assets -> hover hostname -> klik 'Remote Desktop'."
Write-Host "Hapus: install-action-handler.ps1 -ServerUrl $origin -Uninstall"
