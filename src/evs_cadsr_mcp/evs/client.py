"""Typed, cached, release-pinned wrappers over the EVS REST API endpoints.

Every method takes the :class:`Invocation` (budget, correlation id, provenance) and a
:class:`ReleaseContext`; the release's ``terminologyVersion`` is used in the URL path
so results are pinned. Raw JSON is returned; shaping lives in ``content.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ..core.cache import CacheClass, CacheEntry, cache_key
from ..core.config import Settings
from ..core.context import Invocation
from ..core.envelopes import License, Provenance
from ..core.http_client import ResilientClient
from ..core.release import ReleaseContext, ReleaseRegistry
from ..core.shared_cache import TieredCache

_DISPLAY_OBLIGATION = {"snomedct_us", "ncim", "icd10", "icd10cm"}


class EvsClient:
    def __init__(
        self,
        settings: Settings,
        http: ResilientClient,
        cache: TieredCache,
        registry: ReleaseRegistry,
    ) -> None:
        self.settings = settings
        self.http = http
        self.cache = cache
        self.registry = registry

    # ----------------------------------------------------------------- helpers
    def license_for(self, terminology: str) -> License:
        t = terminology.lower()
        if t in {x.lower() for x in self.settings.license_gated_terminologies}:
            return License(terminology=t, status="key_required")
        if t in _DISPLAY_OBLIGATION:
            return License(terminology=t, status="display_obligation")
        return License(terminology=t, status="open")

    def has_license_key(self) -> bool:
        return bool(self.settings.license_key)

    async def _get(
        self,
        inv: Invocation,
        ctx: ReleaseContext | None,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cache_class: CacheClass = "content",
        code: str | None = None,
        not_found_ok: bool = False,
        license_key: str | None = None,
        verify_version: Callable[[Any], str | None] | None = None,
    ) -> Any:
        release = ctx.release if ctx else None
        terminology = ctx.terminology if ctx else None
        key = cache_key(path, release, **(params or {}))
        entry = await self.cache.aget(cache_class, key)
        source_uri = self.http.public_url(path, params)
        if entry is not None:
            inv.add_provenance(
                Provenance(
                    source="evs_rest",
                    servedBy="cache",
                    terminology=terminology,
                    release=release,
                    code=code,
                    sourceUri=source_uri,
                    retrievedAt=entry.retrieved_at,
                    cachedAt=entry.cached_at,
                    license=self.license_for(terminology) if terminology else None,
                )
            )
            return entry.value
        neg = await self.cache.aget("negative", key, shared=False)
        if neg is not None and not_found_ok:
            inv.add_provenance(
                Provenance(source="evs_rest", servedBy="cache", terminology=terminology, release=release,
                           code=code, sourceUri=source_uri, retrievedAt=neg.retrieved_at, cachedAt=neg.cached_at)
            )
            return None

        res = await self.http.get_json(
            path,
            params=params,
            budget=inv.budget,
            correlation_id=inv.correlation_id,
            license_key=license_key,
            not_found_ok=not_found_ok,
        )
        if res.data is None:
            await self.cache.aput("negative", key, None, retrieved_at=res.retrieved_at, shared=False)
        else:
            if verify_version and ctx is not None:
                self.registry.check_upstream_version(ctx, verify_version(res.data))
            await self.cache.aput(cache_class, key, res.data, retrieved_at=res.retrieved_at)
        inv.add_provenance(
            Provenance(
                source="evs_rest",
                servedBy="live",
                terminology=terminology,
                release=release,
                code=code,
                sourceUri=source_uri,
                retrievedAt=res.retrieved_at,
                license=self.license_for(terminology) if terminology else None,
            )
        )
        return res.data

    # ---------------------------------------------------------------- metadata
    async def metadata(self, inv: Invocation, ctx: ReleaseContext, kind: str) -> Any:
        return await self._get(inv, ctx, f"/metadata/{ctx.terminology_version}/{kind}", cache_class="metadata")

    # ---------------------------------------------------------------- concepts
    async def concept(self, inv: Invocation, ctx: ReleaseContext, code: str, include: str) -> dict | None:
        return await self._get(
            inv, ctx, f"/concept/{ctx.terminology_version}/{code}",
            params={"include": include}, code=code, not_found_ok=True,
            verify_version=lambda d: d.get("version") if isinstance(d, dict) else None,
        )

    async def concepts(self, inv: Invocation, ctx: ReleaseContext, codes: Iterable[str], include: str) -> list[dict]:
        """Batch retrieval via ``?list=``, chunked; never per-code fan-out.

        Each concept is also cached on its own (per release and ``include``), so a batch asks EVS
        only for the codes not already cached, however the list is composed. Results come back in
        request order; codes EVS doesn't know are absent.
        """
        codes = list(dict.fromkeys(codes))
        path = f"/concept/{ctx.terminology_version}"
        found: dict[str, dict] = {}
        hits: list[tuple[str, CacheEntry]] = []
        for code in codes:
            entry = await self.cache.aget("content", _item_key(path, ctx.release, code, include))
            if entry is not None:
                found[code] = entry.value
                hits.append((code, entry))
        if hits:
            inv.add_provenance(
                Provenance(
                    source="evs_rest",
                    servedBy="cache",
                    terminology=ctx.terminology,
                    release=ctx.release,
                    sourceUri=self.http.public_url(path, {"list": ",".join(c for c, _ in hits), "include": include}),
                    retrievedAt=min(e.retrieved_at for _, e in hits),
                    cachedAt=min(e.cached_at for _, e in hits),
                    license=self.license_for(ctx.terminology),
                )
            )
        missing = [c for c in codes if c not in found]
        chunk = self.settings.batch_chunk_size
        for i in range(0, len(missing), chunk):
            part = missing[i : i + chunk]
            data = await self._get(inv, ctx, path, params={"list": ",".join(part), "include": include})
            for item in data or []:
                code = item.get("code") if isinstance(item, dict) else None
                if code in part:
                    found[code] = item
                    await self.cache.aput("content", _item_key(path, ctx.release, code, include), item)
        return [found[c] for c in codes if c in found]

    async def concept_part(self, inv: Invocation, ctx: ReleaseContext, code: str, part: str, params: dict | None = None) -> Any:
        """``/concept/{t}/{code}/{part}`` for children, parents, roles, descendants, paths, ..."""
        return await self._get(inv, ctx, f"/concept/{ctx.terminology_version}/{code}/{part}", params=params, code=code, not_found_ok=True)

    async def roots(self, inv: Invocation, ctx: ReleaseContext, include: str = "minimal") -> Any:
        return await self._get(inv, ctx, f"/concept/{ctx.terminology_version}/roots", params={"include": include})

    async def search(self, inv: Invocation, ctx: ReleaseContext, params: dict[str, Any]) -> dict:
        data = await self._get(inv, ctx, f"/concept/{ctx.terminology_version}/search", params=params, cache_class="search")
        return data or {"total": 0, "concepts": []}

    async def replacements(self, inv: Invocation, ctx: ReleaseContext, code: str) -> Any:
        return await self._get(inv, ctx, f"/history/{ctx.terminology_version}/{code}/replacements", code=code, not_found_ok=True)

    async def associations_by_type(self, inv: Invocation, ctx: ReleaseContext, label: str, *, from_record: int, page_size: int) -> Any:
        """Terminology-wide association entries for one association name (paged; excludes subset associations)."""
        return await self._get(
            inv, ctx, f"/concept/{ctx.terminology_version}/associations/{label}",
            params={"fromRecord": from_record, "pageSize": page_size}, not_found_ok=True,
        )

    # ----------------------------------------------------------------- subsets
    # EVS serves the subset tree and single-subset lookups only at the unpinned
    # /subset/{terminology} path (the ncit_<release> form returns [] or 404), so the
    # release is enforced by checking every returned item's version instead.
    async def subsets(self, inv: Invocation, ctx: ReleaseContext, include: str = "minimal") -> list[dict]:
        return await self._get(
            inv, ctx, f"/subset/{ctx.terminology}", params={"include": include},
            verify_version=_subset_version_mismatch(ctx.release),
        ) or []

    async def subset(self, inv: Invocation, ctx: ReleaseContext, code: str, include: str = "minimal") -> dict | None:
        return await self._get(
            inv, ctx, f"/subset/{ctx.terminology}/{code}", params={"include": include},
            code=code, not_found_ok=True, verify_version=_subset_version_mismatch(ctx.release),
        )

    async def subset_members(self, inv: Invocation, ctx: ReleaseContext, code: str, *, include: str, from_record: int, page_size: int) -> list[dict]:
        data = await self._get(
            inv, ctx, f"/subset/{ctx.terminology_version}/{code}/members",
            params={"include": include, "fromRecord": from_record, "pageSize": page_size}, code=code, not_found_ok=True,
        )
        return data or []

    # ----------------------------------------------------------------- mapsets
    async def mapsets(self, inv: Invocation, include: str = "minimal") -> list[dict]:
        return await self._get(inv, None, "/mapset", params={"include": include}, cache_class="metadata") or []

    async def mapset(self, inv: Invocation, code: str, include: str = "properties") -> dict | None:
        return await self._get(inv, None, f"/mapset/{code}", params={"include": include}, cache_class="metadata", code=code, not_found_ok=True)

    async def mapset_maps(self, inv: Invocation, code: str, *, term: str | None, from_record: int, page_size: int, license_key: str | None) -> dict:
        data = await self._get(
            inv, None, f"/mapset/{code}/maps",
            params={"term": term, "fromRecord": from_record, "pageSize": page_size}, code=code, not_found_ok=True,
            license_key=license_key,
        )
        return data or {"total": 0, "maps": []}


def _subset_version_mismatch(release: str | None) -> Callable[[Any], str | None]:
    """Return a checker that finds the first subset (at any depth) from another release."""

    def check(data: Any) -> str | None:
        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            version = item.get("version")
            if release and version and version != release:
                return str(version)
            stack.extend(item.get("children") or [])
        return None

    return check


def _item_key(path: str, release: str | None, code: str, include: str) -> str:
    return cache_key(f"{path}#item", release, code=code, include=include)
