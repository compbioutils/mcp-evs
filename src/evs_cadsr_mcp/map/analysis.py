"""Model grounding, lint, release impact, crosswalk, ICD-O and stored values (UC-1, 2, 5-9)."""

from __future__ import annotations

from ..cadsr.models import MatchEntity
from ..core.context import Invocation
from ..core.envelopes import Provenance
from ..core.errors import EvsMcpError, invalid_request, not_found
from ..core.release import ReleaseContext
from ..evs.models import ConceptRef
from .align import _items_from_enum, _items_from_pvs, align_items
from .capability import CadsrCapability, EvsCapability
from .icdo_map import ICDO_VERSION, IcdoMap, icdo_axis
from .models import (
    CdeSuggestion,
    Crosswalk,
    Finding,
    IcdoMapping,
    Impact,
    LintReport,
    ModelFragment,
    ModelProperty,
    ModelPropertyMapping,
    ReleaseImpact,
    StoredValue,
    StoredValues,
)
from .resolve import _norm, resolve_cde_concepts, resolve_codes


# ------------------------------------------------------------ UC-1 grounding
async def resolve_model_property(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, prop: ModelProperty, *, align: bool = True,
) -> ModelPropertyMapping:
    m = ModelPropertyMapping(property=prop, release=ctx.release or "")
    if not prop.cdeId:
        m.cdeStatus = "missing_cde_id"
        m.notes.append("property carries no caDSR CDE reference")
        if prop.termConceptCode:
            r = (await resolve_codes(evs, inv, ctx, [prop.termConceptCode]))[prop.termConceptCode]
            m.notes.append(f"property-level NCIt term {prop.termConceptCode} is {r.status} at {ctx.release}" + (f" (-> {r.replacement.code})" if r.replacement else ""))
        if prop.enum and any(v.conceptCode for v in prop.enum):
            # No CDE to align against; still validate the enum's own NCIt codes.
            codes = [v.conceptCode for v in prop.enum if v.conceptCode]
            res = await resolve_codes(evs, inv, ctx, codes)
            bad = [c for c, r in res.items() if r.status != "active"]
            if bad:
                m.notes.append("enum NCIt codes not active at release: " + ", ".join(f"{c} ({res[c].status})" for c in bad))
        return m
    try:
        # The enum's codes ride along in the CDE's batch, so alignment below is served from cache.
        enum_codes = [v.conceptCode for v in prop.enum or [] if v.conceptCode] if align else []
        cmap, de = await resolve_cde_concepts(evs, cadsr, inv, ctx, prop.cdeId, prop.cdeVersion,
                                              include_pvs=bool(prop.enum), prefetch=enum_codes)
    except EvsMcpError as exc:
        if exc.code == "not_found":
            m.cdeStatus = "cde_not_found"
            m.notes.append(f"caDSR CDE {prop.cdeId}" + (f" v{prop.cdeVersion}" if prop.cdeVersion else "") + " not found")
            return m
        raise
    m.cde = cmap
    m.cdeStatus = "resolved"
    if de.latestVersion is False and inv.budget.remaining > 0:
        versions = await cadsr.get_versions(inv, prop.cdeId)
        latest = next((v for v in versions if v.latestVersion), versions[0] if versions else None)
        if latest and latest.version != de.version:
            m.cdeStatus = "cde_superseded"
            m.latestCdeVersion = latest.version
            m.notes.append(f"CDE version {de.version} is not the latest ({latest.version}, {latest.workflowStatus})")
    if align and prop.enum:
        pvs = (de.valueDomain.permissibleValues if de.valueDomain else None) or []
        if pvs:
            m.alignment = await align_items(evs, inv, ctx, _items_from_enum(prop.enum), _items_from_pvs(pvs))
        else:
            m.notes.append("model property is enumerated but the CDE value domain has no permissible values")
    return m


