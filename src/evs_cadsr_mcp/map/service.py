"""Transport-independent mapping handlers (one per ``map_*`` tool)."""

from __future__ import annotations

from typing import Any

from ..core.config import Settings
from ..core.context import Invocation
from ..core.envelopes import Envelope, Truncation
from ..core.errors import invalid_request
from . import analysis, resolve
from .align import align_value_sets
from .capability import CadsrCapability, EvsCapability
from .icdo_map import IcdoMapStore
from .models import (
    CdeConceptMap,
    CdeSuggestion,
    Crosswalk,
    DataElementsForConcept,
    IcdoMapping,
    LintReport,
    ModelFragment,
    ModelPropertyMapping,
    PvExplanation,
    ReleaseImpact,
    StoredValues,
    ValueSetAlignment,
    ValueSetSide,
)

EXCEPTION_SUGGEST = "cde_suggestion_ranking: caDSR offers no ranking; scores are computed by this server"
EXCEPTION_ALIGN = "value_set_alignment: verdicts are computed by this server from caDSR PVs and NCIt names/synonyms"
EXCEPTION_LINT = "model_lint: findings are computed by this server; neither upstream defines them"


class MapService:
    def __init__(self, settings: Settings, evs: EvsCapability, cadsr: CadsrCapability) -> None:
        self.settings = settings
        self.evs = evs
        self.cadsr = cadsr
        self.icdo_map = IcdoMapStore.from_settings(settings)

    async def ctx(self, release: str | None):
        return await self.evs.release_context(release)

    async def resolve_cde_concepts(self, inv: Invocation, public_id: str, version: str | None, release: str | None, *, include_pvs: bool) -> Envelope[CdeConceptMap]:
        ctx = await self.ctx(release)
        cmap, _ = await resolve.resolve_cde_concepts(self.evs, self.cadsr, inv, ctx, public_id, version, include_pvs=include_pvs)
        return inv.envelope(cmap)

    async def find_data_elements_for_concept(self, inv: Invocation, code: str, release: str | None, *, expand: bool, max_level: int, max_concepts: int, item_type: str | None) -> Envelope[DataElementsForConcept]:
        ctx = await self.ctx(release)
        result, truncated = await resolve.data_elements_for_concept(self.evs, self.cadsr, inv, ctx, code, expand=expand, max_level=max_level, max_concepts=max_concepts, item_type=item_type)
        trunc = Truncation(occurred=True, bound=truncated, limit=max_concepts if truncated == "maxConcepts" else inv.budget.max_requests,
                           reached=len(result.groups), omitted=None, exact=False) if truncated else None
        return inv.envelope(result, truncation=trunc)

    async def explain_permissible_value(self, inv: Invocation, public_id: str, version: str | None, value: str, release: str | None) -> Envelope[PvExplanation]:
        ctx = await self.ctx(release)
        return inv.envelope(await resolve.explain_permissible_value(self.evs, self.cadsr, inv, ctx, public_id, version, value))

    async def align_value_sets(self, inv: Invocation, left: ValueSetSide, right: ValueSetSide, release: str | None) -> Envelope[ValueSetAlignment]:
        ctx = await self.ctx(release)
        inv.exception = EXCEPTION_ALIGN
        return inv.envelope(await align_value_sets(self.evs, self.cadsr, inv, ctx, left, right))

    async def resolve_model_property(self, inv: Invocation, fragment: ModelFragment, release: str | None) -> Envelope[list[ModelPropertyMapping]]:
        ctx = await self.ctx(release)
        mappings, truncated = await analysis.resolve_fragment(self.evs, self.cadsr, inv, ctx, fragment)
        if any(m.alignment for m in mappings):
            inv.exception = EXCEPTION_ALIGN
        trunc = Truncation(occurred=True, bound="maxProperties", limit=50, reached=len(mappings), omitted=None, exact=False) if truncated else None
        return inv.envelope(mappings, truncation=trunc)

    async def suggest_cdes_for_term(self, inv: Invocation, term: str, *, description: str | None, sample_values: list[str] | None, contexts: list[str] | None, limit: int, backend: str | None, release: str | None) -> Envelope[list[CdeSuggestion]]:
        ctx = await self.ctx(release)
        inv.exception = EXCEPTION_SUGGEST
        suggestions, used = await analysis.suggest_cdes_for_term(self.evs, self.cadsr, inv, ctx, term, description=description, sample_values=sample_values, contexts=contexts, limit=limit, backend=backend)
        inv.warn(f"ranking backend: {used}; candidates are suggestions, never a fabricated CDE")
        return inv.envelope(suggestions)

    async def validate_model_fragment(self, inv: Invocation, fragment: ModelFragment, release: str | None, *, mode: str) -> Envelope[Any]:
        ctx = await self.ctx(release)
        inv.exception = EXCEPTION_LINT
        mappings, truncated = await analysis.resolve_fragment(self.evs, self.cadsr, inv, ctx, fragment)
        report: LintReport = analysis.lint_report(ctx.release or "", mappings)
        trunc = Truncation(occurred=True, bound="maxProperties", limit=50, reached=len(mappings), omitted=None, exact=False) if truncated else None
        if mode == "findings":
            return inv.envelope(report.findings, truncation=trunc)
        return inv.envelope(report, truncation=trunc)

    async def assess_release_impact(self, inv: Invocation, from_release: str, to_release: str | None, scope: dict, *, lookup_cdes: bool) -> Envelope[ReleaseImpact]:
        from_ctx = await self.ctx(from_release)
        to_ctx = await self.ctx(to_release)
        if from_ctx.release == to_ctx.release:
            raise invalid_request("fromRelease and toRelease are the same release", release=from_ctx.release)
        return inv.envelope(await analysis.assess_release_impact(self.evs, self.cadsr, inv, from_ctx, to_ctx, scope, lookup_cdes=lookup_cdes))

    async def crosswalk_properties(self, inv: Invocation, left: ModelFragment, right: ModelFragment, release: str | None) -> Envelope[Crosswalk]:
        ctx = await self.ctx(release)
        lm, _ = await analysis.resolve_fragment(self.evs, self.cadsr, inv, ctx, left, max_properties=1)
        rm, _ = await analysis.resolve_fragment(self.evs, self.cadsr, inv, ctx, right, max_properties=1)
        if not lm or not rm:
            raise invalid_request("each side must resolve to one property (set fragment.property when the fragment has several)")
        return inv.envelope(analysis.crosswalk(lm[0], rm[0]))

    async def map_icdo_to_ncit(self, inv: Invocation, *, icdo_code: str | None, term: str | None, axis: str, include_group: bool, release: str | None) -> Envelope[list[IcdoMapping]]:
        icdo_map = await self.icdo_map.get()
        ctx = await self.ctx(release)
        out = await analysis.map_icdo_to_ncit(self.evs, inv, ctx, icdo_map, icdo_code=icdo_code, term=term, axis=axis)
        if include_group:
            inv.warn("ICD-O diagnosis-group roll-up needs the ICD-O group table, which is not configured in this deployment; group is null")
        return inv.envelope(out)

    async def resolve_stored_value(self, inv: Invocation, code: str, commons: str, release: str | None) -> Envelope[StoredValues]:
        ctx = await self.ctx(release)
        return inv.envelope(await analysis.resolve_stored_value(self.evs, self.cadsr, inv, ctx, code, commons))
