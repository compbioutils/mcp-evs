"""Release registry and release context (proposal Section 6.1, SOW-S11).

* polls ``GET /metadata/terminologies?terminology=<t>`` and records the releases EVS
  currently serves live, the latest monthly release, and the active release;
* ``resolve(terminology, requested)`` returns a :class:`ReleaseContext` or fails closed
  with ``release_not_available``;
* every EVS call uses ``ctx.terminology_version`` (e.g. ``ncit_26.09d``) in the path, so
  the answer is pinned even if EVS rolls over mid-request; an upstream ``version`` that
  differs from the pinned release raises ``release_mismatch``.

The NCIt retrieval index is not part of this first pass, so the active release is the
latest live monthly release (or ``ECM_RELEASE_PIN`` when set).
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from .budget import Budget
from .config import Settings
from .errors import EvsMcpError
from .http_client import ResilientClient

log = structlog.get_logger(__name__)

_RELEASE_RE = re.compile(r"^\d{2}\.\d{2}[a-z]?$")


@dataclass(frozen=True)
class ReleaseInfo:
    terminology: str
    version: str
    terminology_version: str
    latest: bool
    monthly: bool
    weekly: bool
    date: str | None
    name: str | None
    license_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class ReleaseContext:
    terminology: str
    release: str | None  # None only for terminologies without versioned addressing
    terminology_version: str  # path segment used upstream
    requested: str | None
    active: bool
    warnings: tuple[str, ...] = ()


class ReleaseRegistry:
    def __init__(self, settings: Settings, client: ResilientClient) -> None:
        self._settings = settings
        self._client = client
        self._lock = asyncio.Lock()
        self._by_terminology: dict[str, list[ReleaseInfo]] = {}
        self._fetched_at: dict[str, float] = {}
        self._all_terminologies: list[ReleaseInfo] | None = None
        self._all_fetched_at: float = 0.0

    # ------------------------------------------------------------------ fetch
    async def refresh(self, terminology: str, *, force: bool = False) -> list[ReleaseInfo]:
        terminology = terminology.lower()
        now = time.monotonic()
        fresh = now - self._fetched_at.get(terminology, 0.0) < self._settings.release_poll_seconds
        if not force and fresh and terminology in self._by_terminology:
            return self._by_terminology[terminology]
        async with self._lock:
            fresh = time.monotonic() - self._fetched_at.get(terminology, 0.0) < self._settings.release_poll_seconds
            if not force and fresh and terminology in self._by_terminology:
                return self._by_terminology[terminology]
            budget = Budget(max_requests=self._settings.http_max_retries + 1)
            res = await self._client.get_json(
                "/metadata/terminologies",
                params={"terminology": terminology},
                budget=budget,
                correlation_id="release-registry",
            )
            releases = [_parse(item) for item in (res.data or [])]
            if not releases:
                raise EvsMcpError("not_found", f"terminology '{terminology}' is not served by EVS")
            self._by_terminology[terminology] = releases
            self._fetched_at[terminology] = time.monotonic()
            log.info("release.refresh", terminology=terminology, live=[r.version for r in releases])
            return releases

    async def all_terminologies(self, *, force: bool = False) -> list[ReleaseInfo]:
        now = time.monotonic()
        if not force and self._all_terminologies and now - self._all_fetched_at < self._settings.release_poll_seconds:
            return self._all_terminologies
        budget = Budget(max_requests=self._settings.http_max_retries + 1)
        res = await self._client.get_json(
            "/metadata/terminologies",
            params={"latest": True},
            budget=budget,
            correlation_id="release-registry",
        )
        self._all_terminologies = [_parse(item) for item in (res.data or [])]
        self._all_fetched_at = time.monotonic()
        return self._all_terminologies

    # ---------------------------------------------------------------- resolve
    async def live_releases(self, terminology: str) -> list[ReleaseInfo]:
        return await self.refresh(terminology)

    async def active_release(self, terminology: str) -> ReleaseInfo:
        releases = await self.refresh(terminology)
        pin = self._settings.release_pin
        if pin and terminology.lower() == self._settings.default_terminology:
            for r in releases:
                if r.version == pin:
                    return r
            raise EvsMcpError(
                "release_not_available",
                f"pinned release '{pin}' is not served live by EVS",
                details={"live": [r.version for r in releases]},
                hint="The server is pinned (ECM_RELEASE_PIN) to a release EVS no longer serves. "
                     "Pass `release` with a value from details.live, or ask the operator to update the pin.",
            )
        monthly = [r for r in releases if r.monthly] or releases
        latest = [r for r in monthly if r.latest]
        return (latest or sorted(monthly, key=lambda r: r.version))[-1]

    async def resolve(self, terminology: str | None, requested: str | None) -> ReleaseContext:
        terminology = (terminology or self._settings.default_terminology).lower()
        releases = await self.refresh(terminology)
        if requested:
            requested = requested.strip()
            if requested.lower().startswith(terminology + "_"):
                requested = requested[len(terminology) + 1 :]
            for r in releases:
                if r.version == requested:
                    active = await self.active_release(terminology)
                    return ReleaseContext(
                        terminology=terminology,
                        release=r.version,
                        terminology_version=r.terminology_version,
                        requested=requested,
                        active=r.version == active.version,
                    )
            raise EvsMcpError(
                "release_not_available",
                f"release '{requested}' of {terminology} is not served live by EVS "
                "(only the most recent releases are available)",
                details={"terminology": terminology, "live": [r.version for r in releases]},
                hint="Pass one of details.live as `release`, or omit `release` for the active release. "
                     "Older releases can't be queried live.",
            )
        active = await self.active_release(terminology)
        return ReleaseContext(
            terminology=terminology,
            release=active.version,
            terminology_version=active.terminology_version,
            requested=None,
            active=True,
        )

    def check_upstream_version(self, ctx: ReleaseContext, upstream_version: str | None) -> None:
        """Fail closed when upstream reports a different release than the one pinned."""
        if ctx.release and upstream_version and upstream_version != ctx.release:
            raise EvsMcpError(
                "release_mismatch",
                "upstream returned content from a different release than requested",
                details={"requested": ctx.release, "upstream": upstream_version},
            )


def _parse(item: dict[str, Any]) -> ReleaseInfo:
    term = str(item.get("terminology", "")).lower()
    version = str(item.get("version", ""))
    tags = item.get("tags") or {}
    meta = item.get("metadata") or {}
    tv = item.get("terminologyVersion") or (f"{term}_{version}" if version else term)
    return ReleaseInfo(
        terminology=term,
        version=version,
        terminology_version=str(tv),
        latest=bool(item.get("latest", False)),
        monthly=str(tags.get("monthly", "")).lower() == "true",
        weekly=str(tags.get("weekly", "")).lower() == "true",
        date=item.get("date"),
        name=item.get("name"),
        license_text=meta.get("licenseText"),
        raw=item,
    )


def is_release_string(value: str) -> bool:
    return bool(_RELEASE_RE.match(value))
