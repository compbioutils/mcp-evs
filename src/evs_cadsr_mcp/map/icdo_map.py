"""Local ICD-O-3.1 <-> NCIt map used by ``map_map_icdo_to_ncit``.

The map comes from EVS's published ICD-O-3.1 mapping files (NCI Metathesaurus synonymy
mappings of each ICD-O code and term to an NCIt concept), which :mod:`.icdo_sync` downloads
into a local cache once a day. Only the two tab-delimited files are parsed; their layout is
described by ``About.html`` in the same EVS directory:

    ICD-O Code | Level | Term Type | Term Type Desc | ICD-O string | NCIm CUI | NCIt Code | NCIt PT string

Rows are grouped by (ICD-O code, NCIt concept); the displayed ICD-O term prefers the PT. Each
mapped concept's status is checked live at the requested NCIt release by the caller.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from ..core.errors import EvsMcpError
from .resolve import _norm

if TYPE_CHECKING:
    from ..core.config import Settings
    from .icdo_sync import IcdoSyncer, SyncResult

log = structlog.get_logger(__name__)

ICDO_VERSION = "3.1"
MORPHOLOGY_FILE = "ICD-O-3.1-NCIt_Morphology_Mapping.txt"
TOPOGRAPHY_FILE = "ICD-O-3.1-NCIt_Topography_Mapping.txt"
AXIS_FILES = {"morphology": MORPHOLOGY_FILE, "topography": TOPOGRAPHY_FILE}
# Leading words of each expected column; the two files differ only in letter case.
EXPECTED_HEADER = ("icd-o code", "level", "term type", "term type desc", "icd-o string", "ncim cui", "ncit code", "ncit pt string")

MORPH_RE = re.compile(r"^\d{4}/\d$")
TOPO_RE = re.compile(r"^C\d{2}(\.\d)?$", re.IGNORECASE)
TOPO_RANGE_RE = re.compile(r"^C\d{2}-C\d{2}$", re.IGNORECASE)
# PT, SY, RT, HT, then the obsolete forms (OP, IS, ORT) the files flag.
_TERM_TYPE_RANK = {"PT": 0, "SY": 1, "RT": 2, "HT": 3, "OP": 4, "IS": 5, "ORT": 6}


def icdo_axis(code: str) -> str:
    """Axis of a caller-supplied code; ``unknown`` for group codes such as '800'."""
    if MORPH_RE.match(code):
        return "morphology"
    if TOPO_RE.match(code) or TOPO_RANGE_RE.match(code):
        return "topography"
    return "unknown"


@dataclass(frozen=True)
class IcdoMapEntry:
    icdo_code: str
    icdo_term: str
    term_type: str
    icdo_terms: tuple[str, ...]  # every ICD-O string seen for the pair (searchable)
    ncit_code: str
    ncit_name: str
    ncim_cui: str | None
    axis: str

    def rank(self) -> tuple[int, str, str]:
        return (_TERM_TYPE_RANK.get(self.term_type, 9), self.icdo_code, self.ncit_name.lower())


@dataclass(frozen=True)
class IcdoMap:
    version: str  # cache version directory the map was loaded from
    source_url: str
    published: datetime | None  # newest Last-Modified of the parsed files at EVS
    synced_at: datetime  # when this version was downloaded
    entries: tuple[IcdoMapEntry, ...]

    @property
    def published_date(self) -> str | None:
        return self.published.date().isoformat() if self.published else None

    def file_url(self, axis: str | None) -> str:
        return self.source_url + AXIS_FILES[axis] if axis in AXIS_FILES else self.source_url

    def lookup(self, code: str) -> list[IcdoMapEntry]:
        key = code.strip().upper()
        return sorted((e for e in self.entries if e.icdo_code.upper() == key), key=IcdoMapEntry.rank)

    def search(self, term: str, *, axis: str | None, limit: int) -> tuple[list[tuple[IcdoMapEntry, str]], int]:
        """Exact name matches if any, otherwise names containing the term; returns (page, total)."""
        q = _norm(term)
        if not q:
            return [], 0
        pool = [e for e in self.entries if axis is None or e.axis == axis]

        def matches(e: IcdoMapEntry, exact: bool) -> str | None:
            def hit(name: str) -> bool:
                n = _norm(name)
                return n == q if exact else q in n

            if any(hit(t) for t in e.icdo_terms):
                return "ICD-O term"
            if hit(e.ncit_name):
                return "NCIt name"
            return None

        for exact in (True, False):
            found = [(e, via) for e in pool if (via := matches(e, exact))]
            if found:
                found.sort(key=lambda p: (len(p[0].icdo_term),) + p[0].rank())
                return found[:limit], len(found)
        return [], 0


def parse_mapping_file(path: Path, axis: str) -> list[IcdoMapEntry]:
    """Parse one tab-delimited mapping file; raises ValueError when it isn't the documented layout."""
    with path.open(newline="", encoding="utf-8-sig", errors="strict") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        raise ValueError(f"{path.name} is empty")
    header = [c.strip().lower() for c in rows[0]]
    if len(header) != len(EXPECTED_HEADER) or not all(h.startswith(e) for h, e in zip(header, EXPECTED_HEADER, strict=True)):
        raise ValueError(f"{path.name} does not have the documented columns (got {rows[0]})")
    grouped: dict[tuple[str, str], list[list[str]]] = {}
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        if len(row) != len(EXPECTED_HEADER):
            raise ValueError(f"{path.name} line {n} has {len(row)} columns, expected {len(EXPECTED_HEADER)}")
        code, concept = row[0].strip(), row[6].strip()
        if code and concept:
            if not re.fullmatch(r"C[1-9][0-9]*", concept):
                raise ValueError(f"{path.name} line {n} has an invalid NCIt code {concept!r}")
            grouped.setdefault((code, concept), []).append([c.strip() for c in row])
    entries = []
    for (code, concept), group in grouped.items():
        best = min(group, key=lambda r: _TERM_TYPE_RANK.get(r[2], 9))
        entries.append(IcdoMapEntry(
            icdo_code=code,
            icdo_term=best[4],
            term_type=best[2],
            icdo_terms=tuple(dict.fromkeys(r[4] for r in group if r[4])),
            ncit_code=concept,
            ncit_name=best[7] or concept,
            ncim_cui=best[5] or None,
            axis=axis,
        ))
    if not entries:
        raise ValueError(f"{path.name} has no rows with an NCIt code")
    return entries


