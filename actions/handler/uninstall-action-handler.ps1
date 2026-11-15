<#
.SYNOPSIS  Hapus handler raniaction:// dari PC ini (kebalikan installer).
#>
$ErrorActionPreference = 'Stop'
$regRoot = 'HKCU:\Software\Classes\raniaction'
$destDir = Join-Path $env:ProgramData 'RaniAction'
if (Test-Path $regRoot) { Remove-Item -Path $regRoot -Recurse -Force }
if (Test-Path $destDir) { Remove-Item -Path $destDir -Recurse -Force }
Write-Host 'raniaction:// dihapus dari PC ini.'
