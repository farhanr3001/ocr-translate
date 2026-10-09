"""Public release updates are opt-in, bounded, and verified before launch."""

import asyncio
import hashlib

import httpx
import pytest

from arabic_lens.updates import UpdateError, UpdateInfo, UpdateService, is_newer_version


REPOSITORY = "farhanr3001/ocr-translate"
RELEASE_URL = "https://github.com/farhanr3001/ocr-translate/releases/download/v0.2.0/ArabicLens-Setup.exe"
INSTALLER = b"MZ" + b"Arabic Lens installer fixture" * 4
DIGEST = hashlib.sha256(INSTALLER).hexdigest()


def release(*, version="v0.2.0", digest=f"sha256:{DIGEST}", size=len(INSTALLER), assets=None):
    return {
        "tag_name": version, "draft": False, "prerelease": False,
        "body": "A small update", "assets": assets if assets is not None else [
            {"name": "ArabicLens-Setup.exe", "size": size, "state": "uploaded",
             "digest": digest, "browser_download_url": RELEASE_URL},
        ],
    }


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def info():
    return UpdateInfo("0.2.0", "", "https://github.com/farhanr3001/ocr-translate/releases/tag/v0.2.0",
                      RELEASE_URL, DIGEST, len(INSTALLER))


def test_repository_and_numeric_versions():
    service = UpdateService("https://github.com/farhanr3001/ocr-translate", "0.1.0")
    assert service.api_url == "https://api.github.com/repos/farhanr3001/ocr-translate/releases/latest"
    assert is_newer_version("v0.2.0", "0.1.9")
    assert is_newer_version("v1.0.0", "0.9.9")
    assert not is_newer_version("0.1.0", "v0.1.0")
    assert not is_newer_version("0.1.9", "0.2.0")
    with pytest.raises(ValueError):
        UpdateService("https://example.com/owner/repo", "0.1.0")
    with pytest.raises(UpdateError):
        is_newer_version("v0.2.0-preview", "0.1.0")


@pytest.mark.parametrize("tag,expected", [("v0.2.0", True), ("v0.1.0", False), ("v0.0.9", False)])
def test_check_only_offers_a_newer_stable_release(tag, expected):
    async def run():
        async with client_for(lambda request: httpx.Response(200, json=release(version=tag))) as client:
            return await UpdateService(REPOSITORY, "0.1.0").check(client=client)
    found = asyncio.run(run())
    assert (found is not None) is expected
    if found:
        assert found.version == "0.2.0"
        assert found.sha256 == DIGEST


def test_check_handles_no_release_and_rejects_unsafe_metadata():
    async def run(payload, status=200):
        async with client_for(lambda request: httpx.Response(status, json=payload)) as client:
            return await UpdateService(REPOSITORY, "0.1.0").check(client=client)

    assert asyncio.run(run({}, 404)) is None
    payload = release()
    payload["prerelease"] = True
    assert asyncio.run(run(payload)) is None
    for bad in (
        release(digest="sha256:not-a-hash"),
        release(digest=None),
        release(size=0),
        release(size=2 * 1024 * 1024 * 1024),
        release(assets=[{"name": "ArabicLens-Setup.exe", "size": len(INSTALLER),
                         "digest": f"sha256:{DIGEST}",
                         "browser_download_url": "https://evil.example/ArabicLens-Setup.exe"}]),
    ):
        with pytest.raises(UpdateError):
            asyncio.run(run(bad))


def test_release_metadata_size_is_bounded():
    async def run():
        async with client_for(lambda request: httpx.Response(200, content=b" " * (1024 * 1024 + 1))) as client:
            return await UpdateService(REPOSITORY, "0.1.0").check(client=client)

    with pytest.raises(UpdateError, match="too large"):
        asyncio.run(run())


