# Dipakai oleh build-and-push.bat bila "docker login" ke ECR gagal dengan
#   error storing credentials ... The stub received bad data
# Penyebab: token login ECR lebih panjang dari batas Windows Credential Manager yang dipakai
# credential helper Docker Desktop. Solusi: salin konfigurasi Docker Anda ke folder sementara
# TANPA credsStore/credHelpers (dan dengan entri "auths" dummy, lihat catatan di bawah), lalu jalankan login, build, dan push dengan DOCKER_CONFIG itu.
# Konfigurasi asli di %USERPROFILE%\.docker tidak diubah.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File docker-config-nocreds.ps1 <folder-tujuan>
param([Parameter(Mandatory = $true)][string]$Dest)

$ErrorActionPreference = 'Stop'
$src = Join-Path $env:USERPROFILE '.docker'
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$cfg = Join-Path $src 'config.json'
if (Test-Path $cfg) {
    $o = Get-Content $cfg -Raw | ConvertFrom-Json
    foreach ($name in 'credsStore', 'credHelpers') {
        if ($o.PSObject.Properties.Name -contains $name) { $o.PSObject.Properties.Remove($name) }
    }
    # PENTING: bila "auths" kosong dan tidak ada credsStore/credHelpers, Docker memilih credential store
    # bawaan platform (di Windows: wincred/desktop) -- galat yang sama muncul lagi. Satu entri dummy di
    # "auths" membuat Docker memakai penyimpanan berkas biasa.
    if (-not ($o.PSObject.Properties.Name -contains 'auths') -or $null -eq $o.auths) {
        $o | Add-Member -NotePropertyName 'auths' -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    if (@($o.auths.PSObject.Properties).Count -eq 0) {
        $o.auths | Add-Member -NotePropertyName 'localhost.invalid' -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    $json = $o | ConvertTo-Json -Depth 20
} else {
    $json = '{"auths":{"localhost.invalid":{}}}'
}
[IO.File]::WriteAllText((Join-Path $Dest 'config.json'), $json, (New-Object Text.UTF8Encoding($false)))

# Context (mis. desktop-linux) dan plugin CLI (buildx) ikut disalin agar docker tetap menemukan engine dan builder.
foreach ($dir in 'contexts', 'cli-plugins') {
    $from = Join-Path $src $dir
    if (Test-Path $from) { Copy-Item $from (Join-Path $Dest $dir) -Recurse -Force }
}
Write-Host "Konfigurasi Docker sementara dibuat di $Dest (tanpa credential store)."
