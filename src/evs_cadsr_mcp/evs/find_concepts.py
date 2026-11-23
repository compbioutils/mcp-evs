"""Concept-set planner for ``evs_find_concepts`` (proposal Section 6.5, SOW-T5).

EVS has no single endpoint for "concepts matching these criteria": ``search`` filters by
property value, subset and text, but **not** by role or association; role/association
targets are reached through ``/{target}/inverseRoles`` and ``/inverseAssociations``; a whole
association type is paged through ``/concept/{t}/associations/{label}``. The planner picks
the cheapest native route for each criterion, combines them with AND/OR, and names the
path it took in ``plan``. Combinations that only SPARQL can answer (for example two
different property values under AND) return ``capability_unavailable`` with
``plan.path = sparql_required``; SPARQL use is a fallback that needs NCI approval
(proposal Appendix B, ``evs-role-search``) and is not implemented in this pass.
"""

from __future__ import annotations

from typing import Any

from ..core.config import Settings
from ..core.context import Invocation
from ..core.cursor import decode_cursor, encode_cursor
from ..core.envelopes import Page
from ..core.errors import EvsMcpError, invalid_request
from ..core.release import ReleaseContext
from .client import EvsClient
from .models import ConceptRef, Criterion, FindConceptsPlan, FindConceptsResult, PlanStep

SEARCH_KINDS = {"property", "term", "subset"}
ENUM_KINDS = {"role", "association", "associationType", "subset"}
ENUMERATE_CAP = 5000  # codes per route when a full set must be materialised
UPSTREAM_PAGE = 1000


