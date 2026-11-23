"""Capability interfaces between the mapping module and the EVS / caDSR modules (8.1).

``map`` never imports the EVS or caDSR *tools*; it talks to narrow protocols. The
in-process adapters below wrap the local services and share the caller's
:class:`Invocation`, so every upstream call made on behalf of a cross-domain tool lands in
one composite provenance list and draws from one budget. A remote adapter (an MCP client to
an EVS-only deployment) can implement the same protocol for a split deployment.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..cadsr import normalise as cadsr_normalise
from ..cadsr.models import (
    CrdcMapEntry,
    DataElement,
    DataElementSummary,
    FindDataElementsResult,
    MatchEntity,
    MatchResult,
    VersionSummary,
)
from ..cadsr.service import CadsrService
from ..core.context import Invocation
from ..core.errors import EvsMcpError
from ..core.release import ReleaseContext
from ..evs.models import (
    Concept,
    ConceptMaps,
    ConceptRef,
    HistoryEvent,
    MapsetEntries,
    Match,
    SearchHit,
)
from ..evs.service import EvsService

SUBSET_PAGE = 1000
SUBSET_CAP = 5000


class EvsCapability(Protocol):
    async def release_context(self, release: str | None) -> ReleaseContext: ...
    async def get_concepts(self, inv: Invocation, ctx: ReleaseContext, codes: list[str], include: list[str]) -> dict[str, Concept]: ...
    async def get_concept_history(self, inv: Invocation, ctx: ReleaseContext, code: str) -> list[HistoryEvent]: ...
    async def get_descendants(self, inv: Invocation, ctx: ReleaseContext, code: str, *, max_level: int | None, limit: int) -> list[ConceptRef]: ...
    async def get_subset_members(self, inv: Invocation, ctx: ReleaseContext, code: str) -> list[Concept]: ...
    async def search_concepts(self, inv: Invocation, ctx: ReleaseContext, term: str, *, search_type: str, filters: dict[str, Any], limit: int) -> list[SearchHit]: ...
    async def lookup_concept(self, inv: Invocation, ctx: ReleaseContext, identifier: str) -> list[Match]: ...
    async def get_concept_maps(self, inv: Invocation, ctx: ReleaseContext, code: str, target: str | None) -> ConceptMaps: ...
    async def get_mapset_entries(self, inv: Invocation, mapset: str, *, term: str | None, limit: int) -> MapsetEntries: ...


class CadsrCapability(Protocol):
    async def get_data_element(self, inv: Invocation, public_id: str, version: str | None) -> DataElement: ...
    async def get_versions(self, inv: Invocation, public_id: str) -> list[VersionSummary]: ...
    async def find_by_concept(self, inv: Invocation, code: str, *, item_type: str | None) -> list[DataElementSummary]: ...
    async def find_data_elements(self, inv: Invocation, query: str, *, by: list[str]) -> FindDataElementsResult: ...
    async def crdc_code_map(self, inv: Invocation) -> list[CrdcMapEntry]: ...
    async def match_data_elements(self, inv: Invocation, entities: list[MatchEntity], *, backend: str, match_limit: int, contexts: list[str] | None) -> list[MatchResult]: ...
    def match_backend_available(self) -> str | None: ...


FULL_INCLUDE = ["valueDomain", "permissibleValues", "dataElementConcept", "alternateNames", "classificationSchemes", "referenceDocuments"]


class InProcessEvs:
    def __init__(self, service: EvsService) -> None:
        self.s = service

    async def release_context(self, release: str | None) -> ReleaseContext:
        return await self.s.release_context("ncit", release)

    async def get_concepts(self, inv, ctx, codes, include):
        if not codes:
            return {}
        env = await self.s.get_concepts(inv, ctx, list(codes), include)
        return {c.code: c for c in env.result.concepts}

    async def get_concept_history(self, inv, ctx, code):
        try:
            return (await self.s.get_concept_history(inv, ctx, code)).result
        except EvsMcpError as exc:
            if exc.code == "not_found":
                return []
            raise

    async def get_descendants(self, inv, ctx, code, *, max_level, limit):
        out: list[ConceptRef] = []
        cursor = None
        while len(out) < limit:
            env = await self.s.get_descendants(inv, ctx, code, max_level=max_level, limit=min(1000, limit - len(out)), cursor=cursor)
            out.extend(env.result)
            cursor = env.page.nextCursor if env.page else None
            if not cursor or inv.budget.remaining <= 0:
                break
        return out[:limit]

    async def get_subset_members(self, inv, ctx, code):
        out: list[Concept] = []
        cursor = None
        while len(out) < SUBSET_CAP:
            env = await self.s.get_subset_members(inv, ctx, code, include=["summary"], limit=SUBSET_PAGE, cursor=cursor)
            out.extend(env.result)
            cursor = env.page.nextCursor if env.page else None
            if not cursor or inv.budget.remaining <= 0:
                break
        return out

    async def search_concepts(self, inv, ctx, term, *, search_type, filters, limit):
        env = await self.s.search_concepts(inv, ctx, term, search_type=search_type, include=["summary"], limit=min(limit, 100), cursor=None, filters=filters)
        return env.result

    async def lookup_concept(self, inv, ctx, identifier):
        env = await self.s.lookup_concept(inv, ctx, identifier, match="normalized", synonym_source=None, term_type=None, include=["summary"], limit=10)
        return env.result

    async def get_concept_maps(self, inv, ctx, code, target):
        return (await self.s.get_concept_maps(inv, ctx, code, target)).result

    async def get_mapset_entries(self, inv, mapset, *, term, limit):
        return (await self.s.get_mapset_entries(inv, mapset, term=term, limit=limit, cursor=None)).result


class InProcessCadsr:
    def __init__(self, service: CadsrService) -> None:
        self.s = service

    async def get_data_element(self, inv, public_id, version):
        return (await self.s.get_data_element(inv, public_id, version, FULL_INCLUDE)).result

    async def get_versions(self, inv, public_id):
        try:
            return (await self.s.get_data_element_versions(inv, public_id)).result
        except EvsMcpError as exc:
            if exc.code == "not_found":
                return []
            raise

    async def find_by_concept(self, inv, code, *, item_type):
        try:
            raws = await self.s.client.data_elements_by_concept(inv, code, item_type=item_type, workflow_status=None)
        except EvsMcpError as exc:
            if exc.code == "not_found":
                return []
            raise
        return [cadsr_normalise.summary(r, matched_role=item_type) for r in raws]

    async def find_data_elements(self, inv, query, *, by):
        return await self.s.search.find(inv, query, by=by, exact=False, context=None, classification_scheme_public_id=None, classification_scheme_version=None)

    async def crdc_code_map(self, inv):
        return (await self.s.get_crdc_code_map(inv, None, limit=1000, cursor=None)).result

    async def match_data_elements(self, inv, entities, *, backend, match_limit, contexts):
        return (await self.s.match_data_elements(inv, entities, match_limit=match_limit, contexts=contexts, backend=backend)).result

    def match_backend_available(self) -> str | None:
        if self.s.client.credential is not None:
            return "cde_match"
        if self.s.client.ai_http is not None:
            return "ai_engine"
        return None
