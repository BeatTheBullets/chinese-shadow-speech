<#
.SYNOPSIS
  Builds the per-user Windows installer: dist\chinese-shadow-speech-<Version>-setup.exe (relative to the repo root).
.PARAMETER Version
  X.Y.Z. Defaults to the version in backend\pyproject.toml.
.NOTES
  Needs git, node/npm and Inno Setup 6 (ISCC.exe). Every download is pinned in versions.json and its SHA-256 is verified
  before anything is extracted. Staging and the download cache live under <repo>\build (git-ignored).
#>
[CmdletBinding()]
param([string]$Version = '')

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar in Windows PowerShell 5.1
Add-Type -AssemblyName System.IO.Compression.FileSystem

$Here = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $Here '..\..')).Path
$Build = Join-Path $Root 'build'
$Cache = Join-Path $Build 'cache'
$Stage = Join-Path $Build 'stage'
$Dist = Join-Path $Root 'dist'

function Fail([string]$msg) { throw $msg }
function Check-Exit([string]$what) { if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit code $LASTEXITCODE)" } }
# Native programs write progress and warnings to stderr. Under Windows PowerShell 5.1 with $ErrorActionPreference = 'Stop'
# (and output redirected, as CI does) each such line would become a terminating NativeCommandError, so run them with
# 'Continue' and judge only by the exit code.
function Invoke-Native([string]$what, [scriptblock]$cmd) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $cmd } finally { $ErrorActionPreference = $saved }
    Check-Exit $what
}

# ---- version: from -Version, else pyproject.toml; always validated as X.Y.Z
$pyproject = Get-Content -Raw -Encoding UTF8 (Join-Path $Root 'backend\pyproject.toml')
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') { Fail 'no version in backend\pyproject.toml' }
$ProjectVersion = $Matches[1]
if (-not $Version) { $Version = $ProjectVersion }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "Version must look like X.Y.Z, got '$Version'" }
if ($Version -ne $ProjectVersion) { Write-Warning "Version $Version differs from backend\pyproject.toml ($ProjectVersion)" }

$pins = Get-Content -Raw -Encoding UTF8 (Join-Path $Here 'versions.json') | ConvertFrom-Json

# ---- pinned, checksum-verified downloads
function Get-Pinned($pin) {
    New-Item -ItemType Directory -Force -Path $Cache | Out-Null
    $path = Join-Path $Cache $pin.file
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        if (-not (Test-Path $path)) {
            Write-Host "Downloading $($pin.url)"
            try { Invoke-WebRequest -UseBasicParsing -Uri $pin.url -OutFile $path }
            catch {
                Remove-Item -Force -ErrorAction SilentlyContinue $path
                if ($attempt -eq 3) { throw }
                Start-Sleep -Seconds (5 * $attempt)
                continue
            }
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        if ($actual -eq $pin.sha256.ToLowerInvariant()) { return $path }
        Remove-Item -Force $path   # a corrupt or stale cache entry: fetch again; the third mismatch is fatal
        if ($attempt -eq 3) { Fail "SHA-256 mismatch for $($pin.file): expected $($pin.sha256), got $actual" }
    }
    Fail "could not download $($pin.url)"
}

function Expand-Zip([string]$zip, [string]$dest) {
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $dest)
}

function Find-Iscc {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
        if (-not $base) { continue }
        $p = Join-Path $base 'Inno Setup 6\ISCC.exe'
        if (Test-Path $p) { return $p }
    }
    Fail 'Inno Setup 6 (ISCC.exe) not found; install it (choco install innosetup) or put it on PATH'
}

$iscc = Find-Iscc
Write-Host "Building chinese-shadow-speech $Version"

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage, $Dist | Out-Null

# ---- python (tar.gz; tar.exe ships with Windows 10 1803+ and the runners)
$tgz = Get-Pinned $pins.python
$pyTmp = Join-Path $Build 'python-extract'
if (Test-Path $pyTmp) { Remove-Item -Recurse -Force $pyTmp }
New-Item -ItemType Directory -Force -Path $pyTmp | Out-Null
Invoke-Native 'tar (python)' { & "$env:SystemRoot\System32\tar.exe" -xzf $tgz -C $pyTmp }
if (-not (Test-Path (Join-Path $pyTmp 'python\python.exe')) -or -not (Test-Path (Join-Path $pyTmp 'python\pythonw.exe'))) {
    Fail 'python archive lacks python.exe/pythonw.exe'
}
Move-Item (Join-Path $pyTmp 'python') (Join-Path $Stage 'python')
Remove-Item -Recurse -Force $pyTmp
Get-ChildItem -Recurse -File -Filter *.pdb (Join-Path $Stage 'python') | Remove-Item -Force   # debug symbols, tens of MB