class ConceptSetPlanner:
    def __init__(self, settings: Settings, client: EvsClient) -> None:
        self.settings = settings
        self.client = client

    # ------------------------------------------------------------- validate
    @staticmethod
    def _validate(criteria: list[Criterion]) -> None:
        if not criteria:
            raise invalid_request("at least one criterion is required")
        for c in criteria:
            if c.kind == "property" and not c.name:
                raise invalid_request("property criterion needs name (and usually value)")
            if c.kind in ("role", "association") and not (c.name and c.targetCode):
                raise invalid_request(f"{c.kind} criterion needs name and targetCode")
            if c.kind == "associationType" and not c.name:
                raise invalid_request("associationType criterion needs name")
            if c.kind == "subset" and not c.value:
                raise invalid_request("subset criterion needs value (the subset code)")
            if c.kind == "term" and not c.value:
                raise invalid_request("term criterion needs value")
            if c.kind in ("conceptStatus", "semanticType") and not c.value:
                raise invalid_request(f"{c.kind} criterion needs value")

    # ---------------------------------------------------------------- plan
    async def find(
        self,
        inv: Invocation,
        ctx: ReleaseContext,
        criteria: list[Criterion],
        combinator: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[FindConceptsResult, Page]:
        self._validate(criteria)
        limit = max(1, min(limit, self.settings.max_page_size))
        offset = decode_cursor(cursor, release=ctx.release)[0] if cursor else 0

        search_crits = [c for c in criteria if c.kind in SEARCH_KINDS or c.kind in ("conceptStatus", "semanticType")]
        enum_crits = [c for c in criteria if c.kind in ("role", "association", "associationType")]

        # --- single criterion: native route with upstream paging where available
        if len(criteria) == 1:
            c = criteria[0]
            if c.kind in ("role", "association", "associationType"):
                refs, step = await self._enumerate(inv, ctx, c)
                return self._page_in_memory(refs, [step], "single_route", combinator, limit, offset, ctx)
            if c.kind == "subset":
                refs, step = await self._subset_members_page(inv, ctx, c, offset, limit)
                more = len(refs) >= limit
                return self._result(refs, [step], "single_route", combinator, limit, offset, None, more, ctx)
            if c.kind in ("conceptStatus", "semanticType"):
                raise invalid_request(f"{c.kind} alone does not define a concept set; combine it with a property, term or subset criterion")
            refs, total, step = await self._search_page([c], ctx, inv, offset, limit)
            return self._result(refs, [step], "single_route", combinator, limit, offset, total, None, ctx)

        # --- OR: enumerate every route and union
        if combinator == "OR":
            steps: list[PlanStep] = []
            union: dict[str, ConceptRef] = {}
            for c in criteria:
                if c.kind in ("conceptStatus", "semanticType"):
                    raise invalid_request(f"{c.kind} cannot be OR-ed; it only narrows other criteria")
                refs, step = await self._enumerate(inv, ctx, c)
                steps.append(step)
                for r in refs:
                    union.setdefault(r.code, r)
            return self._page_in_memory(list(union.values()), steps, "enumerate_and_union", combinator, limit, offset, ctx)

        # --- AND (semanticType is sent as the Semantic_Type property, so it counts as one)
        n_prop = sum(1 for c in search_crits if c.kind in ("property", "semanticType"))
        n_term = sum(1 for c in search_crits if c.kind == "term")
        n_subset = sum(1 for c in search_crits if c.kind == "subset")
        if n_prop > 1 or n_term > 1 or n_subset > 1:
            plan = FindConceptsPlan(
                combinator="AND", path="sparql_required", steps=[],
                note="EVS search accepts one property value, one term and one subset per query; this combination needs SPARQL, "
                     "which is an NCI-approved fallback not enabled in this deployment.",
            )
            raise EvsMcpError(
                "capability_unavailable",
                "criteria combination requires the SPARQL fallback, which is not enabled",
                details={"plan": plan.model_dump()},
                hint="Keep at most one property (or semanticType), one term and one subset per call: run "
                     "evs_find_concepts once per property and intersect the returned codes yourself.",
            )
        steps = []
        if search_crits and not enum_crits:
            refs, total, step = await self._search_page(search_crits, ctx, inv, offset, limit)
            return self._result(refs, [step], "search_combined", combinator, limit, offset, total, None, ctx)

        sets: list[dict[str, ConceptRef]] = []
        if search_crits:
            refs, step = await self._search_enumerate(search_crits, ctx, inv)
            steps.append(step)
            sets.append({r.code: r for r in refs})
        for c in enum_crits:
            refs, step = await self._enumerate(inv, ctx, c)
            steps.append(step)
            sets.append({r.code: r for r in refs})
        common = set.intersection(*(set(s) for s in sets)) if sets else set()
        merged = [sets[0][code] for code in sets[0] if code in common]
        return self._page_in_memory(merged, steps, "enumerate_and_intersect", combinator, limit, offset, ctx)

    # -------------------------------------------------------------- routes
    def _search_params(self, crits: list[Criterion]) -> dict[str, Any]:
        params: dict[str, Any] = {"include": "minimal"}
        for c in crits:
            if c.kind == "property":
                params["property"] = c.name
                if c.value is not None:
                    params["value"] = c.value
            elif c.kind == "term":
                params["term"] = c.value
                params["type"] = c.searchType or "contains"
            elif c.kind == "subset":
                params["subset"] = c.value
            elif c.kind == "conceptStatus":
                params["conceptStatus"] = c.value
            elif c.kind == "semanticType":
                # EVS ignores its semanticType parameter; the Semantic_Type property filter works.
                params["property"] = "Semantic_Type"
                params["value"] = c.value
        # `term` is optional on EVS search when property/value, subset or status filters are present
        # [verify live: tests/live/test_live_smoke.py covers property=ICD-O-3_Code&value=8140/3].
        return params

    async def _search_page(self, crits: list[Criterion], ctx: ReleaseContext, inv: Invocation, offset: int, limit: int):
        params = {**self._search_params(crits), "fromRecord": offset, "pageSize": limit}
        data = await self.client.search(inv, ctx, params)
        refs = _refs(data.get("concepts", []), ctx.release)
        step = PlanStep(criterion=crits[0], route="search", endpoint=self.client.http.public_url(f"/concept/{ctx.terminology_version}/search", params), count=data.get("total"), complete=True)
        return refs, data.get("total"), step

    async def _search_enumerate(self, crits: list[Criterion], ctx: ReleaseContext, inv: Invocation):
        base = self._search_params(crits)
        out: list[ConceptRef] = []
        complete = True
        offset = 0
        total = None
        while True:
            if inv.budget.remaining <= 0 or len(out) >= ENUMERATE_CAP:
                complete = False
                break
            data = await self.client.search(inv, ctx, {**base, "fromRecord": offset, "pageSize": UPSTREAM_PAGE})
            page = _refs(data.get("concepts", []), ctx.release)
            out.extend(page)
            total = data.get("total")
            offset += len(page)
            if not page or (total is not None and offset >= total):
                break
        step = PlanStep(criterion=crits[0], route="search", endpoint=self.client.http.public_url(f"/concept/{ctx.terminology_version}/search", base), count=total, complete=complete)
        return out, step

    async def _subset_members_page(self, inv: Invocation, ctx: ReleaseContext, c: Criterion, offset: int, limit: int):
        raws = await self.client.subset_members(inv, ctx, c.value, include="minimal", from_record=offset, page_size=limit)
        refs = _refs(raws, ctx.release)
        step = PlanStep(criterion=c, route="subsetMembers", endpoint=self.client.http.public_url(f"/subset/{ctx.terminology_version}/{c.value}/members"), count=None, complete=True)
        return refs, step

    async def _enumerate(self, inv: Invocation, ctx: ReleaseContext, c: Criterion):
        """Materialise the full concept set for one criterion (capped)."""
        if c.kind == "role" or c.kind == "association":
            part = "inverseRoles" if c.kind == "role" else "inverseAssociations"
            raws = await self.client.concept_part(inv, ctx, c.targetCode, part)
            if raws is None:
                raise EvsMcpError("not_found", f"target concept {c.targetCode} not found", details={"code": c.targetCode})
            refs = [ConceptRef(code=str(r.get("relatedCode")), name=r.get("relatedName"), release=ctx.release) for r in raws if r.get("type") == c.name]
            endpoint = self.client.http.public_url(f"/concept/{ctx.terminology_version}/{c.targetCode}/{part}")
            return refs, PlanStep(criterion=c, route=part, endpoint=endpoint, count=len(refs), complete=True)
        if c.kind == "associationType":
            out: dict[str, ConceptRef] = {}
            offset = 0
            complete = True
            while True:
                if inv.budget.remaining <= 0 or len(out) >= ENUMERATE_CAP:
                    complete = False
                    break
                data = await self.client.associations_by_type(inv, ctx, c.name, from_record=offset, page_size=UPSTREAM_PAGE)
                entries = _assoc_entries(data)
                for e in entries:
                    code = str(e.get("code") or e.get("relatedCode"))
                    out.setdefault(code, ConceptRef(code=code, name=e.get("name") or e.get("relatedName"), release=ctx.release))
                offset += len(entries)
                total = data.get("total") if isinstance(data, dict) else None
                if not entries or len(entries) < UPSTREAM_PAGE or (total is not None and offset >= total):
                    break
            endpoint = self.client.http.public_url(f"/concept/{ctx.terminology_version}/associations/{c.name}")
            return list(out.values()), PlanStep(criterion=c, route="associationsByType", endpoint=endpoint, count=len(out), complete=complete)
        if c.kind == "subset":
            out = {}
            offset = 0
            complete = True
            while True:
                if inv.budget.remaining <= 0 or len(out) >= ENUMERATE_CAP:
                    complete = False
                    break
                raws = await self.client.subset_members(inv, ctx, c.value, include="minimal", from_record=offset, page_size=UPSTREAM_PAGE)
                for r in _refs(raws, ctx.release):
                    out.setdefault(r.code, r)
                offset += len(raws)
                if len(raws) < UPSTREAM_PAGE:
                    break
            endpoint = self.client.http.public_url(f"/subset/{ctx.terminology_version}/{c.value}/members")
            return list(out.values()), PlanStep(criterion=c, route="subsetMembers", endpoint=endpoint, count=len(out), complete=complete)
        # property / term: enumerate through search
        refs, step = await self._search_enumerate([c], ctx, inv)
        return refs, step

    # ------------------------------------------------------------- results
    def _page_in_memory(self, refs: list[ConceptRef], steps, path, combinator, limit, offset, ctx):
        refs = sorted(refs, key=lambda r: _code_sort_key(r.code))
        window = refs[offset : offset + limit]
        return self._result(window, steps, path, combinator, limit, offset, len(refs), None, ctx)

    def _result(self, refs, steps, path, combinator, limit, offset, total, more, ctx) -> tuple[FindConceptsResult, Page]:
        has_more = more if more is not None else (total is not None and offset + len(refs) < total)
        page = Page(limit=limit, offset=offset, total=total, returned=len(refs),
                    nextCursor=encode_cursor(release=ctx.release, offset=offset + len(refs)) if has_more and refs else None)
        incomplete = [s for s in steps if not s.complete]
        note = None
        if incomplete:
            note = f"{len(incomplete)} route(s) were capped at {ENUMERATE_CAP} codes or by the request budget; the set is a lower bound."
        plan = FindConceptsPlan(combinator=combinator, path=path, steps=steps, note=note)
        return FindConceptsResult(concepts=refs, plan=plan), page


def _refs(items, release: str | None) -> list[ConceptRef]:
    return [ConceptRef(code=str(i.get("code")), name=i.get("name"), terminology=i.get("terminology"), release=i.get("version") or release, leaf=i.get("leaf")) for i in items or []]


def _assoc_entries(data: Any) -> list[dict]:
    if isinstance(data, dict):
        return data.get("associations") or data.get("associationEntries") or data.get("concepts") or []
    return data or []


def _code_sort_key(code: str) -> tuple[int, Any]:
    return (0, int(code[1:])) if code[:1] == "C" and code[1:].isdigit() else (1, code)
