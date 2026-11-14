<#
.SYNOPSIS
    Install raniPush di Windows: copy exe, daftarkan Task Scheduler, push pertama.

.DESCRIPTION
    Jalankan sebagai Administrator (PowerShell). Contoh:
      .\install-agent.ps1 -Server 192.168.88.92:8091
      .\install-agent.ps1 -Server 192.168.88.92:8091 -ExePath .\raniPush-signed.exe

    Agent 0.2+ tidak butuh token: server mengenali PC dari machine_id pada push pertama.
    -Token hanya dipakai bila server di-set RANI_TOKENLESS_PUSH=0 (mode HMAC legacy).
    Agent push tiap $IntervalMinutes menit dan langsung sekali di akhir instalasi.
    Config + spool ada di %PROGRAMDATA%\Rani.

.NOTES
    Exit code: 0 sukses, 1 gagal. Tidak menginstall software lain.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$Token,
    [string]$ExePath = (Join-Path $PSScriptRoot 'raniPush.exe'),
    [string]$InstallDir = 'C:\Rani',
    [int]$IntervalMinutes = 60,
    [string]$TaskName = 'RaniPush'
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Jalankan PowerShell sebagai Administrator.'
    }
}

Assert-Admin

if (-not (Test-Path $ExePath)) { throw "raniPush.exe tidak ditemukan di $ExePath" }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$target = Join-Path $InstallDir 'raniPush.exe'
Copy-Item -Force $ExePath $target
Write-Host "exe     : $target"

if ($Token) {
    & $target --enroll $Token $Server
    if ($LASTEXITCODE -ne 0) { throw "enroll gagal (exit $LASTEXITCODE)" }
    Write-Host 'enroll  : ok (mode HMAC legacy)'
} else {
    Write-Host 'enroll  : tidak perlu (agent 0.2+ langsung push tanpa token)'
}

$action = New-ScheduledTaskAction -Execute $target -Argument $Server
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "task    : $TaskName tiap $IntervalMinutes menit"

& $target $Server
if ($LASTEXITCODE -ne 0) {
    Write-Warning "push pertama gagal (exit $LASTEXITCODE). Payload di-spool dan dicoba lagi oleh task."
} else {
    Write-Host 'push    : ok'
}

Write-Host ''
Write-Host 'Selesai. Cek di UI: http://' + $Server + '/assets'