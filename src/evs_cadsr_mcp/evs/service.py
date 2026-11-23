"""Transport-independent EVS handlers. One method per tool; each returns an Envelope.

The MCP layer (the ``tools`` package) only validates arguments, builds an :class:`Invocation`,
calls one of these methods, and converts :class:`EvsMcpError` into a tool error.
"""

from __future__ import annotations

from typing import Any, Literal

from ..core.config import Settings
from ..core.context import Invocation
from ..core.cursor import decode_cursor, encode_cursor
from ..core.envelopes import Envelope, Page, Provenance, Truncation
from ..core.errors import EvsMcpError, invalid_request, not_found
from ..core.release import ReleaseContext
from . import content
from .client import EvsClient
from .find_concepts import ConceptSetPlanner
from .models import (
    BatchConcepts,
    Concept,
    ConceptMaps,
    ConceptRef,
    Criterion,
    Edge,
    FindConceptsResult,
    HistoryEvent,
    Mapset,
    MapsetEntries,
    Match,
    MetadataBundle,
    Path,
    Release,
    SearchHit,
    Selector,
    Subset,
    SubtreeResult,
    Terminology,
    TraversalBudget,
    TraversalResult,
)
from .traversal import TraversalEngine

SearchType = Literal["contains", "match", "startsWith", "phrase", "AND", "OR", "fuzzy"]
SEARCH_FILTERS = ("conceptStatus", "property", "value", "synonymSource", "synonymTermType", "definitionSource", "subset", "semanticType")
METADATA_KINDS = (
    "roles", "associations", "properties", "qualifiers", "termTypes",
    "synonymSources", "definitionSources", "conceptStatuses", "synonymTypes", "definitionTypes",
)
RELATIONSHIP_KINDS = ("roles", "inverseRoles", "associations", "inverseAssociations", "disjointWith")


