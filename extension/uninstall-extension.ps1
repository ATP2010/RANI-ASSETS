<#
.SYNOPSIS Hapus RANI Actions (registrasi + file) dari PC ini.
#>
param([string]$ServerUrl = "")
$ErrorActionPreference = 'Stop'
$keys = @(
    'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.rani.action_host',
    'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.rani.action_host',
    'HKCU:\Software\Chromium\NativeMessagingHosts\com.rani.action_host'
)
foreach ($k in $keys) { if (Test-Path $k) { Remove-Item -Path $k -Recurse -Force } }
$destDir = Join-Path $env:ProgramData 'rani-action'
if (Test-Path $destDir) { Remove-Item -Path $destDir -Recurse -Force }
Write-Host 'RANI Actions dihapus dari PC ini (registrasi + file).'