def load_icdo_map(version_dir: Path, *, source_url: str) -> IcdoMap:
    """Load an installed (or staged) version directory."""
    manifest = _read_json(version_dir / "manifest.json")
    entries = parse_mapping_file(version_dir / MORPHOLOGY_FILE, "morphology") + parse_mapping_file(version_dir / TOPOGRAPHY_FILE, "topography")
    files = manifest.get("files", {})
    published = [d for name in AXIS_FILES.values() if (d := _http_date(files.get(name, {}).get("lastModified")))]
    synced = manifest.get("syncedAt")
    return IcdoMap(
        version=version_dir.name,
        source_url=manifest.get("source") or source_url,
        published=max(published) if published else None,
        synced_at=datetime.fromisoformat(synced) if synced else datetime.fromtimestamp(version_dir.stat().st_mtime, tz=UTC),
        entries=tuple(entries),
    )


def _http_date(value: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


class IcdoMapStore:
    """Serves the active cached version, reloading when a sync (in-process or CLI) switches it.

    With automatic sync on (``ECM_ICDO_SYNC_INTERVAL_S`` > 0), an empty cache is filled on first
    use and a background task re-checks EVS on that interval.
    """

    def __init__(self, syncer: IcdoSyncer, *, interval_s: int) -> None:
        self.syncer = syncer
        self.interval_s = interval_s
        self._map: IcdoMap | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> IcdoMapStore:
        from .icdo_sync import IcdoSyncer

        return cls(IcdoSyncer.from_settings(settings), interval_s=settings.icdo_sync_interval_s)

    @property
    def auto_sync(self) -> bool:
        return self.interval_s > 0

    def _load_current(self) -> IcdoMap | None:
        version_dir = self.syncer.current_version_dir()
        if version_dir is None:
            return None
        if self._map is not None and self._map.version == version_dir.name:
            return self._map
        try:
            loaded = load_icdo_map(version_dir, source_url=self.syncer.base_url)
        except (OSError, ValueError, csv.Error) as exc:
            log.error("icdo_map.load_failed", version=version_dir.name, error=str(exc))
            return self._map
        log.info("icdo_map.loaded", version=loaded.version, published=loaded.published_date, entries=len(loaded.entries))
        self._map = loaded
        return loaded

    async def sync(self, *, force: bool = False) -> SyncResult:
        async with self._lock:
            result = await self.syncer.sync(force=force)
        self._load_current()
        return result

    async def get(self) -> IcdoMap:
        current = self._load_current()
        if current is None and self.auto_sync:
            await self.sync()
            current = self._load_current()
        if current is None:
            raise EvsMcpError(
                "capability_unavailable",
                "the EVS ICD-O-3.1 mapping files have not been downloaded to this server yet",
                details={"source": self.syncer.base_url, "configure": "evs-cadsr-mcp icdo sync (needs HTTPS access to evs.nci.nih.gov)"},
                hint="Retry shortly if the server was just started. To find the NCIt concept for one ICD-O-3 "
                     "morphology code meanwhile, call evs_find_concepts with "
                     "{kind: 'property', name: 'ICD-O-3_Code', value: '<code>'}.",
            )
        return current

    def status(self) -> dict:
        current = self._load_current()
        return {
            **self.syncer.state(),
            "version": current.version if current else None,
            "published": current.published_date if current else None,
            "entries": len(current.entries) if current else 0,
            "autoSyncIntervalSeconds": self.interval_s,
        }

    # ------------------------------------------------------------ background
    def start(self) -> None:
        if self.auto_sync and self._task is None:
            self._task = asyncio.create_task(self._run(), name="icdo-sync")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        delay = self.syncer.seconds_until_due(self.interval_s) if self._load_current() else 0.0
        while True:
            await asyncio.sleep(delay)
            try:
                result = await self.sync()
                log.info("icdo_sync.done", status=result.status, version=result.version, changed=result.changed, error=result.error)
            except Exception:  # noqa: BLE001 - the loop must survive any single failure
                log.exception("icdo_sync.crashed")
            delay = float(self.interval_s)