class EvsService:
    def __init__(self, settings: Settings, client: EvsClient) -> None:
        self.settings = settings
        self.client = client
        self.registry = client.registry
        self.engine = TraversalEngine(client)
        self.planner = ConceptSetPlanner(settings, client)

    async def release_context(self, terminology: str | None, release: str | None) -> ReleaseContext:
        return await self.registry.resolve(terminology, release)

    # ------------------------------------------------- traversal and sets (6.4, 6.5)
    def _apply_budget(self, inv: Invocation, budget: TraversalBudget) -> None:
        """The traversal budget's maxRequests becomes the invocation's outbound budget (capped)."""
        inv.budget.max_requests = min(budget.maxRequests, self.settings.budget_max_requests_cap)

    async def traverse(
        self, inv: Invocation, ctx: ReleaseContext, start: list[str], selectors: list[Selector], budget: TraversalBudget, *, include_exclusions: bool,
    ) -> Envelope[TraversalResult]:
        if not start:
            raise invalid_request("start must contain at least one code")
        if len(start) > 20:
            raise invalid_request("at most 20 start codes", given=len(start))
        if not selectors:
            raise invalid_request("at least one selector is required")
        self._apply_budget(inv, budget)
        result, trunc = await self.engine.traverse(inv, ctx, start, selectors, budget, include_exclusions=include_exclusions)
        if result.exclusions:
            inv.warn(f"{len(result.exclusions)} negative-polarity edge(s) recorded but not expanded; set includeExclusions=true to follow them")
        return inv.envelope(result, truncation=trunc)

    async def get_subtree(
        self, inv: Invocation, ctx: ReleaseContext, code: str, depth: int, criteria: list[Criterion], budget: TraversalBudget, *, prune: bool,
    ) -> Envelope[SubtreeResult]:
        depth = max(0, min(depth, 4))
        self._apply_budget(inv, budget)
        result, trunc = await self.engine.subtree(inv, ctx, code, depth, criteria, budget, prune=prune)
        return inv.envelope(result, truncation=trunc)

    async def find_concepts(
        self, inv: Invocation, ctx: ReleaseContext, criteria: list[Criterion], combinator: str, *, limit: int, cursor: str | None,
    ) -> Envelope[FindConceptsResult]:
        result, page = await self.planner.find(inv, ctx, criteria, combinator, limit=limit, cursor=cursor)
        if result.plan.note:
            inv.warn(result.plan.note)
        return inv.envelope(result, page=page)

    # ------------------------------------------------------------ terminologies
    async def list_terminologies(self, inv: Invocation) -> Envelope[list[Terminology]]:
        infos = await self.registry.all_terminologies()
        out = []
        for r in infos:
            lic = self.client.license_for(r.terminology)
            out.append(
                Terminology(
                    terminology=r.terminology, name=r.name, version=r.version, terminologyVersion=r.terminology_version,
                    latest=r.latest, monthly=r.monthly, weekly=r.weekly, date=r.date,
                    description=r.raw.get("description"), licenseStatus=lic.status, licenseText=r.license_text,
                )
            )
        inv.add_provenance(
            Provenance(source="evs_rest", servedBy="cache", sourceUri=self.client.http.public_url("/metadata/terminologies", {"latest": "true"}))
        )
        return inv.envelope(out)

    async def list_releases(self, inv: Invocation, terminology: str | None) -> Envelope[list[Release]]:
        term = (terminology or self.settings.default_terminology).lower()
        live = await self.registry.live_releases(term)
        active = await self.registry.active_release(term)
        inv.add_provenance(
            Provenance(source="evs_rest", servedBy="cache", terminology=term,
                       sourceUri=self.client.http.public_url("/metadata/terminologies", {"terminology": term}))
        )
        out = [
            Release(
                terminology=r.terminology, version=r.version, terminologyVersion=r.terminology_version, date=r.date,
                monthly=r.monthly, weekly=r.weekly, latest=r.latest, live=True, indexed=False, active=r.version == active.version,
            )
            for r in sorted(live, key=lambda r: r.version, reverse=True)
        ]
        return inv.envelope(out)

    async def get_terminology_metadata(self, inv: Invocation, ctx: ReleaseContext, kinds: list[str]) -> Envelope[MetadataBundle]:
        bad = [k for k in kinds if k not in METADATA_KINDS]
        if bad:
            raise invalid_request("unknown metadata kind(s)", unknown=bad, allowed=list(METADATA_KINDS))
        bundle = MetadataBundle(terminology=ctx.terminology, release=ctx.release)
        for kind in kinds:
            data = await self.client.metadata(inv, ctx, kind)
            bundle.kinds[kind] = [
                {k: v for k, v in item.items() if k in {"code", "name", "value", "terminology", "version", "synonyms", "definitions"}}
                if isinstance(item, dict) else item
                for item in (data or [])
            ]
        return inv.envelope(bundle)

    # ----------------------------------------------------------------- concepts
    def _shape(self, ctx: ReleaseContext, raw: dict, include: str | None = None, inv: Invocation | None = None) -> Concept:
        uri = self.client.http.public_url(f"/concept/{ctx.terminology_version}/{raw.get('code')}", {"include": include} if include else None)
        concept = content.concept(raw, terminology=ctx.terminology, release=ctx.release, source_uri=uri)
        # The license gate applies to maps in every concept-returning tool, not only evs_get_concept_maps.
        if concept.maps and not self.client.has_license_key():
            gated = self._gated()
            withheld = sorted({m.targetTerminology or "" for m in concept.maps if (m.targetTerminology or "").lower() in gated})
            if withheld:
                concept.maps = [m for m in concept.maps if (m.targetTerminology or "").lower() not in gated]
                concept.mapsWithheld = withheld
                if inv is not None:
                    inv.warn(f"license gate withheld map targets: {', '.join(withheld)} (configure ECM_LICENSE_KEY)")
        return concept

    async def get_concept(self, inv: Invocation, ctx: ReleaseContext, code: str, include: list[str] | None) -> Envelope[Concept]:
        inc = content.normalise_include(include, self.settings.default_include)
        raw = await self.client.concept(inv, ctx, code, inc)
        if raw is None:
            raise not_found(f"concept {code} not found in {ctx.terminology} {ctx.release}", code=code, release=ctx.release)
        if "full" in inc:
            inv.warn("include=full is expensive; prefer summary plus itemised flags")
        return inv.envelope(self._shape(ctx, raw, inc, inv))

    async def get_concepts(self, inv: Invocation, ctx: ReleaseContext, codes: list[str], include: list[str] | None) -> Envelope[BatchConcepts]:
        if not codes:
            raise invalid_request("codes must not be empty")
        if len(codes) > self.settings.max_page_size:
            raise invalid_request("too many codes", limit=self.settings.max_page_size, given=len(codes))
        inc = content.normalise_include(include, self.settings.default_include)
        raws = await self.client.concepts(inv, ctx, codes, inc)
        found = {str(r.get("code")): r for r in raws}
        concepts = [self._shape(ctx, found[c], inc, inv) for c in dict.fromkeys(codes) if c in found]
        missing = [c for c in dict.fromkeys(codes) if c not in found]
        return inv.envelope(BatchConcepts(concepts=concepts, missing=missing))

    async def lookup_concept(
        self, inv: Invocation, ctx: ReleaseContext, identifier: str, *, match: str, synonym_source: str | None,
        term_type: str | None, include: list[str] | None, limit: int,
    ) -> Envelope[list[Match]]:
        inc = content.normalise_include(include, self.settings.default_include)
        ident = identifier.strip()
        matches: list[Match] = []
        # 1. exact code
        if ident.upper().startswith("C") and ident[1:].isdigit():
            raw = await self.client.concept(inv, ctx, ident.upper(), inc)
            if raw is not None:
                matches.append(Match(concept=self._shape(ctx, raw, inc, inv), matchKind="code", matchedTerm=ident.upper()))
                return inv.envelope(matches)
        # 2. exact name / synonym via upstream type=match. Synonyms must be present in the
        #    payload to classify the match kind, so add the flag when the caller asked for less.
        search_inc = inc if any(f in inc.split(",") for f in ("summary", "full", "synonyms")) else inc + ",synonyms"
        params: dict[str, Any] = {"term": ident, "type": "match", "include": search_inc, "pageSize": limit, "fromRecord": 0}
        if synonym_source:
            params["synonymSource"] = synonym_source
        if term_type:
            params["synonymTermType"] = term_type
        data = await self.client.search(inv, ctx, params)
        norm = _norm(ident) if match == "normalized" else ident
        for raw in data.get("concepts", []):
            c = self._shape(ctx, raw, inc, inv)
            kind, term = _classify_match(raw, ident, norm, match)
            if kind is None:
                continue
            matches.append(Match(concept=c, matchKind=kind, matchedTerm=term))
        matches.sort(key=lambda m: {"code": 0, "name": 1, "synonym": 2}[m.matchKind])
        return inv.envelope(matches[:limit])

    async def search_concepts(
        self, inv: Invocation, ctx: ReleaseContext, term: str | None, *, search_type: SearchType, include: list[str] | None,
        limit: int, cursor: str | None, filters: dict[str, Any],
    ) -> Envelope[list[SearchHit]]:
        if limit < 1 or limit > self.settings.search_max_limit:
            raise invalid_request("limit out of range", min=1, max=self.settings.search_max_limit)
        term = (term or "").strip() or None
        active = {key: v for key in SEARCH_FILTERS if (v := filters.get(key))}
        if term is None and not active:
            raise invalid_request("give a search term, or at least one filter such as property and value", filters=list(SEARCH_FILTERS))
        # EVS ignores its `semanticType` parameter, so the filter is sent as the Semantic_Type
        # property instead. EVS takes one property filter per search.
        if "semanticType" in active:
            if "property" in active or "value" in active:
                raise invalid_request(
                    "semanticType is applied as property Semantic_Type, and EVS search takes one property filter: "
                    "use semanticType or property/value, not both",
                    hint="Run two searches and intersect the codes, or drop one of the two filters.",
                )
            active["property"], active["value"] = "Semantic_Type", active.pop("semanticType")
        inc = content.normalise_include(include, "minimal")
        offset = decode_cursor(cursor, release=ctx.release)[0] if cursor else 0
        # EVS ANDs the term with the filters, so the term is only sent when given: a filter-only
        # search (e.g. property=ICD-O-3_Code, value=8140/3) must not carry text the concept lacks.
        params: dict[str, Any] = {"type": search_type, "include": inc, "fromRecord": offset, "pageSize": limit, **active}
        if term is not None:
            params["term"] = term
        data = await self.client.search(inv, ctx, params)
        hits = [SearchHit(concept=self._shape(ctx, raw, inc, inv), score=raw.get("score"), highlight=raw.get("highlight")) for raw in data.get("concepts", [])]
        total = data.get("total")
        page = _page(limit, offset, total, len(hits), ctx.release)
        return inv.envelope(hits, page=page)

    async def suggest_concepts(self, inv: Invocation, ctx: ReleaseContext, prefix: str, limit: int) -> Envelope[list[ConceptRef]]:
        limit = max(1, min(limit, 20))
        data = await self.client.search(inv, ctx, {"term": prefix, "type": "startsWith", "include": "minimal", "pageSize": limit, "fromRecord": 0})
        return inv.envelope(content.refs(data.get("concepts", []), release=ctx.release)[:limit])

    # ---------------------------------------------------------------- hierarchy
    async def get_hierarchy_neighbors(self, inv: Invocation, ctx: ReleaseContext, code: str | None, direction: str) -> Envelope[list[Edge]]:
        if direction == "roots":
            raws = await self.client.roots(inv, ctx)
            return inv.envelope([content.edge(r, "root") for r in raws or []])
        if not code:
            raise invalid_request("code is required unless direction is 'roots'")
        part = {"parents": "parents", "children": "children"}.get(direction)
        if part is None:
            raise invalid_request("direction must be parents, children or roots")
        raws = await self.client.concept_part(inv, ctx, code, part)
        if raws is None:
            raise not_found(f"concept {code} not found", code=code)
        kind = "parent" if part == "parents" else "child"
        return inv.envelope([content.edge(r, kind) for r in raws])

    async def get_descendants(self, inv: Invocation, ctx: ReleaseContext, code: str, *, max_level: int | None, limit: int, cursor: str | None) -> Envelope[list[ConceptRef]]:
        limit = max(1, min(limit, self.settings.max_page_size))
        offset = decode_cursor(cursor, release=ctx.release)[0] if cursor else 0
        params: dict[str, Any] = {"fromRecord": offset, "pageSize": limit}
        if max_level is not None:
            params["maxLevel"] = max_level
        raws = await self.client.concept_part(inv, ctx, code, "descendants", params)
        if raws is None:
            raise not_found(f"concept {code} not found", code=code)
        items = content.refs(raws, release=ctx.release)
        page = _page(limit, offset, None, len(items), ctx.release, more=len(items) >= limit)
        return inv.envelope(items, page=page)

    async def get_paths(self, inv: Invocation, ctx: ReleaseContext, code: str, kind: str, ancestor_code: str | None) -> Envelope[list[Path]]:
        if kind == "toRoot":
            raw = await self.client.concept_part(inv, ctx, code, "pathsToRoot")
        elif kind == "fromRoot":
            raw = await self.client.concept_part(inv, ctx, code, "pathsFromRoot")
        elif kind == "toAncestor":
            if not ancestor_code:
                raise invalid_request("ancestorCode is required for kind=toAncestor")
            raw = await self.client.concept_part(inv, ctx, code, f"pathsToAncestor/{ancestor_code}")
        else:
            raise invalid_request("kind must be toRoot, fromRoot or toAncestor")
        if raw is None:
            raise not_found(f"concept {code} not found", code=code)
        return inv.envelope(content.paths(raw, kind, release=ctx.release))

    async def get_relationships(self, inv: Invocation, ctx: ReleaseContext, code: str, kinds: list[str], names: list[str] | None) -> Envelope[list[Edge]]:
        bad = [k for k in kinds if k not in RELATIONSHIP_KINDS]
        if bad:
            raise invalid_request("unknown relationship kind(s)", unknown=bad, allowed=list(RELATIONSHIP_KINDS))
        raw = await self.client.concept(inv, ctx, code, ",".join(kinds))
        if raw is None:
            raise not_found(f"concept {code} not found", code=code)
        singular = {"roles": "role", "inverseRoles": "inverseRole", "associations": "association",
                    "inverseAssociations": "inverseAssociation", "disjointWith": "disjointWith"}
        out: list[Edge] = []
        for k in kinds:
            out.extend(content.edges(raw.get(k), singular[k]) or [])
        if names:
            wanted = set(names)
            out = [e for e in out if e.type in wanted]
        return inv.envelope(out)

    # ------------------------------------------------------------------ subsets
    async def list_subsets(self, inv: Invocation, ctx: ReleaseContext, code: str | None, include: str) -> Envelope[list[Subset]]:
        if code:
            raw = await self.client.subset(inv, ctx, code, include)
            if raw is None:
                raise not_found(f"subset {code} not found", code=code)
            return inv.envelope([content.subset(raw, release=ctx.release)])
        raws = await self.client.subsets(inv, ctx, include)
        return inv.envelope([content.subset(r, release=ctx.release) for r in raws])

    async def get_subset_members(self, inv: Invocation, ctx: ReleaseContext, code: str, *, include: list[str] | None, limit: int, cursor: str | None) -> Envelope[list[Concept]]:
        limit = max(1, min(limit, self.settings.max_page_size))
        inc = content.normalise_include(include, "minimal")
        offset = decode_cursor(cursor, release=ctx.release)[0] if cursor else 0
        raws = await self.client.subset_members(inv, ctx, code, include=inc, from_record=offset, page_size=limit)
        items = [self._shape(ctx, r, inc, inv) for r in raws]
        page = _page(limit, offset, None, len(items), ctx.release, more=len(items) >= limit)
        return inv.envelope(items, page=page)

    # --------------------------------------------------------------------- maps
    def _gated(self) -> set[str]:
        return {t.lower() for t in self.settings.license_gated_terminologies}

    async def get_concept_maps(self, inv: Invocation, ctx: ReleaseContext, code: str, target_terminology: str | None) -> Envelope[ConceptMaps]:
        raw = await self.client.concept(inv, ctx, code, "maps")
        if raw is None:
            raise not_found(f"concept {code} not found", code=code)
        maps = [content.map_assertion(m) for m in raw.get("maps", [])]
        if target_terminology:
            maps = [m for m in maps if (m.targetTerminology or "").lower() == target_terminology.lower()]
        withheld: list[str] = []
        if not self.client.has_license_key():
            gated = self._gated()
            kept = []
            for m in maps:
                if (m.targetTerminology or "").lower() in gated:
                    if m.targetTerminology not in withheld:
                        withheld.append(m.targetTerminology or "")
                else:
                    kept.append(m)
            maps = kept
            if withheld:
                inv.warn(f"license gate withheld map targets: {', '.join(withheld)} (configure ECM_LICENSE_KEY)")
        return inv.envelope(ConceptMaps(code=code, maps=maps, withheld=withheld))

    async def list_mapsets(self, inv: Invocation) -> Envelope[list[Mapset]]:
        raws = await self.client.mapsets(inv, include="properties")
        return inv.envelope([content.mapset(r, gated=self._gated()) for r in raws])

    async def get_mapset_entries(self, inv: Invocation, mapset_code: str, *, term: str | None, limit: int, cursor: str | None) -> Envelope[MapsetEntries]:
        limit = max(1, min(limit, self.settings.max_page_size))
        raw = await self.client.mapset(inv, mapset_code, include="properties")
        if raw is None:
            raise not_found(f"mapset {mapset_code} not found", mapset=mapset_code)
        ms = content.mapset(raw, gated=self._gated())
        offset = decode_cursor(cursor, release=None)[0] if cursor else 0
        key = self.settings.license_key if ms.licenseRequired else None
        if ms.licenseRequired and not key:
            # Count only, plus the licenseRequired marker (Section 6.6).
            data = await self.client.mapset_maps(inv, mapset_code, term=term, from_record=0, page_size=1, license_key=None)
            total = _total(data)
            inv.warn("mapset target terminology requires a license key; assertions withheld")
            return inv.envelope(MapsetEntries(mapset=ms, total=total, entries=[], licenseRequired=True))
        data = await self.client.mapset_maps(inv, mapset_code, term=term, from_record=offset, page_size=limit, license_key=key)
        entries = [content.map_assertion(m) for m in _maps(data)]
        page = _page(limit, offset, _total(data), len(entries), None)
        return inv.envelope(MapsetEntries(mapset=ms, total=_total(data), entries=entries, licenseRequired=False), page=page)

    # ------------------------------------------------------------------ history
    async def get_concept_history(self, inv: Invocation, ctx: ReleaseContext, code: str) -> Envelope[list[HistoryEvent]]:
        raw = await self.client.concept(inv, ctx, code, "minimal,history")
        events: list[HistoryEvent] = []
        if raw is None:
            # Retired codes may be absent at this release; replacements endpoint still answers.
            repl = await self.client.replacements(inv, ctx, code)
            if repl is None:
                raise not_found(f"concept {code} not found and has no replacement record", code=code)
            for r in repl if isinstance(repl, list) else [repl]:
                events.append(content.history_event(r))
            inv.warn(f"{code} is not present at {ctx.release}; events come from the replacements endpoint")
            return inv.envelope(events)
        events = [content.history_event(h) for h in raw.get("history", [])]
        if raw.get("active") is False or (raw.get("conceptStatus") or "").lower().startswith("retired"):
            repl = await self.client.replacements(inv, ctx, code)
            for r in repl or []:
                ev = content.history_event(r)
                if ev not in events:
                    events.append(ev)
        return inv.envelope(events)


