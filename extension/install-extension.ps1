<#
.SYNOPSIS
  Pasang "RANI Actions" extension + native host di PC pengguna (tanpa admin).
.DESCRIPTION
  1. Menyalin rani-action-host.exe ke %ProgramData%\rani-action\rani-action-host.exe
  2. Menulis config.json { server_origin }
  3. Menulis native messaging manifest com.rani.action_host.json
  4. Mendaftarkan HKCU\Software\Google\Chrome\NativeMessagingHosts\com.rani.action_host
     dan HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.rani.action_host
  5. Mencetak instruksi "Load unpacked" untuk memasang ekstensi dari folder zip
     (developer mode, tanpa Web Store).
.PARAMETER ServerUrl
  Origin RANI, mis. https://rani.corp.local:8091
.PARAMETER HostExe
  Path ke rani-action-host.exe hasil download (default: C:\Program Files\...\rani-action-host.exe
  atau file rani-action-host.exe di folder ini).
.PARAMETER Uninstall
  Hapus registrasi + file.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-extension.ps1 -ServerUrl https://rani.corp.local:8091
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerUrl,
    [string]$HostExe = "",
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'

$destDir = Join-Path $env:ProgramData 'rani-action'
$destExe = Join-Path $destDir 'rani-action-host.exe'
$cfgPath = Join-Path $destDir 'config.json'
$manifestPath = Join-Path $destDir 'com.rani.action_host.json'

$chromeKey = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.rani.action_host'
$edgeKey   = 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.rani.action_host'
$chromiumKey = 'HKCU:\Software\Chromium\NativeMessagingHosts\com.rani.action_host'

if ($Uninstall) {
    foreach ($k in @($chromeKey, $edgeKey, $chromiumKey)) {
        if (Test-Path $k) { Remove-Item -Path $k -Recurse -Force }
    }
    if (Test-Path $destDir) { Remove-Item -Path $destDir -Recurse -Force }
    Write-Host 'RANI Actions dihapus dari PC ini (registrasi + file).'
    exit 0
}

if ($ServerUrl -notmatch '^https?://[A-Za-z0-9._\-]+(:[0-9]{1,5})?/?$') {
    throw "ServerUrl tidak valid: '$ServerUrl'. Contoh: https://rani.corp.local:8091"
}
$origin = $ServerUrl.TrimEnd('/')

# cari host exe: argumen eksplisit, atau folder script ini, atau download default
if (-not $HostExe) {
    $candidates = @(
        (Join-Path $PSScriptRoot 'rani-action-host.exe'),
        (Join-Path $env:USERPROFILE 'Downloads\rani-action-host.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $HostExe = $c; break }
    }
}
if (-not $HostExe -or -not (Test-Path $HostExe)) {
    throw @"
Host exe tidak ditemukan.
Download dulu dari /agents (bagian Download agent) atau
  $origin/downloads/rani-action-host.exe
lalu jalankan lagi:
  install-extension.ps1 -ServerUrl $origin -HostExe C:\path\to\rani-action-host.exe
"@
}

New-Item -ItemType Directory -Force -Path $destDir | Out-Null
Copy-Item -Path $HostExe -Destination $destExe -Force

$cfg = [ordered]@{ server_origin = $origin } | ConvertTo-Json
Set-Content -Path $cfgPath -Value $cfg -Encoding UTF8

$manifest = [ordered]@{
    name = 'com.rani.action_host'
    description = 'RANI Actions native host (Lansweeper Shell Execute equivalent)'
    path = $destExe
    type = 'stdio'
    allowed_origins = @('chrome-extension://lfkhhkhfcfkcmeefpijfoojicckpnkjo/')
} | ConvertTo-Json
Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

foreach ($k in @($chromeKey, $edgeKey, $chromiumKey)) {
    Remove-Item -Path $k -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -Path $k -Force | Out-Null
    Set-ItemProperty -Path $k -Name '(Default)' -Value $manifestPath
}

Write-Host ""
Write-Host "Native host terpasang:" -ForegroundColor Green
Write-Host "  file     : $destExe"
Write-Host "  config   : $cfgPath"
Write-Host "  manifest : $manifestPath"
Write-Host ""
Write-Host "Pasang ekstensi (sekali, tanpa Web Store):" -ForegroundColor Cyan
Write-Host "  1. Unzip rani-actions-extension.zip  -> folder berisi manifest.json"
Write-Host "     (download dari $origin/agents -> bagian RANI Actions, atau butuh login)"
Write-Host "  2. Buka  edge://extensions  (Chrome/Edge/Brave/dst)"
Write-Host "  3. Aktifkan 'Developer mode' (toggle kanan atas)"
Write-Host "  4. Klik 'Load unpacked' -> pilih folder hasil unzip tadi"
Write-Host "  5. Reload halaman RANI; klik ikon puzzle -> RANI Actions -> izinkan di situs ini"
Write-Host ""
Write-Host "Hapus: install-extension.ps1 -ServerUrl $origin -Uninstall"
