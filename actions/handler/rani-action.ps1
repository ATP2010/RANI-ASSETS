<#
.SYNOPSIS
  Handler protokol "raniaction://" untuk RANI (gaya Lansweeper Actions).
.DESCRIPTION
  Dipanggil oleh browser saat user klik action ber-kind "script" di web RANI.
  URL masuk: raniaction://run?f=<file>&exp=<unix>&sig=<hmac>&a=<args>

  Langkah:
  1. Baca konfigurasi dari %ProgramData%\RaniAction\config.json (dibuat installer).
  2. Validasi: f = nama file polos (tanpa path), ekstensi diizinkan.
  3. Download file dari <server_url>/actions/files/<file>?exp=&sig= (read-only, HMAC).
  4. Jalankan file dengan arg ter-decode (hanya karakter aman).
     Arg divalidasi ketat: huruf/angka/./:/-/, jadi tidak ada yang bisa di-inject.
.PARAMETER Uri
  URI lengkap "raniaction://run?f=...&exp=...&sig=...&a=..." (dikirim browser sebagai %1).
.PARAMETER SelfTest
  Uji-parsing URI tanpa download/eksekusi (dipakai untuk CI).
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Uri,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'

$AllowedExt = @('.bat', '.cmd', '.ps1', '.exe', '.msi')
$AllowedArg = '^[A-Za-z0-9._:\-]+$'
$MaxDownloadBytes = 64MB
$DownloadTimeoutSec = 20

function Show-Error($Message) {
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        [System.Windows.Forms.MessageBox]::Show($Message, 'RANI Action', 'OK', 'Error') | Out-Null
    } catch {
        Write-Error $Message
    }
}

function Get-ActionUri([string]$Raw) {
    $prefix = 'raniaction://'
    if (-not $Raw.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "bukan URI raniaction:// ($Raw)"
    }
    $query = $Raw.Substring($prefix.Length) -split '\?', 2 | Select-Object -Last 1
    $pairs = @{}
    foreach ($part in ($query -split '&')) {
        $kv = $part -split '=', 2
        if ($kv.Count -ne 2) { continue }
        $pairs[[Uri]::UnescapeDataString($kv[0])] = [Uri]::UnescapeDataString($kv[1])
    }
    return $pairs
}

function Get-ServerOrigin {
    $cfgPath = Join-Path $env:ProgramData 'RaniAction\config.json'
    if (-not (Test-Path $cfgPath)) {
        throw "konfigurasi tidak ditemukan: $cfgPath`nJalankan install-action-handler.ps1 -ServerUrl <url> dulu."
    }
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $origin = ([string]$cfg.server_url).TrimEnd('/')
    if ($origin -notmatch '^https?://[A-Za-z0-9._\-]+(:[0-9]{1,5})?$') {
        throw "server_url tidak valid: $origin"
    }
    return $origin
}

function Split-Args([string]$ArgLine) {
    if ([string]::IsNullOrWhiteSpace($ArgLine)) { return @() }
    $tokens = $ArgLine -split '\s+' | Where-Object { $_ -ne '' }
    foreach ($t in $tokens) {
        if ($t -notmatch $AllowedArg) {
            throw "argumen tidak diizinkan: '$t' (hanya huruf, angka, titik, titik dua, strip)"
        }
    }
    return $tokens
}

try {
    $p = Get-ActionUri $Uri
    $file = [string]$p['f']
    $exp = [string]$p['exp']
    $sig = [string]$p['sig']
    $argLine = [string]$p['a']

    if ([string]::IsNullOrWhiteSpace($file)) { throw 'parameter f (nama file) wajib ada' }
    if ($file -match '[\\/]' -or $file -notmatch '^[A-Za-z0-9._\-]+$') {
        throw "nama file tidak valid: '$file'"
    }
    $ext = [IO.Path]::GetExtension($file).ToLowerInvariant()
    if ($AllowedExt -notcontains $ext) {
        throw "ekstensi '$ext' tidak diizinkan ({0})" -f ($AllowedExt -join ' ')
    }
    if ([string]::IsNullOrWhiteSpace($exp) -or [string]::IsNullOrWhiteSpace($sig)) {
        throw 'parameter exp/sig wajib ada'
    }
    $expNum = 0L
    if (-not [long]::TryParse($exp, [ref]$expNum)) { throw 'exp bukan angka' }
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($expNum -lt $now) { throw 'token kedaluwarsa — klik ulang action di web RANI' }

    $argTokens = Split-Args $argLine

    if ($SelfTest) {
        $server = try { Get-ServerOrigin } catch { 'https://PLACEHOLDER-NOT-CONFIGURED' }
        $selfUrl = "$server/actions/files/$([Uri]::EscapeDataString($file))?exp=$exp&sig=$sig"
        Write-Output ("SELFTEST OK file={0} ext={1} args=[{2}] url={3}" -f $file, $ext, ($argTokens -join ' '), $selfUrl)
        exit 0
    }

    $server = Get-ServerOrigin
    $downloadUrl = "$server/actions/files/$([Uri]::EscapeDataString($file))?exp=$exp&sig=$sig"

    $tmpRoot = Join-Path $env:TEMP 'rani-action'
    New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
    $target = Join-Path $tmpRoot $file

    $req = [System.Net.HttpWebRequest]::Create($downloadUrl)
    $req.Method = 'GET'
    $req.Timeout = $DownloadTimeoutSec * 1000
    $resp = $req.GetResponse()
    $ms = [System.IO.MemoryStream]::new()
    $buf = New-Object byte[] 8192
    $total = 0L
    while (($read = $resp.GetResponseStream().Read($buf, 0, $buf.Length)) -gt 0) {
        $total += $read
        if ($total -gt $MaxDownloadBytes) { throw 'file terlalu besar' }
        $ms.Write($buf, 0, $read)
    }
    [System.IO.File]::WriteAllBytes($target, $ms.ToArray())
    Write-Output "downloaded $file -> $target ($total bytes)"

    switch ($ext) {
        '.ps1' { Start-Process 'powershell.exe' -ArgumentList (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$target`"") + $argTokens) -Wait }
        '.bat' { Start-Process 'cmd.exe' -ArgumentList (@('/c', "`"$target`"") + $argTokens) -Wait }
        '.cmd' { Start-Process 'cmd.exe' -ArgumentList (@('/c', "`"$target`"") + $argTokens) -Wait }
        '.exe' { Start-Process $target -ArgumentList $argTokens }
        '.msi' { Start-Process 'msiexec.exe' -ArgumentList (@('/i', "`"$target`"") + $argTokens) }
        default { throw "tidak ada runner untuk $ext" }
    }
    exit 0
} catch {
    if ($SelfTest) {
        Write-Host "SELFTEST FAIL: $($_.Exception.Message)"
        exit 3
    }
    Show-Error "RANI Action gagal:`n$($_.Exception.Message)"
    exit 1
}
