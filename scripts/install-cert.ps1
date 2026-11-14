<#
.SYNOPSIS
    Pasang sertifikat code-signing internal RANI di PC Windows (Trusted Root + Trusted Publishers).

.DESCRIPTION
    Dibutuhkan supaya exe yang ditandatangani sertifikat internal dianggap sah dan
    Windows berhenti menampilkan "Unknown publisher". Jalankan sebagai Administrator.

    .\install-cert.ps1 -CerPath .\rani-push-signing.cer
    .\install-cert.ps1 -CerPath .\rani-push-signing.cer -Remove   # cabut

.NOTES
    Sertifikat self-signed hanya untuk PC yang kita kelola. Untuk PC di luar kendali,
    gunakan sertifikat code-signing dari CA publik (OV/EV).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CerPath,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Jalankan PowerShell sebagai Administrator.'
}
if (-not (Test-Path $CerPath)) { throw "File sertifikat tidak ditemukan: $CerPath" }

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Resolve-Path $CerPath).Path)
Write-Host ("subject : " + $cert.Subject)
Write-Host ("sha256  : " + $cert.Thumbprint)

foreach ($storeName in @('Root', 'TrustedPublisher')) {
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($storeName, 'LocalMachine')
    $store.Open('ReadWrite')
    try {
        if ($Remove) {
            $found = $store.Certificates.Find('FindByThumbprint', $cert.Thumbprint, $false)
            foreach ($c in $found) { $store.Remove($c) }
            Write-Host "removed dari $storeName"
        } else {
            $store.Add($cert)
            Write-Host "added ke $storeName"
        }
    } finally {
        $store.Close()
    }
}

if (-not $Remove) {
    Write-Host ''
    Write-Host 'Selesai. Verifikasi:'
    Write-Host '  Get-AuthenticodeSignature .\raniPush-signed.exe | Format-List Status, SignerCertificate'
    Write-Host 'Status harus "Valid" (bukan "UnknownError"/"NotSigned").'
}

# Info tambahan: cara cek apakah Smart App Control / ASR yang memblokir
Write-Host ''
Write-Host 'Diagnosa blokir (jalankan bila exe masih ditolak):'
Write-Host '  Get-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy -Name VerifiedAndReputablePolicyState -ErrorAction SilentlyContinue'
Write-Host '    0 = Smart App Control off, 1 = on (enforce), 2 = evaluation'
Write-Host '  Get-MpPreference | Select-Object -ExpandProperty AttackSurfaceReductionRules_Ids'