async def resolve_fragment(evs, cadsr, inv, ctx, fragment: ModelFragment, *, max_properties: int = 50) -> tuple[list[ModelPropertyMapping], bool]:
    from .fragments import parse_fragment

    props = parse_fragment(fragment)
    truncated = len(props) > max_properties
    out = []
    for p in props[:max_properties]:
        if inv.budget.remaining <= 1:
            truncated = True
            break
        out.append(await resolve_model_property(evs, cadsr, inv, ctx, p))
    return out, truncated


# ------------------------------------------------------------------ UC-8 lint
def lint_mapping(m: ModelPropertyMapping) -> list[Finding]:
    f: list[Finding] = []
    p = m.property.name
    if m.cdeStatus == "missing_cde_id":
        f.append(Finding(severity="warning", code="missing_cde_id", property=p, message="property has no caDSR CDE reference",
                         suggestion="use map_suggest_cdes_for_term to find candidates"))
    elif m.cdeStatus == "cde_not_found":
        f.append(Finding(severity="error", code="cde_not_found", property=p, message=f"CDE {m.property.cdeId} v{m.property.cdeVersion or '?'} not found in caDSR"))
    elif m.cdeStatus == "cde_superseded":
        f.append(Finding(severity="warning", code="stale_cde_version", property=p, message=f"CDE {m.property.cdeId} v{m.property.cdeVersion} is superseded by v{m.latestCdeVersion}",
                         suggestion=f"review v{m.latestCdeVersion} and update cde_version"))
    for note in m.notes:
        if note.startswith("enum NCIt codes not active"):
            f.append(Finding(severity="error", code="invalid_ncit_code", property=p, message=note))
        if note.startswith("property-level NCIt term") and ("retired" in note or "not_found" in note):
            f.append(Finding(severity="error", code="invalid_ncit_code", property=p, message=note))
    if m.cde:
        for lst in (m.cde.objectClass, m.cde.property, m.cde.representationTerm, m.cde.valueMeanings):
            for rc in lst:
                if rc.conceptStatusAtRelease == "retired":
                    f.append(Finding(severity="warning", code="retired_annotation_concept", property=p, value=rc.pvValue,
                                     message=f"CDE {rc.role} concept {rc.conceptCode} is retired at {m.release}",
                                     suggestion=f"replacement {rc.replacement.code} ({rc.replacement.name})" if rc.replacement else None))
                elif rc.conceptStatusAtRelease == "not_found":
                    f.append(Finding(severity="error", code="annotation_concept_not_found", property=p, value=rc.pvValue, message=f"CDE {rc.role} concept {rc.conceptCode} not found at {m.release}"))
    if m.alignment:
        for a in m.alignment.alignments:
            if a.status == "unmapped":
                f.append(Finding(severity="warning", code="enum_value_not_in_cde", property=p, value=a.value, message="enum value has no matching permissible value"))
            elif a.status == "ambiguous":
                f.append(Finding(severity="error", code="enum_concept_mismatch", property=p, value=a.value, message="; ".join(a.evidence)))
            elif a.status == "retired":
                f.append(Finding(severity="warning", code="enum_value_retired_concept", property=p, value=a.value, message="; ".join(a.evidence),
                                 suggestion=f"use {a.replacement.code}" if a.replacement else None))
            elif a.status == "synonym":
                f.append(Finding(severity="info", code="enum_label_differs", property=p, value=a.value, message=f"matches PV '{a.matchedTo}' by concept/synonym, label differs"))
        if m.alignment.unmatchedRight:
            f.append(Finding(severity="info", code="cde_values_not_in_enum", property=p, message=f"{len(m.alignment.unmatchedRight)} CDE permissible value(s) absent from the enum: {m.alignment.unmatchedRight[:10]}"))
    return f


def lint_report(release: str, mappings: list[ModelPropertyMapping]) -> LintReport:
    findings = [x for m in mappings for x in lint_mapping(m)]
    summary: dict[str, int] = {}
    for x in findings:
        summary[x.severity] = summary.get(x.severity, 0) + 1
    return LintReport(release=release, propertiesChecked=len(mappings), findings=findings, summary=summary)


