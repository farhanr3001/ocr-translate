param([switch]$Apply)
# Developer housekeeping only. Does not alter installed app files or user data.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$prefix = $workspace.TrimEnd('\') + '\'
$artifacts = Join-Path $workspace 'artifacts'
$protected = @('dist\ArabicLens', '.venv', '.git', 'arabic_lens\data\cpu-en-ar',
               'artifacts\installer-tools\InnoSetup') | ForEach-Object { [IO.Path]::GetFullPath((Join-Path $workspace $_)) }
$targets = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($relative in @('build', '.pytest_cache', '__pycache__', 'arabic_lens\data\translation',
        'arabic_lens\data\offline-en-ar', 'artifacts\models', 'artifacts\watch-area-staged-build',
        'artifacts\installer-final-stage\build', 'artifacts\translate-en_ar.argosmodel',
        'artifacts\llama-b11146-bin-win-vulkan-x64.zip', 'artifacts\installer-tools\innosetup-6.7.3.exe')) {
    [void]$targets.Add([IO.Path]::GetFullPath((Join-Path $workspace $relative)))
}
# Rebuildable distribution ZIPs; retain the live portable baseline and latest installer.
Get-ChildItem -LiteralPath (Join-Path $workspace 'dist') -File | Where-Object {
    $_.Name -eq 'ArabicLens-Windows-x64.zip' -or $_.Name -like 'ArabicLens-Update-*.zip*'
} | ForEach-Object { [void]$targets.Add($_.FullName) }
if (Test-Path -LiteralPath $artifacts) {
    Get-ChildItem -LiteralPath $artifacts -File -Recurse -Filter 'ArabicLens.exe' | ForEach-Object {
        if (Test-Path -LiteralPath (Join-Path $_.DirectoryName '_internal')) {
            [void]$targets.Add($_.DirectoryName)
        }
    }
    Get-ChildItem -LiteralPath $artifacts -Directory -Filter 'seamless-*' | ForEach-Object {
        foreach ($name in @('prepared', 'backup')) {
            [void]$targets.Add((Join-Path $_.FullName $name))
        }
    }
    Get-ChildItem -LiteralPath $artifacts -File -Recurse | Where-Object {
        $_.Name -eq 'ArabicLens-Setup.exe' -or $_.Name -like 'ArabicLens-Update-*.zip'
    } | ForEach-Object { [void]$targets.Add($_.FullName) }
}
foreach ($relative in @('arabic_lens', 'tests', 'tools')) {
    Get-ChildItem -LiteralPath (Join-Path $workspace $relative) -Directory -Recurse -Filter '__pycache__' |
        ForEach-Object { [void]$targets.Add($_.FullName) }
}
$existing = @($targets | Where-Object { Test-Path -LiteralPath $_ } | Sort-Object Length)
$plan = @()
foreach ($target in $existing) {
    $full = (Resolve-Path -LiteralPath $target).Path
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Target escaped workspace: $full" }
    foreach ($keep in $protected) {
        if ($full.Equals($keep, [StringComparison]::OrdinalIgnoreCase) -or
            $full.StartsWith($keep + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $keep.StartsWith($full + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Protected target: $full" }
    }
    if ($plan | Where-Object { $full.StartsWith($_.Path + '\', [StringComparison]::OrdinalIgnoreCase) }) { continue }
    $item = Get-Item -LiteralPath $full -Force
    $children = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $full -Recurse -Force) } else { @() }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        ($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) { throw "Linked target: $full" }
    $bytes = if ($item.PSIsContainer) { ($children | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum } else { $item.Length }
    $plan += [PSCustomObject]@{Path=$full;Bytes=[long]$bytes;Directory=$item.PSIsContainer}
}
$plan | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $artifacts 'cleanup-plan.json')
$total = ($plan | Measure-Object Bytes -Sum).Sum
Write-Output ("Identified {0} targets, {1:N2} GiB" -f $plan.Count, ($total / 1GB))
if (-not $Apply) { Write-Output 'Preview only. Use -Apply after inspecting artifacts/cleanup-plan.json.'; return }
# Fail before mutation when a process is using any target. Never kill an app to clean it.
$running = @(Get-CimInstance Win32_Process -Filter "Name='ArabicLens.exe'")
foreach ($process in $running) {
    foreach ($entry in $plan) {
        if ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($entry.Path + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "An app is running inside cleanup target: $($entry.Path)"
        }
    }
}
foreach ($entry in $plan) {
    # Paths have been resolved and checked above; keep all operations in PowerShell.
    if ($entry.Directory) { Remove-Item -LiteralPath $entry.Path -Recurse -Force }
    else { Remove-Item -LiteralPath $entry.Path -Force }
}
$plan | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $artifacts 'cleanup-applied.json')
Write-Output ("Removed {0:N2} GiB of generated/retired files." -f ($total / 1GB))
