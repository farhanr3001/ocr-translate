"""Optional, consent-based updates from a public GitHub Release.

Run the async methods on the application's background event loop. The UI decides
when to check and must ask before calling ``download``. GitHub's release asset
digest (or a companion .sha256 asset) is checked before an installer is staged.
An installer is launched only after a successful download by this service.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urljoin, urlparse

import httpx


INSTALLER_NAME = "ArabicLens-Setup.exe"
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_VERSION = re.compile(r"v?((?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){1,3})\Z", re.I)
_SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")


class UpdateError(Exception):
    """A short, user-displayable update failure; the original error is chained."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    release_url: str
    installer_url: str
    sha256: str
    size_bytes: int
    asset_name: str = INSTALLER_NAME


def _version_parts(version: str) -> tuple[int, ...]:
    matched = _VERSION.fullmatch(version)
    if not matched:
        raise UpdateError("This release has an invalid version number.")
    parts = tuple(int(part) for part in matched.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


def is_newer_version(latest: str, installed: str) -> bool:
    """Compare the stable numeric release tags supported by the installer."""
    return _version_parts(latest) > _version_parts(installed)


def _repository_slug(repository: str) -> str:
    if repository.startswith("https://"):
        parsed = urlparse(repository)
        if parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.port:
            raise ValueError("The update repository must be on github.com.")
        if parsed.query or parsed.fragment:
            raise ValueError("The update repository URL must not have a query or fragment.")
        repository = parsed.path.strip("/")
        if repository.endswith(".git"):
            repository = repository[:-4]
    if not _REPOSITORY.fullmatch(repository):
        raise ValueError("The update repository must be an owner/repository pair.")
    return repository


def _require_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise UpdateError("The update source did not use a secure connection.")


def _asset_url(url: str, repository: str, tag: str, filename: str) -> str:
    _require_https(url)
    parsed = urlparse(url)
    expected = f"/{repository}/releases/download/{quote(tag, safe='')}/{filename}"
    if parsed.hostname != "github.com" or parsed.port or parsed.path != expected:
        raise UpdateError("The release contains an unexpected download link.")
    if parsed.query or parsed.fragment:
        raise UpdateError("The release contains an unexpected download link.")
    return url


def _digest(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.lower().startswith("sha256:"):
        raise UpdateError("The release has an invalid installer checksum.")
    checksum = value[7:]
    if not _SHA256.fullmatch(checksum):
        raise UpdateError("The release has an invalid installer checksum.")
    return checksum.lower()


def _checksum_file(text: str) -> str:
    # Accept a bare hash or the usual sha256sum format, but bind a filename if
    # one is supplied. Never interpret a checksum for another release asset.
    match = re.fullmatch(r"\s*([a-fA-F0-9]{64})(?:[ \t]+\*?ArabicLens-Setup\.exe)?\s*", text)
    if not match:
        raise UpdateError("The release has an invalid installer checksum.")
    return match.group(1).lower()


class UpdateService:
    def __init__(self, repository: str, current_version: str, timeout: float = 10.0):
        self.repository = _repository_slug(repository)
        self.current_version = current_version
        _version_parts(current_version)
        if timeout <= 0:
            raise ValueError("The update timeout must be positive.")
        self.timeout = timeout
        self._verified_paths: dict[Path, str] = {}
        self._verified_versions: dict[Path, str] = {}

    @property
    def api_url(self) -> str:
        return f"https://api.github.com/repos/{self.repository}/releases/latest"

    async def check(self, *, client: httpx.AsyncClient | None = None) -> UpdateInfo | None:
        """Return a newer stable release, or None when no update is published."""
        if client is None:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=True) as owned:
                return await self.check(client=owned)
        try:
            async with client.stream("GET", self.api_url, headers={
                "Accept": "application/vnd.github+json", "User-Agent": "ArabicLens-Updater",
                "X-GitHub-Api-Version": "2022-11-28",
            }, follow_redirects=False) as response:
                if response.status_code == 404:
                    return None
                if response.url.host != "api.github.com" or response.url.scheme != "https":
                    raise UpdateError("The update source could not be verified.")
                response.raise_for_status()
                payload = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    payload.extend(chunk)
                    if len(payload) > 1024 * 1024:
                        raise UpdateError("The release information is too large.")
            data = json.loads(payload)
        except httpx.HTTPError as exc:
            raise UpdateError("Could not check for updates. Try again later.") from exc
        except (ValueError, UnicodeError) as exc:
            raise UpdateError("The release information could not be read.") from exc

        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return None
        tag = data.get("tag_name")
        if not isinstance(tag, str):
            raise UpdateError("The release has no valid version number.")
        if not is_newer_version(tag, self.current_version):
            return None
        if not isinstance(data.get("assets"), list):
            raise UpdateError("The release has no Windows installer.")
        assets = [item for item in data["assets"] if isinstance(item, dict)]
        delta_name = f"ArabicLens-Update-{self.current_version}.zip"
        asset_name = next((name for name in (delta_name, 'ArabicLens-Update-full.zip', INSTALLER_NAME)
                           if any(item.get('name') == name for item in assets)), INSTALLER_NAME)
        installer = next((item for item in assets if item.get("name") == asset_name), None)
        if installer is None or installer.get("state", "uploaded") != "uploaded":
            raise UpdateError("The release has no Windows installer.")
        size = installer.get("size")
        if type(size) is not int or not 2 <= size <= MAX_INSTALLER_BYTES:
            raise UpdateError("The installer size is invalid.")
        url = installer.get("browser_download_url")
        if not isinstance(url, str):
            raise UpdateError("The release has no secure installer link.")
        _asset_url(url, self.repository, tag, asset_name)
        checksum = _digest(installer.get("digest"))
        if checksum is None:
            companion_name = asset_name + ".sha256"
            companion = next((item for item in assets if item.get("name") == companion_name), None)
            if companion is None or not isinstance(companion.get("browser_download_url"), str):
                raise UpdateError("The release has no installer checksum.")
            checksum_url = _asset_url(companion["browser_download_url"], self.repository, tag, companion_name)
            try:
                checksum_bytes = await self._read_small_https(client, checksum_url, MAX_CHECKSUM_BYTES)
                checksum_text = checksum_bytes.decode('ascii')
                if asset_name != INSTALLER_NAME:
                    checksum_text = checksum_text.replace(asset_name, INSTALLER_NAME)
                checksum = _checksum_file(checksum_text)
            except (UnicodeError, httpx.HTTPError) as exc:
                raise UpdateError("The installer checksum could not be read.") from exc
        notes = data.get("body") if isinstance(data.get("body"), str) else ""
        release_url = f"https://github.com/{self.repository}/releases/tag/{quote(tag, safe='')}"
        return UpdateInfo(tag.lstrip("vV"), notes[:2000], release_url, url, checksum, size, asset_name)

    @staticmethod
    async def _read_small_https(client: httpx.AsyncClient, url: str, limit: int) -> bytes:
        result = bytearray()
        async with UpdateService._stream_https(client, url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(1024):
                result.extend(chunk)
                if len(result) > limit:
                    raise UpdateError("The installer checksum is too large.")
        return bytes(result)

    @staticmethod
    @asynccontextmanager
    async def _stream_https(client: httpx.AsyncClient, url: str):
        current_url = url
        for _ in range(6):
            _require_https(current_url)
            async with client.stream("GET", current_url, follow_redirects=False,
                                     headers={"User-Agent": "ArabicLens-Updater"}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise UpdateError("The download location is missing.")
                    current_url = urljoin(str(response.url), location)
                    _require_https(current_url)
                    continue
                yield response
                return
        raise UpdateError("The download redirected too many times.")

    async def download(
        self,
        info: UpdateInfo,
        on_progress: Callable[[int, int], None] | None = None,
        *,
        directory: Path | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> Path:
        """Stream and verify the installer; call only after the user accepts."""
        if client is None:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, read=30.0), trust_env=True) as owned:
                return await self.download(info, on_progress, directory=directory, client=owned)
        # API tags may omit 'v'; accept either exact release path after checking
        # the source repository and the expected asset name.
        parsed = urlparse(info.installer_url)
        path_parts = parsed.path.split("/")
        if len(path_parts) != 7 or path_parts[4] != "download":
            raise UpdateError("The installer link is invalid.")
        tag = path_parts[5]
        if info.asset_name not in (INSTALLER_NAME, 'ArabicLens-Update-full.zip',
                                   f'ArabicLens-Update-{self.current_version}.zip'):
            raise UpdateError('The update package name is invalid.')
        _asset_url(info.installer_url, self.repository, tag, info.asset_name)
        if _version_parts(tag) != _version_parts(info.version):
            raise UpdateError("The installer version does not match the release.")
        if not _SHA256.fullmatch(info.sha256) or not 2 <= info.size_bytes <= MAX_INSTALLER_BYTES:
            raise UpdateError("The installer details are invalid.")

        base = Path(directory) if directory is not None else Path(tempfile.gettempdir()) / "ArabicLens-updates"
        try:
            base.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix="ArabicLens-", dir=base))
        except OSError as exc:
            raise UpdateError("Could not save the update. Check free disk space.") from exc
        partial = staging / (info.asset_name + ".part")
        final = staging / info.asset_name
        digest = hashlib.sha256()
        received = 0
        try:
            async with self._stream_https(client, info.installer_url) as response:
                response.raise_for_status()
                with partial.open("xb") as out:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > info.size_bytes or received > MAX_INSTALLER_BYTES:
                            raise UpdateError("The installer download was larger than expected.")
                        out.write(chunk)
                        digest.update(chunk)
                        if on_progress is not None:
                            on_progress(received, info.size_bytes)
            if received != info.size_bytes:
                raise UpdateError("The installer download was incomplete.")
            if not secrets.compare_digest(digest.hexdigest(), info.sha256.lower()):
                raise UpdateError("The installer download failed its checksum check.")
            with partial.open("rb") as installed_file:
                signature = b'MZ' if info.asset_name == INSTALLER_NAME else b'PK'
                if installed_file.read(2) != signature:
                    raise UpdateError("The downloaded file is not a Windows installer.")
            partial.replace(final)
            self._verified_paths[final.resolve()] = info.sha256.lower()
            self._verified_versions[final.resolve()] = info.version
            return final
        except (httpx.HTTPError, OSError) as exc:
            raise UpdateError("Could not download the update. Try again later.") from exc
        finally:
            if not final.exists():
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
                try:
                    staging.rmdir()
                except OSError:
                    pass

    def launch_installer(self, path: Path, *, executable=None, data_directory=None) -> subprocess.Popen:
        """Start a verified Inno installer; the caller should then quit the app."""
        candidate = Path(path).resolve()
        expected = self._verified_paths.get(candidate)
        if expected is None or not candidate.is_file():
            raise UpdateError("The installer was not verified. Download it again.")
        try:
            digest = hashlib.sha256()
            with candidate.open("rb") as installer:
                for chunk in iter(lambda: installer.read(1024 * 1024), b""):
                    digest.update(chunk)
            if not secrets.compare_digest(digest.hexdigest(), expected):
                raise UpdateError("The installer changed after download. Download it again.")
            if candidate.suffix == '.zip':
                from .file_update import launch_file_update
                return launch_file_update(candidate, executable, data_directory, self.current_version,
                                          self._verified_versions[candidate])
            if candidate.name != INSTALLER_NAME:
                raise UpdateError('The update package name is invalid.')
            return subprocess.Popen([
                str(candidate), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            ], close_fds=True)
        except OSError as exc:
            raise UpdateError("Could not start the installer. Try again later.") from exc