# ---------------------------------------------------------- UC-5 release impact
async def assess_release_impact(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, from_ctx: ReleaseContext, to_ctx: ReleaseContext, scope: dict, *, lookup_cdes: bool, max_codes: int = 200,
) -> ReleaseImpact:
    codes: list[str] = []
    if scope.get("conceptCodes"):
        codes = [str(c) for c in scope["conceptCodes"]]
    elif scope.get("cde"):
        de = await cadsr.get_data_element(inv, str(scope["cde"]["publicId"]), scope["cde"].get("version"))
        from .resolve import cde_annotations, is_ncit_annotation

        codes = [a.conceptCode for _, a, _ in cde_annotations(de, include_pvs=True) if is_ncit_annotation(a)]
    elif scope.get("subset"):
        codes = [m.code for m in await evs.get_subset_members(inv, from_ctx, str(scope["subset"]))]
    else:
        raise invalid_request("scope must give conceptCodes[], cde{publicId,version?} or subset")
    codes = list(dict.fromkeys(codes))[:max_codes]
    before = await resolve_codes(evs, inv, from_ctx, codes)
    after = await resolve_codes(evs, inv, to_ctx, codes)
    impacts: list[Impact] = []
    for code in codes:
        b, a = before[code], after[code]
        name = (b.concept.name if b.concept else None) or (a.concept.name if a.concept else None)
        if b.status == "active" and a.status == "active":
            if b.concept and a.concept and b.concept.name != a.concept.name:
                impacts.append(Impact(conceptCode=code, conceptName=a.concept.name, change="renamed"))
            continue
        if a.status == "retired":
            merged = any((ev.action or "").lower().startswith("merge") for ev in (a.concept.history if a.concept else []) or [])
            impacts.append(Impact(conceptCode=code, conceptName=name, change="merged" if merged else "retired", replacement=a.replacement))
        elif a.status == "not_found":
            impacts.append(Impact(conceptCode=code, conceptName=name, change="not_in_target", replacement=a.replacement))
    if lookup_cdes:
        for imp in impacts[:20]:
            if inv.budget.remaining <= 0:
                inv.warn("budget exhausted before every impacted concept was checked for CDEs")
                break
            imp.dataElements = await cadsr.find_by_concept(inv, imp.conceptCode, item_type=None)
    return ReleaseImpact(fromRelease=from_ctx.release or "", toRelease=to_ctx.release or "", scope=scope, impacts=impacts, checked=len(codes))


# ------------------------------------------------------------- UC-6 crosswalk
def crosswalk(left: ModelPropertyMapping, right: ModelPropertyMapping) -> Crosswalk:
    def concept_set(m: ModelPropertyMapping) -> set[str]:
        if not m.cde:
            return {m.property.termConceptCode} if m.property.termConceptCode else set()
        return {rc.conceptCode for rc in m.cde.objectClass + m.cde.property + m.cde.representationTerm}

    ls, rs = concept_set(left), concept_set(right)
    shared, lo, ro = sorted(ls & rs), sorted(ls - rs), sorted(rs - ls)
    if left.property.cdeId and left.property.cdeId == right.property.cdeId:
        basis = "same_cde" if (left.property.cdeVersion or None) == (right.property.cdeVersion or None) else "same_cde_different_version"
    elif ls and ls == rs:
        basis = "same_concepts"
    elif shared:
        basis = "partial"
    else:
        basis = "none"
    overlap = None
    if left.property.enum and right.property.enum:
        lv = {_norm(v.value) for v in left.property.enum}
        rv = {_norm(v.value) for v in right.property.enum}
        lc = {v.conceptCode for v in left.property.enum if v.conceptCode}
        rc = {v.conceptCode for v in right.property.enum if v.conceptCode}
        overlap = {"sharedValues": len(lv & rv), "leftOnlyValues": len(lv - rv), "rightOnlyValues": len(rv - lv), "sharedConcepts": len(lc & rc)}
    return Crosswalk(left=left, right=right, basis=basis, sharedConcepts=shared, leftOnlyConcepts=lo, rightOnlyConcepts=ro, enumOverlap=overlap)  # type: ignore[arg-type]


