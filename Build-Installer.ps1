param(
    [string]$SourceDir = 'dist\ArabicLens',
    [string]$OutputDir = 'dist',
    [string]$CompilerPath = ''
)

$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$prefix = $workspace.TrimEnd('\') + '\'

function Resolve-WorkspacePath([string]$value, [bool]$mustExist) {
    $candidate = if ([IO.Path]::IsPathRooted($value)) { $value } else { Join-Path $workspace $value }
    $full = [IO.Path]::GetFullPath($candidate)
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path must remain inside the workspace: $full"
    }
    if ($mustExist -and -not (Test-Path -LiteralPath $full)) { throw "Missing path: $full" }
    return $full
}

$source = Resolve-WorkspacePath $SourceDir $true
$output = Resolve-WorkspacePath $OutputDir $false
New-Item -ItemType Directory -Force -Path $output | Out-Null

$versionSource = Get-Content -LiteralPath (Join-Path $workspace 'arabic_lens\version.py') -Raw
$versionMatch = [regex]::Match($versionSource, 'APP_VERSION\s*=\s*["'']([0-9]+\.[0-9]+\.[0-9]+)["'']')
if (-not $versionMatch.Success) { throw 'Could not read APP_VERSION from arabic_lens/version.py.' }
$appVersion = $versionMatch.Groups[1].Value
$resource = Get-Content -LiteralPath (Join-Path $workspace 'assets\version.txt') -Raw
foreach ($field in @('FileVersion', 'ProductVersion')) {
    $pattern = "StringStruct\('$field','" + [regex]::Escape($appVersion) + "'\)"
    if ($resource -notmatch $pattern) { throw "assets/version.txt $field does not match $appVersion." }
}
$parts = $appVersion.Split('.')
$tuple = '(' + (($parts + @('0')) -join ',') + ')'
foreach ($field in @('filevers', 'prodvers')) {
    if ($resource -notmatch ([regex]::Escape("$field=$tuple"))) {
        throw "assets/version.txt $field does not match $appVersion.0."
    }
}
$manifest = Get-Content -LiteralPath (Join-Path $workspace 'assets\app.manifest') -Raw
if ($manifest -notmatch ([regex]::Escape("version=`"$appVersion.0`""))) {
    throw "assets/app.manifest assembly version does not match $appVersion.0."
}

$required = @(
    'ArabicLens.exe',
    'README.md',
    'THIRD_PARTY.md',
    '_internal\arabic_lens\data\cpu-en-ar\model\model.bin',
    '_internal\arabic_lens\data\cpu-en-ar\sentencepiece.model'
)
foreach ($entry in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $entry) -PathType Leaf)) {
        throw "Incomplete packaged app: $entry is missing from $source"
    }
}
$frozenVersion = (Get-Item -LiteralPath (Join-Path $source 'ArabicLens.exe')).VersionInfo.FileVersion
if ($frozenVersion -ne $appVersion) {
    throw "Packaged executable is version $frozenVersion, but source is $appVersion. Rebuild the application first."
}

if (-not $CompilerPath) {
    $candidates = @(
        (Join-Path $workspace 'artifacts\installer-tools\InnoSetup\ISCC.exe'),
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 7\ISCC.exe'
    )
    $CompilerPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $CompilerPath -or -not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) {
    throw 'Inno Setup 6 or 7 ISCC.exe is required to build the installer. Install it from jrsoftware.org/isdl.php or pass -CompilerPath.'
}

$script = Join-Path $workspace 'installer\ArabicLens.iss'
$arguments = @(
    "/DAppVersion=$appVersion",
    "/DSourceDir=$source",
    "/DOutputDir=$output",
    $script
)
& $CompilerPath @arguments
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed with exit code $LASTEXITCODE." }

$installer = Join-Path $output 'ArabicLens-Setup.exe'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'Compiler did not produce ArabicLens-Setup.exe.' }
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$sidecar = Join-Path $output 'ArabicLens-Setup.exe.sha256'
Set-Content -LiteralPath $sidecar -Value "$hash  ArabicLens-Setup.exe" -Encoding ascii
$sizeMiB = [math]::Round((Get-Item -LiteralPath $installer).Length / 1MB, 1)
Write-Output "Installer: $installer ($sizeMiB MiB)"
Write-Output "SHA-256: $hash"
Write-Output "Checksum: $sidecar"
