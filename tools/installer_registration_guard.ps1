# Dot-source this file, then wrap every installer test in Invoke-InstallerTestGuard.
# LOCALAPPDATA isolation alone does not isolate the per-user uninstall registry.
function Invoke-InstallerTestGuard([scriptblock]$Test) {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{71A7C1D9-6186-4731-9A0B-FE541EB24C8E}_is1'
    $snapshot = @{}
    $existed = Test-Path $key
    if ($existed) {
        $entry = Get-Item $key
        foreach ($name in $entry.GetValueNames()) {
            $snapshot[$name] = @{Value=$entry.GetValue($name); Kind=$entry.GetValueKind($name).ToString()}
        }
    }
    try { & $Test }
    finally {
        if ($existed) {
            New-Item $key -Force | Out-Null
            $entry = Get-Item $key
            foreach ($name in $entry.GetValueNames()) {
                if (-not $snapshot.ContainsKey($name)) { Remove-ItemProperty -Path $key -Name $name }
            }
            foreach ($name in $snapshot.Keys) {
                New-ItemProperty -Path $key -Name $name -Value $snapshot[$name].Value -PropertyType $snapshot[$name].Kind -Force | Out-Null
            }
        } elseif (Test-Path $key) {
            $location = (Get-ItemProperty $key).InstallLocation
            $workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
            $testPrefix = [IO.Path]::GetFullPath((Join-Path $workspace 'artifacts')) + '\'
            if (-not $location -or -not [IO.Path]::GetFullPath($location).StartsWith($testPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Refusing to remove non-test installation registration.'
            }
            Remove-Item -LiteralPath $key -Recurse
        }
    }
}
