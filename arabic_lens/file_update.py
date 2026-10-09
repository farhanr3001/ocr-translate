"""Verified file updates, staged outside the app, with rollback on replacement failure."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _hash(stream)


def _hash(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def safe_path(root, name):
    if not isinstance(name, str):
        raise ValueError('Unsafe update path')
    path = PurePosixPath(name)
    if (not isinstance(name, str) or '\\' in name or ':' in name or path.is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))
            or any(re.search(r'[<>"|?*\x00-\x1f]', part) or part.endswith((' ', '.'))
                   or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)
                   for part in path.parts)):
        raise ValueError('Unsafe update path')
    root = Path(root).resolve()
    candidate = root.joinpath(*path.parts)
    if root not in candidate.resolve().parents:
        raise ValueError('Update path escaped application')
    for parent in (candidate, *candidate.parents):
        if parent == root:
            break
        if parent.exists() and (parent.is_symlink() or getattr(parent.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Update path uses a link')
    return candidate


def prepare_update(package, install, current_version, expected_version=None):
    """Validate every payload and old-file hash before any installed file is touched."""
    package, install = Path(package), Path(install).resolve()
    stage = package.parent / 'prepared'
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > 1024**3:
            raise ValueError('Update package is too large')
        if archive.getinfo('update.json').file_size > 4 * 1024**2:
            raise ValueError('Update manifest is too large')
        manifest = json.loads(archive.read('update.json'))
        from .updates import is_newer_version
        if manifest.get('schema') != 1 or not is_newer_version(manifest['version'], current_version):
            raise ValueError('Invalid update version')
        if expected_version is not None and manifest['version'] != expected_version:
            raise ValueError('Update manifest version differs from release')
        if manifest.get('base') not in (None, current_version):
            raise ValueError('Update does not match this app version')
        files, removed = manifest['files'], manifest.get('removed', {})
        if not isinstance(files, dict) or not isinstance(removed, dict) or 'ArabicLens.exe' not in files:
            raise ValueError('Incomplete update')
        names = [e.filename for e in entries]
        expected = {'update.json', *('files/' + name for name in files)}
        if len(set(n.lower() for n in names)) != len(names) or set(names) != expected:
            raise ValueError('Unexpected update files')
        if set(name.lower() for name in files) & set(name.lower() for name in removed):
            raise ValueError('Conflicting update files')
        stage.mkdir()
        unchanged = []
        for name, entry in files.items():
            target = safe_path(install, name)
            payload = safe_path(stage, name)
            old = entry.get('old')
            if manifest.get('base') is not None:
                if (old is None and target.exists()) or (old is not None and
                        (not target.is_file() or sha256(target) != old)):
                    raise ValueError('Installed files differ from this update baseline')
            payload.parent.mkdir(parents=True, exist_ok=True)
            with archive.open('files/' + name) as src, payload.open('xb') as dest:
                for chunk in iter(lambda: src.read(1024 * 1024), b''):
                    dest.write(chunk)
            if sha256(payload) != entry['sha256']:
                raise ValueError('Update file checksum failed')
            if manifest.get('base') is None and target.is_file() and sha256(target) == entry['sha256']:
                payload.unlink()
                unchanged.append(name)
        for name, old in removed.items():
            target = safe_path(install, name)
            if not target.is_file() or sha256(target) != old:
                raise ValueError('Removed file differs from update baseline')
        for name in unchanged:
            del manifest['files'][name]
    return stage, manifest


HELPER = r'''
$ErrorActionPreference = 'Stop'
function FileHash([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hash.Dispose() }
}
$job = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'job.json') -Raw | ConvertFrom-Json
$backup = Join-Path $PSScriptRoot 'backup'
$touched = [Collections.Generic.List[string]]::new()
$installed = $job.install
$closed = $false
try {
    $parent = Get-Process -Id $job.pid -ErrorAction SilentlyContinue
    if ($parent -and -not $parent.WaitForExit(30000)) { throw 'App did not close for update' }
    $closed = $true
    foreach ($property in $job.manifest.files.PSObject.Properties) {
        $source = Join-Path $job.stage $property.Name
        if ((FileHash $source) -ne $property.Value.sha256) { throw 'Staged checksum failed' }
    }
    $names = @($job.manifest.files.PSObject.Properties.Name) + @($job.manifest.removed.PSObject.Properties.Name)
    foreach ($name in $names) {
        $target = Join-Path $installed $name
        $saved = Join-Path $backup $name
        if (Test-Path -LiteralPath $target) {
            New-Item -ItemType Directory -Force -Path (Split-Path $saved) | Out-Null
            Copy-Item -LiteralPath $target -Destination $saved
        }
        $touched.Add($name)
        $source = Join-Path $job.stage $name
        if (Test-Path -LiteralPath $source) {
            New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
            Copy-Item -LiteralPath $source -Destination $target -Force
        } else { Remove-Item -LiteralPath $target -Force }
    }
    $reopened = Start-Process -FilePath (Join-Path $installed 'ArabicLens.exe') -ArgumentList @('--data-dir', ('"' + $job.data + '"')) -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    if ($reopened.HasExited) { throw 'Updated app could not start' }
    @{success=$true;version=$job.manifest.version;pid=$reopened.Id} | ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'result.json')
    try {
        foreach ($folder in @($job.stage, $backup)) {
            $resolved = [IO.Path]::GetFullPath($folder)
            if (-not $resolved.StartsWith($PSScriptRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid cleanup path' }
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
        Remove-Item -LiteralPath $job.package -Force
    } catch { } # Cleanup failure must never undo an already successful update.
} catch {
    $failure = $_.Exception.Message
    foreach ($name in $touched) {
        $target = Join-Path $installed $name
        $saved = Join-Path $backup $name
        try {
            if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination $target -Force }
            elseif (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
        } catch { $failure += '; rollback: ' + $_.Exception.Message }
    }
    @{success=$false;error=$failure} | ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'result.json')
    if ($closed) { Start-Process -FilePath (Join-Path $installed 'ArabicLens.exe') -ArgumentList @('--data-dir', ('"' + $job.data + '"')) -WindowStyle Hidden }
}
'''


def launch_file_update(package, executable, data_directory, current_version, expected_version=None):
    from .updates import UpdateError
    executable = Path(executable or '')
    if executable.name != 'ArabicLens.exe' or not executable.is_file() or data_directory is None:
        raise UpdateError('File updates require the packaged application.')
    try:
        stage, manifest = prepare_update(package, executable.parent, current_version, expected_version)
        root = Path(package).parent
        (root / 'job.json').write_text(json.dumps(dict(install=str(executable.parent.resolve()),
            stage=str(stage.resolve()), data=str(Path(data_directory).resolve()), pid=os.getpid(),
            package=str(Path(package).resolve()), manifest=manifest)), encoding='utf-8')
        script = root / 'apply.ps1'
        script.write_text(HELPER, encoding='utf-8-sig')
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        return subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
            'Bypass', '-WindowStyle', 'Hidden', '-File', str(script)],
            creationflags=0x08000000, close_fds=True)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise UpdateError('Could not prepare the update. The current app is unchanged.') from exc