# -------------------------------------------------------------------- helpers
def _page(limit: int, offset: int, total: int | None, returned: int, release: str | None, *, more: bool | None = None) -> Page:
    has_more = more if more is not None else (total is not None and offset + returned < total)
    return Page(
        limit=limit, offset=offset, total=total, returned=returned,
        nextCursor=encode_cursor(release=release, offset=offset + returned) if has_more and returned else None,
    )


def _total(data: Any) -> int | None:
    if isinstance(data, dict):
        return data.get("total")
    if isinstance(data, list):
        return len(data)
    return None


def _maps(data: Any) -> list[dict]:
    if isinstance(data, dict):
        return data.get("maps") or data.get("concepts") or []
    return data or []


def _norm(s: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in s).split())


def _classify_match(raw: dict, ident: str, norm: str, mode: str) -> tuple[str | None, str | None]:
    def eq(a: str | None) -> bool:
        if a is None:
            return False
        return (_norm(a) == norm) if mode == "normalized" else (a.casefold() == ident.casefold())

    if eq(raw.get("name")):
        return "name", raw.get("name")
    for s in raw.get("synonyms", []) or []:
        if eq(s.get("name")):
            return "synonym", s.get("name")
    return None, None


def truncation(bound: str, limit: int, reached: int, omitted: int | None, exact: bool = True) -> Truncation:
    return Truncation(occurred=True, bound=bound, limit=limit, reached=reached, omitted=omitted, exact=exact)


__all__ = ["EvsService", "EvsMcpError", "SearchType", "METADATA_KINDS", "RELATIONSHIP_KINDS"]
