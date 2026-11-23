"""Download EVS's ICD-O-3.1 mapping files into a local, versioned cache.

The EVS download directory is a JavaScript page with no machine-readable listing, so "new
files" means a new version of the files below, detected with conditional requests
(``If-None-Match`` / ``If-Modified-Since``) and a SHA-256 comparison. Layout of the cache:

    <cache>/CURRENT              name of the active version (replaced atomically)
    <cache>/versions/<id>/       the four files + manifest.json (never modified once installed)
    <cache>/state.json           last check time, result and error
    <cache>/.lock                serialises syncs across processes (server and CLI)

A download is installed only after both mapping files parse and the entry count hasn't
collapsed; otherwise the previous version stays active. ``About.html`` and the ``.xls``
workbook (the same data as the two text files) are kept for reference and change detection.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import structlog

from .icdo_map import MORPHOLOGY_FILE, TOPOGRAPHY_FILE, load_icdo_map

log = structlog.get_logger(__name__)

DEFAULT_SOURCE_URL = "https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Mappings/ICD-O-3_Mappings/"
REFERENCE_FILES = ("About.html", "ICD-O-3.1-NCIt_Axis_Mappings.xls")
PARSED_FILES = (MORPHOLOGY_FILE, TOPOGRAPHY_FILE)
ALL_FILES = REFERENCE_FILES + PARSED_FILES
MAX_FILE_BYTES = 25 * 1024 * 1024
# A new version with fewer than half the previous entries is treated as a broken download.
MIN_ENTRY_RATIO = 0.5
KEEP_VERSIONS = 2

Status = Literal["updated", "unchanged", "failed", "busy"]


@dataclass
class SyncResult:
    status: Status
    version: str | None = None
    changed: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SyncError(Exception):
    pass


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "evs-cadsr-mcp" / "icdo"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class IcdoSyncer:
    def __init__(
        self, cache_dir: Path, base_url: str, *, user_agent: str, timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("the ICD-O source URL must use https")
        self.cache_dir = cache_dir
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.transport = transport

    @classmethod
    def from_settings(cls, settings, *, transport: httpx.AsyncBaseTransport | None = None) -> IcdoSyncer:
        cache = Path(settings.icdo_cache_dir).expanduser() if settings.icdo_cache_dir else default_cache_dir()
        return cls(cache, settings.icdo_source_url, user_agent=settings.evs_user_agent, transport=transport)

    # ------------------------------------------------------------------ reading
    @property
    def versions_dir(self) -> Path:
        return self.cache_dir / "versions"

    def current_version_dir(self) -> Path | None:
        try:
            name = (self.cache_dir / "CURRENT").read_text().strip()
        except OSError:
            return None
        path = self.versions_dir / name
        return path if name and "/" not in name and name not in (".", "..") and path.is_dir() else None

    def manifest(self, version_dir: Path | None) -> dict:
        if version_dir is None:
            return {}
        try:
            return json.loads((version_dir / "manifest.json").read_text())
        except (OSError, ValueError):
            return {}

    def state(self) -> dict:
        try:
            return json.loads((self.cache_dir / "state.json").read_text())
        except (OSError, ValueError):
            return {"lastCheck": None, "lastResult": None, "lastError": None}

    def seconds_until_due(self, interval_s: int) -> float:
        last = self.state().get("lastCheck")
        if not last:
            return 0.0
        elapsed = (_now() - datetime.fromisoformat(last)).total_seconds()
        return max(0.0, interval_s - elapsed)

    # ------------------------------------------------------------------ syncing
    async def sync(self, *, force: bool = False) -> SyncResult:
        """Check EVS for new versions of the files and install them; never raises for upstream faults."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock() as acquired:
            if not acquired:
                return SyncResult("busy", error="another sync is running")
            current = self.current_version_dir()
            previous = self.manifest(current).get("files", {}) if current else {}
            try:
                fetched = await self._fetch_changed(previous, force=force or current is None)
                changed = [n for n, f in fetched.items() if f["sha256"] != previous.get(n, {}).get("sha256")]
                if current is not None and not changed:
                    result = SyncResult("unchanged", version=current.name)
                else:
                    version = self._install(current, fetched, changed)
                    result = SyncResult("updated", version=version, changed=changed)
            except (SyncError, httpx.HTTPError, OSError, ValueError) as exc:
                log.warning("icdo_sync.failed", error=str(exc))
                result = SyncResult("failed", version=current.name if current else None, error=str(exc))
            self._write_state(result)
            return result

    def install_from_dir(self, source: Path) -> SyncResult:
        """Install files copied by hand (offline hosts): every file in ALL_FILES that exists in
        ``source`` is used; the two mapping files are required."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock() as acquired:
            if not acquired:
                return SyncResult("busy", error="another sync is running")
            current = self.current_version_dir()
            fetched = {}
            for name in ALL_FILES:
                path = source / name
                if path.is_file():
                    body = path.read_bytes()
                    fetched[name] = {"body": body, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                                     "etag": None, "lastModified": None}
            try:
                missing = [n for n in PARSED_FILES if n not in fetched]
                if missing:
                    raise SyncError(f"missing required files in {source}: {missing}")
                version = self._install(current, fetched, list(fetched), source_label=f"file:{source.name}")
                result = SyncResult("updated", version=version, changed=list(fetched))
            except (SyncError, OSError, ValueError) as exc:
                result = SyncResult("failed", version=current.name if current else None, error=str(exc))
            self._write_state(result)
            return result

    async def _fetch_changed(self, previous: dict, *, force: bool) -> dict[str, dict]:
        """GET each file conditionally. Returns new content for files that came back 200; a
        reference file that fails is skipped (the previous copy is kept), a mapping file that
        fails aborts the sync."""
        out: dict[str, dict] = {}
        async with httpx.AsyncClient(
            timeout=self.timeout_s, follow_redirects=False, transport=self.transport,
            headers={"User-Agent": self.user_agent},
        ) as client:
            for name in ALL_FILES:
                prev = previous.get(name, {})
                headers = {}
                if not force:
                    if prev.get("etag"):
                        headers["If-None-Match"] = prev["etag"]
                    if prev.get("lastModified"):
                        headers["If-Modified-Since"] = prev["lastModified"]
                try:
                    fetched = await self._get(client, name, headers)
                except (SyncError, httpx.HTTPError) as exc:
                    if name in PARSED_FILES:
                        raise
                    log.warning("icdo_sync.reference_file_skipped", file=name, error=str(exc))
                    continue
                if fetched is not None:
                    out[name] = fetched
        return out

    async def _get(self, client: httpx.AsyncClient, name: str, headers: dict[str, str]) -> dict | None:
        url = self.base_url + name
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 304:
                return None
            if resp.status_code != 200:
                raise SyncError(f"{name}: HTTP {resp.status_code}")
            declared = resp.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_FILE_BYTES:
                raise SyncError(f"{name}: {declared} bytes exceeds the {MAX_FILE_BYTES}-byte limit")
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_FILE_BYTES:
                    raise SyncError(f"{name}: exceeds the {MAX_FILE_BYTES}-byte limit")
            return {
                "body": bytes(body), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                "etag": resp.headers.get("etag"), "lastModified": resp.headers.get("last-modified"),
            }

    def _install(self, current: Path | None, fetched: dict[str, dict], changed: list[str], *, source_label: str | None = None) -> str:
        """Stage new and carried-over files, validate, then switch CURRENT atomically."""
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.versions_dir))
        try:
            files_meta: dict[str, dict] = {}
            previous = self.manifest(current).get("files", {}) if current else {}
            for name in ALL_FILES:
                if name in fetched:
                    (stage / name).write_bytes(fetched[name]["body"])
                    files_meta[name] = {k: fetched[name][k] for k in ("etag", "lastModified", "sha256", "bytes")}
                elif current is not None and (current / name).is_file():
                    shutil.copy2(current / name, stage / name)
                    files_meta[name] = previous.get(name, {})
            manifest = {"source": source_label or self.base_url, "syncedAt": _now().isoformat(), "changed": changed, "files": files_meta}
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            new_map = load_icdo_map(stage, source_url=self.base_url)  # raises ValueError on a bad file
            if current is not None:
                try:
                    old_count = len(load_icdo_map(current, source_url=self.base_url).entries)
                except (OSError, ValueError):
                    old_count = 0
                if old_count and len(new_map.entries) < old_count * MIN_ENTRY_RATIO:
                    raise SyncError(f"new files have {len(new_map.entries)} mappings, under half of the current {old_count}; not installed")
            version = self._version_name()
            stage.rename(self.versions_dir / version)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        self._atomic_write(self.cache_dir / "CURRENT", version + "\n")
        self._prune(keep={version})
        log.info("icdo_sync.installed", version=version, changed=changed, entries=len(new_map.entries))
        return version

    def _version_name(self) -> str:
        base = _now().strftime("%Y%m%dT%H%M%SZ")
        name, n = base, 1
        while (self.versions_dir / name).exists():
            n += 1
            name = f"{base}-{n}"
        return name

    def _prune(self, keep: set[str]) -> None:
        versions = sorted((p for p in self.versions_dir.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name)
        for old in versions[:-KEEP_VERSIONS]:
            if old.name not in keep:
                shutil.rmtree(old, ignore_errors=True)

    def _write_state(self, result: SyncResult) -> None:
        state = {"lastCheck": _now().isoformat(), "lastResult": result.status, "lastError": result.error}
        if result.status == "busy":
            return
        try:
            self._atomic_write(self.cache_dir / "state.json", json.dumps(state, indent=2) + "\n")
        except OSError as exc:
            log.warning("icdo_sync.state_write_failed", error=str(exc))

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    @contextlib.contextmanager
    def _lock(self) -> Iterator[bool]:
        """Exclusive, non-blocking lock across processes (POSIX); always granted elsewhere."""
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows
            yield True
            return
        fh = open(self.cache_dir / ".lock", "a+")  # noqa: SIM115 - held for the duration of the sync
        try:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()
