param([Parameter(Mandatory=$true)][string]$NotesFile,
      [Parameter(Mandatory=$true)][string]$VerificationFile)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath $VerificationFile)) { throw 'Release verification missing.' }
if (-not ((Get-Content -LiteralPath $VerificationFile -Raw | ConvertFrom-Json).success)) { throw 'Release verification did not pass.' }
if (git status --porcelain) { throw 'Commit and push the release source before publishing.' }
$version = [regex]::Match((Get-Content arabic_lens/version.py -Raw), 'APP_VERSION = "([0-9.]+)"').Groups[1].Value
if (-not $version) { throw 'Version missing.' }
$repo = 'farhanr3001/ocr-translate'
$tag = 'v' + $version
$files = @((Get-Item -LiteralPath dist/ArabicLens-Setup.exe).FullName,
           (Get-Item -LiteralPath dist/ArabicLens-Setup.exe.sha256).FullName)
$packages = @(Get-ChildItem -LiteralPath dist -Filter 'ArabicLens-Update-*.zip')
if (-not ($packages.Name -contains 'ArabicLens-Update-full.zip')) { throw 'Full file-update fallback missing.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($package in $packages) {
    $archive = [IO.Compression.ZipFile]::OpenRead($package.FullName)
    try {
        $reader = [IO.StreamReader]::new($archive.GetEntry('update.json').Open())
        try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($manifest.version -ne $version) { throw 'Stale update package in dist; do not publish it.' }
    } finally { $archive.Dispose() }
    $files += @($package.FullName, $package.FullName + '.sha256')
}
foreach ($file in $files | Where-Object { -not $_.EndsWith('.sha256') }) {
    $expected = (Get-Content -LiteralPath ($file + '.sha256') -Raw).Split()[0]
    if ((Get-FileHash -LiteralPath $file).Hash.ToLowerInvariant() -ne $expected) { throw 'Asset checksum mismatch.' }
}
$env:GIT_TERMINAL_PROMPT = '0'
$credentialLines = "protocol=https`nhost=github.com`n`n" | git credential fill
if ($LASTEXITCODE -ne 0) { throw 'GitHub authentication unavailable.' }
$credentialPassword = ($credentialLines | Where-Object { $_.StartsWith('password=') } | Select-Object -First 1).Substring(9)
$headers = @{ Authorization="Bearer $credentialPassword"; Accept='application/vnd.github+json'; 'X-GitHub-Api-Version'='2022-11-28'; 'User-Agent'='ArabicLens-Release' }
$api = "https://api.github.com/repos/$repo/releases"
$commit = (git rev-parse HEAD).Trim()
try {
    try {
        $release = Invoke-RestMethod -Uri "$api/tags/$tag" -Headers $headers
        if (-not $release.draft) { throw 'Never overwrite a published release.' }
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
        $body = @{tag_name=$tag;target_commitish=$commit;name="Arabic Lens $version";body=(Get-Content -LiteralPath $NotesFile -Raw);draft=$true;prerelease=$false} | ConvertTo-Json
        $release = Invoke-RestMethod -Method Post -Uri $api -Headers $headers -ContentType 'application/json' -Body $body
    }
    $upload = $release.upload_url -replace '\{\?name,label\}$',''
    foreach ($file in $files) {
        $name = [IO.Path]::GetFileName($file)
        if ($release.assets.name -contains $name) { throw "Draft already contains $name" }
        $asset = Invoke-RestMethod -Method Post -Uri ($upload+'?name='+[Uri]::EscapeDataString($name)) -Headers $headers -ContentType 'application/octet-stream' -InFile $file
        if ($asset.size -ne (Get-Item -LiteralPath $file).Length) { throw 'Upload size mismatch.' }
        $hash = 'sha256:' + (Get-FileHash -LiteralPath $file).Hash.ToLowerInvariant()
        if ($asset.digest -and $asset.digest -ne $hash) { throw 'Upload digest mismatch.' }
    }
    $release = Invoke-RestMethod -Uri ($api+'/'+$release.id) -Headers $headers
    if ($release.assets.Count -ne $files.Count) { throw 'Unexpected release assets.' }
    $published = Invoke-RestMethod -Method Patch -Uri ($api+'/'+$release.id) -Headers $headers -ContentType 'application/json' -Body '{"draft":false}'
    @{url=$published.html_url;commit=$commit;tag=$tag;assets=$files.Count} | ConvertTo-Json | Set-Content ("artifacts/publication-$version.json")
    Write-Output ('Published: '+$published.html_url)
} finally {
    $headers.Clear(); $credentialPassword=$null; $credentialLines=$null
}
