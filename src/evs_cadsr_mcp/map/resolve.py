"""CDE <-> NCIt resolution at a pinned release (UC-1, UC-4, proposal 8.2).

``resolve_codes`` is the shared primitive: one batch EVS call for all codes, then history
lookups only for codes that are retired or absent, so a CDE with eight permissible values
costs one or two upstream calls at the EVS side.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cadsr.models import ConceptAnnotation, DataElement
from ..core.context import Invocation
from ..core.errors import invalid_request, not_found
from ..core.release import ReleaseContext
from ..evs.models import Concept, ConceptRef
from .capability import CadsrCapability, EvsCapability
from .models import (
    CdeConceptMap,
    ConceptGroup,
    ConceptStatusAtRelease,
    DataElementsForConcept,
    PvExplanation,
    ResolvedConcept,
)

NCIT_SOURCES = {None, "", "NCI_CONCEPT_CODE", "NCIT", "NCI THESAURUS"}


@dataclass
class Resolution:
    code: str
    concept: Concept | None
    status: ConceptStatusAtRelease
    replacement: ConceptRef | None = None


def is_ncit_annotation(a: ConceptAnnotation) -> bool:
    return (a.evsSource or "").upper() in NCIT_SOURCES and a.conceptCode[:1].upper() == "C" and a.conceptCode[1:].isdigit()


def _norm(s: str | None) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in (s or "")).split())


def concept_names(c: Concept) -> set[str]:
    names = {_norm(c.name)}
    for s in c.synonyms or []:
        names.add(_norm(s.name))
    return names - {""}


async def resolve_codes(evs: EvsCapability, inv: Invocation, ctx: ReleaseContext, codes: list[str]) -> dict[str, Resolution]:
    """Batch-resolve NCIt codes at the pinned release; retired/missing codes get history."""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}
    found = await evs.get_concepts(inv, ctx, codes, ["summary", "history"])
    out: dict[str, Resolution] = {}
    for code in codes:
        c = found.get(code)
        if c is None:
            out[code] = Resolution(code=code, concept=None, status="not_found")
            continue
        retired = c.active is False or (c.conceptStatus or "").lower().startswith("retired") or (c.conceptStatus or "").lower() == "obsolete_concept"
        repl = _replacement_from_history(c)
        out[code] = Resolution(code=code, concept=c, status="retired" if retired else "active", replacement=repl)
    # Absent codes: ask the replacements endpoint (bounded by budget).
    for code, r in out.items():
        if r.status == "not_found" and inv.budget.remaining > 0:
            events = await evs.get_concept_history(inv, ctx, code)
            for ev in events:
                if ev.replacementCode:
                    r.status = "retired"
                    r.replacement = ConceptRef(code=ev.replacementCode, name=ev.replacementName, release=ctx.release)
                    break
        elif r.status == "retired" and r.replacement is None and inv.budget.remaining > 0:
            events = await evs.get_concept_history(inv, ctx, code)
            for ev in events:
                if ev.replacementCode:
                    r.replacement = ConceptRef(code=ev.replacementCode, name=ev.replacementName, release=ctx.release)
                    break
    return out


def _replacement_from_history(c: Concept) -> ConceptRef | None:
    for ev in c.history or []:
        if ev.replacementCode and (ev.action or "").lower() in ("merge", "retire", "split", "merged", "retired"):
            return ConceptRef(code=ev.replacementCode, name=ev.replacementName, release=c.release)
    return None


def _resolved(role: str, a: ConceptAnnotation, r: Resolution | None, pv_value: str | None = None) -> ResolvedConcept:
    c = r.concept if r else None
    agrees = None
    if c is not None and a.longName:
        agrees = _norm(a.longName) in concept_names(c)
    return ResolvedConcept(
        role=role,  # type: ignore[arg-type]
        conceptCode=a.conceptCode,
        cadsrName=a.longName,
        evsSource=a.evsSource,
        primaryIndicator=a.primaryIndicator,
        displayOrder=a.displayOrder,
        ncitName=c.name if c else None,
        conceptStatusAtRelease=r.status if r else "unresolved",
        semanticTypes=c.semanticTypes if c else [],
        replacement=r.replacement if r else None,
        nameAgrees=agrees,
        pvValue=pv_value,
    )


def cde_annotations(de: DataElement, *, include_pvs: bool) -> list[tuple[str, ConceptAnnotation, str | None]]:
    rows: list[tuple[str, ConceptAnnotation, str | None]] = []
    dec = de.dataElementConcept
    if dec and dec.objectClass:
        rows += [("ObjectClass", a, None) for a in dec.objectClass.concepts]
    if dec and dec.property:
        rows += [("Property", a, None) for a in dec.property.concepts]
    vd = de.valueDomain
    if vd and vd.representationTerm:
        rows += [("RepresentationTerm", a, None) for a in vd.representationTerm.concepts]
    if include_pvs and vd and vd.permissibleValues:
        for pv in vd.permissibleValues:
            if pv.valueMeaning:
                rows += [("ValueMeaning", a, pv.value) for a in pv.valueMeaning.concepts]
    return rows


async def resolve_cde_concepts(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, public_id: str, version: str | None, *, include_pvs: bool,
    prefetch: list[str] | None = None,
) -> tuple[CdeConceptMap, DataElement]:
    """``prefetch`` codes join the same EVS batch so a later step finds them cached; they don't
    affect the result."""
    de = await cadsr.get_data_element(inv, public_id, version)
    rows = cde_annotations(de, include_pvs=include_pvs)
    ncit_codes = [a.conceptCode for _, a, _ in rows if is_ncit_annotation(a)]
    res = await resolve_codes(evs, inv, ctx, ncit_codes + [c for c in prefetch or [] if c])
    cmap = CdeConceptMap(publicId=de.publicId, version=de.version, longName=de.longName, release=ctx.release or "")
    bucket = {"ObjectClass": cmap.objectClass, "Property": cmap.property, "RepresentationTerm": cmap.representationTerm, "ValueMeaning": cmap.valueMeanings}
    for role, a, pv in rows:
        r = res.get(a.conceptCode) if is_ncit_annotation(a) else None
        rc = _resolved(role, a, r, pv)
        if not is_ncit_annotation(a):
            rc.conceptStatusAtRelease = "unresolved"
        bucket[role].append(rc)
    counts: dict[str, int] = {}
    for lst in bucket.values():
        for rc in lst:
            counts[rc.conceptStatusAtRelease] = counts.get(rc.conceptStatusAtRelease, 0) + 1
    cmap.summary = counts
    if counts.get("retired"):
        inv.warn(f"{counts['retired']} annotation concept(s) are retired at {ctx.release}; see replacement")
    if counts.get("unresolved"):
        inv.warn(f"{counts['unresolved']} annotation(s) are not NCIt codes (other evsSource) and were not resolved")
    return cmap, de


async def data_elements_for_concept(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, code: str, *, expand: bool, max_level: int, max_concepts: int, item_type: str | None,
) -> tuple[DataElementsForConcept, str | None]:
    """UC-4: CDEs annotated with a concept, optionally with bounded descendant expansion.
    Returns the result and the name of the bound that truncated it (or None)."""
    res = await resolve_codes(evs, inv, ctx, [code])
    root = res[code]
    if root.status == "not_found":
        raise not_found(f"concept {code} not found at {ctx.release}", code=code)
    targets: list[tuple[ConceptRef, int]] = [(ConceptRef(code=code, name=root.concept.name if root.concept else None, release=ctx.release), 0)]
    truncated: str | None = None
    if expand:
        desc = await evs.get_descendants(inv, ctx, code, max_level=max_level, limit=max_concepts)
        if len(desc) >= max_concepts:
            truncated = "maxConcepts"
        for d in desc[: max_concepts - 1]:
            targets.append((d, d.level or 1))
    groups: list[ConceptGroup] = []
    total = 0
    for ref, depth in targets:
        if inv.budget.remaining <= 0:
            truncated = "maxRequests"
            break
        des = await cadsr.find_by_concept(inv, ref.code, item_type=item_type)
        if des or depth == 0:
            groups.append(ConceptGroup(concept=ref, depth=depth, dataElements=des))
            total += len(des)
    return DataElementsForConcept(conceptCode=code, release=ctx.release or "", expandedDescendants=expand, groups=groups, totalDataElements=total), truncated


async def explain_permissible_value(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, public_id: str, version: str | None, value: str,
) -> PvExplanation:
    de = await cadsr.get_data_element(inv, public_id, version)
    pvs = (de.valueDomain.permissibleValues if de.valueDomain else None) or []
    target = next((p for p in pvs if p.value == value), None) or next((p for p in pvs if _norm(p.value) == _norm(value)), None)
    if target is None:
        raise invalid_request(f"'{value}' is not a permissible value of {public_id}", knownValues=[p.value for p in pvs][:50])
    ann = next((a for a in (target.valueMeaning.concepts if target.valueMeaning else []) if is_ncit_annotation(a)), None)
    concept = None
    status: ConceptStatusAtRelease = "unresolved"
    repl = None
    definition = def_source = None
    synonyms: list[str] = []
    if ann:
        r = (await resolve_codes(evs, inv, ctx, [ann.conceptCode]))[ann.conceptCode]
        status, repl = r.status, r.replacement
        if r.concept:
            concept = ConceptRef(code=r.concept.code, name=r.concept.name, release=ctx.release)
            d = next((d for d in (r.concept.definitions or []) if d.source == "NCI"), None) or next(iter(r.concept.definitions or []), None)
            if d:
                definition, def_source = d.definition, d.source
            synonyms = sorted({s.name for s in (r.concept.synonyms or []) if s.name and _norm(s.name) != _norm(r.concept.name)})[:25]
    return PvExplanation(
        publicId=de.publicId, version=de.version, value=target.value, valueDescription=target.valueDescription, valueMeaning=ann,
        valueMeaningLongName=target.valueMeaning.longName if target.valueMeaning else None, concept=concept, conceptStatusAtRelease=status,
        definition=definition, definitionSource=def_source, synonyms=synonyms, replacement=repl, release=ctx.release or "",
    )
