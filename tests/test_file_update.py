import asyncio
import json
from pathlib import Path
import zipfile
import hashlib
import httpx
import pytest
from arabic_lens.file_update import prepare_update, safe_path
from arabic_lens.updates import UpdateService
from arabic_lens.updates import UpdateInfo
from tools.build_file_update import build


def fixture(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir(); new.mkdir()
    for root in (old, new):
        (root / 'model.bin').write_bytes(b'unchanged model' * 100)
    (old / 'ArabicLens.exe').write_bytes(b'MZold')
    (new / 'ArabicLens.exe').write_bytes(b'MZnew')
    (old / 'removed.txt').write_text('old')
    (new / 'added.txt').write_text('new')
    package = tmp_path / 'update.zip'
    build(new, package, '0.1.3', old, '0.1.2')
    return old, new, package


def test_only_changed_files_staged_and_installed_files_untouched(tmp_path):
    old, new, package = fixture(tmp_path)
    stage, manifest = prepare_update(package, old, '0.1.2', '0.1.3')
    assert not (stage / 'model.bin').exists()
    assert (old / 'ArabicLens.exe').read_bytes() == b'MZold'
    assert (stage / 'ArabicLens.exe').read_bytes() == b'MZnew'
    assert manifest['removed'] == {'removed.txt': hashlib.sha256(b'old').hexdigest()}


@pytest.mark.parametrize('name', ['../evil', '/evil', 'C:/evil', 'dir\\evil', 'NUL.txt', 'x:stream', 'a./b'])
def test_path_escape_and_windows_special_paths_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        safe_path(tmp_path, name)


def test_modified_baseline_rejected_before_replacing_app(tmp_path):
    old, new, package = fixture(tmp_path)
    (old / 'ArabicLens.exe').write_bytes(b'MZmodified')
    with pytest.raises(ValueError, match='baseline'):
        prepare_update(package, old, '0.1.2')
    assert (old / 'ArabicLens.exe').read_bytes() == b'MZmodified'


def test_full_fallback_does_not_replace_unchanged_model(tmp_path):
    old, new, package = fixture(tmp_path)
    build(new, package, '0.1.3')
    stage, manifest = prepare_update(package, old, '0.1.2')
    assert 'model.bin' not in manifest['files']
    assert not (stage / 'model.bin').exists()


def test_wrong_release_version_and_corrupt_payload_rejected(tmp_path):
    old, new, package = fixture(tmp_path)
    with pytest.raises(ValueError, match='version'):
        prepare_update(package, old, '0.1.2', '0.1.4')
    with zipfile.ZipFile(package) as src:
        entries = {n: src.read(n) for n in src.namelist()}
    entries['files/ArabicLens.exe'] = b'MZcorrupt'
    with zipfile.ZipFile(package, 'w') as out:
        for name, payload in entries.items(): out.writestr(name, payload)
    with pytest.raises(ValueError, match='checksum'):
        prepare_update(package, old, '0.1.2')


def test_update_feed_prefers_delta_then_full_package(tmp_path):
    async def run():
        assets = []
        for name in ('ArabicLens-Setup.exe', 'ArabicLens-Update-full.zip', 'ArabicLens-Update-0.1.2.zip'):
            assets.append(dict(name=name, size=100, digest='sha256:' + 'a'*64,
                browser_download_url=f'https://github.com/farhanr3001/ocr-translate/releases/download/v0.1.3/{name}'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,
                json=dict(tag_name='v0.1.3', assets=assets)))) as client:
            delta = await UpdateService('farhanr3001/ocr-translate', '0.1.2').check(client=client)
            full = await UpdateService('farhanr3001/ocr-translate', '0.1.1').check(client=client)
        assert delta.asset_name == 'ArabicLens-Update-0.1.2.zip'
        assert full.asset_name == 'ArabicLens-Update-full.zip'
    asyncio.run(run())


def test_verified_zip_launches_file_helper_instead_of_setup(tmp_path, monkeypatch):
    old, new, package = fixture(tmp_path)
    payload = package.read_bytes()
    name = 'ArabicLens-Update-0.1.2.zip'
    info = UpdateInfo('0.1.3', '', '',
        f'https://github.com/farhanr3001/ocr-translate/releases/download/v0.1.3/{name}',
        hashlib.sha256(payload).hexdigest(), len(payload), name)
    service = UpdateService('farhanr3001/ocr-translate', '0.1.2')
    async def download():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payload))) as client:
            return await service.download(info, directory=tmp_path / 'downloads', client=client)
    downloaded = asyncio.run(download())
    calls = []
    monkeypatch.setattr('arabic_lens.file_update.launch_file_update', lambda *args: calls.append(args) or object())
    service.launch_installer(downloaded, executable=old / 'ArabicLens.exe', data_directory=tmp_path / 'data')
    assert calls[0] == (downloaded, old / 'ArabicLens.exe', tmp_path / 'data', '0.1.2', '0.1.3')