# --------------------------------------------------------------- UC-9 ICD-O
ICDO_TERM_LIMIT = 20


async def map_icdo_to_ncit(
    evs: EvsCapability, inv: Invocation, ctx: ReleaseContext, icdo_map: IcdoMap, *, icdo_code: str | None, term: str | None, axis: str,
) -> list[IcdoMapping]:
    """ICD-O-3.1 -> NCIt from EVS's mapping files (cached locally); concept status is checked live at ``ctx``."""
    if not icdo_code and not term:
        raise invalid_request("give icdoCode or term")
    if icdo_code:
        code = icdo_code.strip().upper()
        detected = icdo_axis(code)
        if axis != "auto" and detected not in (axis, "unknown"):
            raise invalid_request(f"icdoCode '{icdo_code}' does not look like {axis}")
        matches = [(e, "ICD-O code") for e in icdo_map.lookup(code)]
    else:
        matches, total = icdo_map.search(term or "", axis=None if axis == "auto" else axis, limit=ICDO_TERM_LIMIT)
        if total > len(matches):
            inv.warn(f"{total} mappings match '{term}'; showing the first {len(matches)}. Use a more specific term or an ICD-O code.")
    axes = {e.axis for e, _ in matches}
    inv.add_provenance(Provenance(
        source="evs_download", servedBy="snapshot", terminology="icdo3",
        sourceUri=icdo_map.file_url(next(iter(axes)) if len(axes) == 1 else None), retrievedAt=icdo_map.synced_at,
    ))
    if not matches:
        raise not_found(f"no NCIt concept is mapped to that ICD-O-3 code or term in the EVS ICD-O-3.1 mapping files "
                        f"(published {icdo_map.published_date or 'unknown'})", icdoCode=icdo_code, term=term)

    found = await evs.get_concepts(inv, ctx, [e.ncit_code for e, _ in matches], ["minimal"])
    out: list[IcdoMapping] = []
    for e, via in matches:
        c = found.get(e.ncit_code)
        if c is None:
            status = "not_found"
        elif c.active is False or (c.conceptStatus or "").lower().startswith("retired"):
            status = "retired"
        else:
            status = "active"
        name = c.name if c is not None and c.name else e.ncit_name
        out.append(IcdoMapping(
            icdoCode=e.icdo_code, icdoTerm=e.icdo_term, icdoTermType=e.term_type, icdoVersions=[ICDO_VERSION], ncimCui=e.ncim_cui,
            axis=e.axis,  # type: ignore[arg-type]
            concept=ConceptRef(code=e.ncit_code, name=name, release=ctx.release), ncitName=name,
            conceptStatusAtRelease=status, matchedVia=via,  # type: ignore[arg-type]
            release=ctx.release or "", mapRelease=icdo_map.published_date,
        ))
    if any(m.conceptStatusAtRelease != "active" for m in out):
        inv.warn("some mapped NCIt concepts are retired or absent at this release; check conceptStatusAtRelease")
    return out


# ------------------------------------------------------ stored values (GDC)
async def resolve_stored_value(evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, code: str, commons: str) -> StoredValues:
    commons_l = commons.lower()
    if commons_l != "gdc":
        raise EvsMcpError("capability_unavailable", f"stored values are only resolvable for commons 'gdc' in this deployment (asked: {commons})")
    values: list[StoredValue] = []
    maps = await evs.get_concept_maps(inv, ctx, code, "GDC")
    for m in maps.maps:
        values.append(StoredValue(conceptCode=code, commons="gdc", storedValue=m.targetName or m.targetCode, propertyHint=None, source="mapset",
                                  detail={"type": m.type, "targetCode": m.targetCode, "targetTerminologyVersion": m.targetTerminologyVersion}))
    if not values and inv.budget.remaining > 0:
        entries = await evs.get_mapset_entries(inv, "NCIt_Maps_To_GDC", term=code, limit=50)
        for e in entries.entries:
            if e.sourceCode == code:
                values.append(StoredValue(conceptCode=code, commons="gdc", storedValue=e.targetName or e.targetCode, source="mapset", detail={"type": e.type, "targetCode": e.targetCode}))
    if not values:
        inv.warn("no NCIt->GDC map assertion for this concept; the GDC value may come from a CDE permissible value instead")
    return StoredValues(conceptCode=code, commons="gdc", release=ctx.release or "", values=values)