def test_companion_hash_is_accepted_only_for_the_named_installer():
    assets = release(digest=None)["assets"]
    assets.append({"name": "ArabicLens-Setup.exe.sha256", "size": 100,
                   "browser_download_url": RELEASE_URL + ".sha256"})

    async def run(checksum):
        def handler(request):
            if request.url.host == "api.github.com":
                return httpx.Response(200, json=release(assets=assets))
            return httpx.Response(200, text=checksum)
        async with client_for(handler) as client:
            return await UpdateService(REPOSITORY, "0.1.0").check(client=client)

    assert asyncio.run(run(f"{DIGEST} *ArabicLens-Setup.exe\n")).sha256 == DIGEST
    with pytest.raises(UpdateError):
        asyncio.run(run(f"{DIGEST} *other.exe\n"))
    with pytest.raises(UpdateError, match="too large"):
        asyncio.run(run(f"{DIGEST}\n" + " " * 5000))


def test_download_streams_verifies_and_launches_only_checked_file(tmp_path, monkeypatch):
    calls = []
    service = UpdateService(REPOSITORY, "0.1.0")

    async def run():
        def handler(request):
            assert request.url.scheme == "https"
            if request.url.host == "github.com":
                return httpx.Response(302, headers={"Location": "https://release-assets.githubusercontent.com/blob"})
            return httpx.Response(200, content=INSTALLER)
        async with client_for(handler) as client:
            return await service.download(info(), lambda done, total: calls.append((done, total)),
                                          directory=tmp_path, client=client)

    installer = asyncio.run(run())
    assert installer.read_bytes() == INSTALLER
    assert calls[-1] == (len(INSTALLER), len(INSTALLER))
    launches = []
    monkeypatch.setattr("arabic_lens.updates.subprocess.Popen",
                        lambda argv, **kwargs: launches.append((argv, kwargs)) or object())
    service.launch_installer(installer)
    assert launches[0][0] == [str(installer), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"]
    with pytest.raises(UpdateError):
        UpdateService(REPOSITORY, "0.1.0").launch_installer(installer)
    installer.write_bytes(INSTALLER + b"changed")
    with pytest.raises(UpdateError):
        service.launch_installer(installer)
    assert len(launches) == 1


@pytest.mark.parametrize("reply", [
    lambda: httpx.Response(200, content=b"MZbad"),
    lambda: httpx.Response(200, content=INSTALLER + b"extra"),
    lambda: httpx.Response(302, headers={"Location": "http://example.com/insecure.exe"}),
])
def test_bad_or_insecure_download_cleans_partial(tmp_path, reply):
    service = UpdateService(REPOSITORY, "0.1.0")

    async def run():
        async with client_for(lambda request: reply()) as client:
            return await service.download(info(), directory=tmp_path, client=client)

    with pytest.raises(UpdateError):
        asyncio.run(run())
    assert list(tmp_path.rglob("*.part")) == []
    assert list(tmp_path.rglob("*.exe")) == []


def test_wrong_version_or_non_executable_download_never_stages(tmp_path):
    service = UpdateService(REPOSITORY, "0.1.0")
    wrong = UpdateInfo("0.3.0", "", info().release_url, RELEASE_URL, DIGEST, len(INSTALLER))
    bogus = b"ZZ" + INSTALLER[2:]
    non_executable = UpdateInfo("0.2.0", "", info().release_url, RELEASE_URL,
                                hashlib.sha256(bogus).hexdigest(), len(bogus))

    async def run(candidate):
        async with client_for(lambda request: httpx.Response(200, content=bogus)) as client:
            return await service.download(candidate, directory=tmp_path, client=client)

    with pytest.raises(UpdateError):
        asyncio.run(run(wrong))
    with pytest.raises(UpdateError):
        asyncio.run(run(non_executable))
    assert list(tmp_path.rglob("*.exe")) == []


def test_cancelled_download_cleans_partial(tmp_path):
    service = UpdateService(REPOSITORY, "0.1.0")

    def cancel(done, total):
        raise asyncio.CancelledError()

    async def run():
        async with client_for(lambda request: httpx.Response(200, content=INSTALLER)) as client:
            return await service.download(info(), cancel, directory=tmp_path, client=client)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert list(tmp_path.rglob("*.part")) == []
    assert list(tmp_path.rglob("*.exe")) == []