# ---- uv
$tmp = Join-Path $Build 'x-uv'
Expand-Zip (Get-Pinned $pins.uv) $tmp
Copy-Item (Join-Path $tmp 'uv.exe') (Join-Path $Stage 'uv.exe')
Remove-Item -Recurse -Force $tmp

# ---- tools: ffmpeg (LGPL build), ffprobe, deno
$tools = Join-Path $Stage 'tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$tmp = Join-Path $Build 'x-ffmpeg'
Expand-Zip (Get-Pinned $pins.ffmpeg) $tmp
$ffroot = Get-ChildItem -Directory $tmp | Select-Object -First 1
foreach ($f in 'ffmpeg.exe', 'ffprobe.exe') { Copy-Item (Join-Path $ffroot.FullName "bin\$f") (Join-Path $tools $f) }
Copy-Item (Join-Path $ffroot.FullName 'LICENSE.txt') (Join-Path $tools 'ffmpeg-LICENSE.txt')
Remove-Item -Recurse -Force $tmp
$tmp = Join-Path $Build 'x-deno'
Expand-Zip (Get-Pinned $pins.deno) $tmp
Copy-Item (Join-Path $tmp 'deno.exe') (Join-Path $tools 'deno.exe')
Remove-Item -Recurse -Force $tmp
foreach ($f in 'ffmpeg.exe', 'ffprobe.exe', 'deno.exe') {
    if (-not (Test-Path (Join-Path $tools $f))) { Fail "missing tools\$f" }
}
@"
Third-party programs shipped with this app (unmodified):
  tools\ffmpeg.exe, tools\ffprobe.exe  FFmpeg $($pins.ffmpeg.version), $($pins.ffmpeg.license)
                                       Source and build scripts: https://github.com/BtbN/FFmpeg-Builds and https://ffmpeg.org/
  tools\deno.exe                       Deno $($pins.deno.version), $($pins.deno.license) (runs yt-dlp's YouTube challenge solver)
  uv.exe                               uv $($pins.uv.version), $($pins.uv.license)
  python\                              CPython $($pins.python.version) (python-build-standalone), $($pins.python.license)
"@ | Set-Content -Encoding UTF8 (Join-Path $tools 'THIRD-PARTY.txt')

# ---- frontend
Push-Location (Join-Path $Root 'frontend')
try {
    Invoke-Native 'npm ci' { & npm.cmd ci }
    Invoke-Native 'npm run build' { & npm.cmd run build }
} finally { Pop-Location }
$dist = Join-Path $Root 'frontend\dist'
if (-not (Test-Path (Join-Path $dist 'index.html'))) { Fail 'frontend build produced no frontend\dist\index.html' }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'frontend') | Out-Null
Copy-Item -Recurse $dist (Join-Path $Stage 'frontend\dist')

# ---- backend source: the committed tree only (git archive HEAD), so no .venv, caches or local data
$zip = Join-Path $Build 'backend.zip'
if (Test-Path $zip) { Remove-Item -Force $zip }
Invoke-Native 'git archive' { & git.exe -C $Root archive --format=zip -o $zip HEAD backend }
$tmp = Join-Path $Build 'x-backend'
Expand-Zip $zip $tmp
Move-Item (Join-Path $tmp 'backend') (Join-Path $Stage 'backend')
Remove-Item -Recurse -Force $tmp
Remove-Item -Force $zip
foreach ($f in 'pyproject.toml', 'uv.lock') {
    if (-not (Test-Path (Join-Path $Stage "backend\$f"))) { Fail "backend\$f missing from the archive (commit it first)" }
}

# ---- launcher files
foreach ($f in 'bootstrap.py', 'progress.html', 'icon.ico') { Copy-Item (Join-Path $Here $f) (Join-Path $Stage $f) }

# ---- installer
$out = Join-Path $Dist "chinese-shadow-speech-$Version-setup.exe"
if (Test-Path $out) { Remove-Item -Force $out }
Invoke-Native 'ISCC' { & $iscc "/DAppVersion=$Version" "/DStageDir=$Stage" "/DOutDir=$Dist" "/Qp" (Join-Path $Here 'shadow.iss') }
if (-not (Test-Path $out)) { Fail "installer not found at $out" }
$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host "Built $out ($mb MB)"