# ------------------------------------------------- UC-2 / UC-13 suggestion
ROLE_WEIGHT = {"Property": 1.0, "ObjectClass": 0.7, "RepresentationTerm": 0.4, "ValueMeaning": 0.3, None: 0.6}


async def suggest_cdes_for_term(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, term: str, *, description: str | None,
    sample_values: list[str] | None, contexts: list[str] | None, limit: int, backend: str | None,
) -> tuple[list[CdeSuggestion], str]:
    """Returns (suggestions, backend_used). Declared exception: caDSR offers no ranking of its own."""
    chosen = backend or cadsr.match_backend_available()
    if chosen in ("cde_match", "ai_engine"):
        results = await cadsr.match_data_elements(inv, [MatchEntity(name=term, userTip=description, permissibleValues=sample_values)], backend=chosen, match_limit=limit, contexts=contexts)
        return [CdeSuggestion(publicId=r.publicId or "", version=r.version, longName=r.longName, score=r.score or 0.0, backend=chosen,
                              evidence=[f"{chosen} match" + (f" on {r.matchedField}" if r.matchedField else "")]) for r in results if r.publicId][:limit], chosen
    # Native fallback: term -> concepts -> CDEs annotated with those concepts -> PV overlap.
    cands: list[tuple[str, float, str]] = []
    for m in await evs.lookup_concept(inv, ctx, term):
        cands.append((m.concept.code, 1.0 if m.matchKind in ("code", "name") else 0.8, f"term matches NCIt {m.matchKind} of {m.concept.code} ({m.concept.name})"))
    if len(cands) < 3 and inv.budget.remaining > 0:
        for h in await evs.search_concepts(inv, ctx, term, search_type="contains", filters={}, limit=5):
            if all(h.concept.code != c for c, _, _ in cands):
                cands.append((h.concept.code, 0.6, f"term search hit {h.concept.code} ({h.concept.name})"))
    scores: dict[tuple[str, str | None], CdeSuggestion] = {}
    for code, cscore, why in cands[:3]:
        if inv.budget.remaining <= 0:
            inv.warn("budget exhausted before all candidate concepts were checked")
            break
        for role in ("Property", "ObjectClass"):
            for de in await cadsr.find_by_concept(inv, code, item_type=role):
                if contexts and de.context and de.context not in contexts:
                    continue
                key = (de.publicId, de.version)
                s = round(cscore * ROLE_WEIGHT[role], 3)
                ev = [why, f"CDE annotated with {code} as {role}"]
                if key not in scores or scores[key].score < s:
                    scores[key] = CdeSuggestion(publicId=de.publicId, version=de.version, longName=de.longName, score=s, evidence=ev, backend="native")
    ranked = sorted(scores.values(), key=lambda s: (-s.score, s.publicId))[: max(limit, 1) * 2]
    if sample_values:
        wanted = {_norm(v) for v in sample_values}
        for s in ranked[:5]:
            if inv.budget.remaining <= 0:
                break
            try:
                de = await cadsr.get_data_element(inv, s.publicId, s.version)
            except EvsMcpError:
                continue
            pvs = (de.valueDomain.permissibleValues if de.valueDomain else None) or []
            labels = {_norm(p.value) for p in pvs} | {_norm(p.valueMeaning.longName) for p in pvs if p.valueMeaning}
            hit = len(wanted & labels)
            if pvs:
                s.score = round(min(1.0, s.score + 0.3 * hit / max(len(wanted), 1)), 3)
                s.evidence.append(f"{hit}/{len(wanted)} sample values found among {len(pvs)} permissible values")
    ranked.sort(key=lambda s: (-s.score, s.publicId))
    return ranked[:limit], "native"
