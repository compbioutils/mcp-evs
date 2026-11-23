"""Value-set alignment (UC-3, UC-14): left values vs. right values with per-value verdicts.

Statuses: ``exact`` (same concept and/or same normalised label), ``synonym`` (same concept
under a different label, or label equals an NCIt synonym of the right concept), ``retired``
(left concept retired at the release), ``ambiguous`` (several right candidates),
``unmapped``. Each verdict carries an evidence list naming what was compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..cadsr.models import PermissibleValue
from ..core.context import Invocation
from ..core.errors import invalid_request
from ..core.release import ReleaseContext
from ..evs.models import Concept
from .capability import CadsrCapability, EvsCapability
from .models import ModelEnumValue, ValueAlignment, ValueSetAlignment, ValueSetSide
from .resolve import _norm, concept_names, is_ncit_annotation, resolve_codes


@dataclass
class Item:
    value: str
    code: str | None = None
    label: str | None = None  # value-meaning long name / concept name
    extra: set[str] = field(default_factory=set)  # alternative labels (synonyms)


def _items_from_pvs(pvs: list[PermissibleValue]) -> list[Item]:
    out = []
    for pv in pvs:
        code = None
        label = None
        if pv.valueMeaning:
            label = pv.valueMeaning.longName
            ann = next((a for a in pv.valueMeaning.concepts if is_ncit_annotation(a) and a.primaryIndicator is not False), None) or next(
                (a for a in pv.valueMeaning.concepts if is_ncit_annotation(a)), None)
            code = ann.conceptCode if ann else None
        out.append(Item(value=pv.value, code=code, label=label))
    return out


def _items_from_enum(values: list[ModelEnumValue]) -> list[Item]:
    return [Item(value=v.value, code=v.conceptCode) for v in values]


def _items_from_gdc_enum_def(block: dict) -> list[Item]:
    from .fragments import _gdc_property  # reuse the GDC parser

    prop = _gdc_property("enum", block if "enumDef" in block or "enum" in block else {"enumDef": block}, None)
    return _items_from_enum(prop.enum)


def _items_from_mdf_enum(items: list) -> list[Item]:
    from .fragments import mdf_properties

    prop = mdf_properties({"PropDefinitions": {"enum": {"Enum": items}}})[0]
    return _items_from_enum(prop.enum)


async def _side_items(evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, side: ValueSetSide, *, allow_subset: bool) -> list[Item]:
    chosen = [k for k in ("cde", "values", "gdcEnumDef", "mdfEnum", "ncitSubset") if getattr(side, k) is not None]
    if len(chosen) != 1:
        raise invalid_request("each side must set exactly one of cde, values, gdcEnumDef, mdfEnum, ncitSubset", given=chosen)
    kind = chosen[0]
    if kind == "cde":
        de = await cadsr.get_data_element(inv, str(side.cde.get("publicId")), side.cde.get("version"))
        return _items_from_pvs((de.valueDomain.permissibleValues if de.valueDomain else None) or [])
    if kind == "values":
        return [Item(value=str(v)) for v in side.values]
    if kind == "gdcEnumDef":
        return _items_from_gdc_enum_def(side.gdcEnumDef)
    if kind == "mdfEnum":
        return _items_from_mdf_enum(side.mdfEnum)
    if not allow_subset:
        raise invalid_request("ncitSubset is only valid on the right side")
    members = await evs.get_subset_members(inv, ctx, side.ncitSubset)
    return [Item(value=m.name or m.code, code=m.code, label=m.name, extra=concept_names(m)) for m in members]


async def align_value_sets(
    evs: EvsCapability, cadsr: CadsrCapability, inv: Invocation, ctx: ReleaseContext, left: ValueSetSide, right: ValueSetSide,
) -> ValueSetAlignment:
    left_items = await _side_items(evs, cadsr, inv, ctx, left, allow_subset=False)
    right_items = await _side_items(evs, cadsr, inv, ctx, right, allow_subset=True)
    return await align_items(evs, inv, ctx, left_items, right_items)


async def align_items(evs: EvsCapability, inv: Invocation, ctx: ReleaseContext, left_items: list[Item], right_items: list[Item]) -> ValueSetAlignment:
    # Resolve every concept once (gives status, names and synonyms for both sides).
    codes = [i.code for i in left_items + right_items if i.code]
    res = await resolve_codes(evs, inv, ctx, codes)
    concepts: dict[str, Concept] = {c: r.concept for c, r in res.items() if r.concept is not None}

    def labels(item: Item) -> set[str]:
        s = {_norm(item.value)}
        if item.label:
            s.add(_norm(item.label))
        s |= {_norm(x) for x in item.extra}
        if item.code and item.code in concepts:
            s |= concept_names(concepts[item.code])
        return s - {""}

    right_labels = [(r, labels(r)) for r in right_items]
    by_code: dict[str, list[Item]] = {}
    for r in right_items:
        if r.code:
            by_code.setdefault(r.code, []).append(r)

    alignments: list[ValueAlignment] = []
    matched_right: set[int] = set()
    for li in left_items:
        ev: list[str] = []
        lres = res.get(li.code) if li.code else None
        # 1. same concept code on both sides
        cands = by_code.get(li.code or "", [])
        if li.code and lres and lres.status == "retired":
            repl = lres.replacement
            ev.append(f"left concept {li.code} is retired at {ctx.release}" + (f"; replacement {repl.code} ({repl.name})" if repl else ""))
            target = cands  # the right side carries the same (retired) concept
            matched_concept = li.code if cands else None
            if cands:
                ev.append(f"right '{cands[0].value}' carries the same retired concept")
            elif repl and by_code.get(repl.code):
                target = by_code[repl.code]
                matched_concept = repl.code
                ev.append(f"replacement {repl.code} present on the right as '{target[0].value}'")
            alignments.append(ValueAlignment(value=li.value, conceptCode=li.code, status="retired", matchedTo=target[0].value if target else None,
                                             matchedConcept=matched_concept, replacement=repl, evidence=ev))
            if target:
                matched_right.add(right_items.index(target[0]))
            continue
        if li.code and lres and lres.status == "not_found":
            ev.append(f"left concept {li.code} not found at {ctx.release}")
        if cands:
            r = cands[0]
            same_label = _norm(li.value) == _norm(r.value)
            ev.append(f"same NCIt concept {li.code} on both sides" + ("" if same_label else f"; labels differ ('{li.value}' vs '{r.value}')"))
            alignments.append(ValueAlignment(value=li.value, conceptCode=li.code, status="exact" if same_label else "synonym", matchedTo=r.value, matchedConcept=r.code, evidence=ev))
            matched_right.add(right_items.index(r))
            continue
        # 2. label equality / synonym against right labels
        ln = _norm(li.value)
        lnames = labels(li)
        exact = [(idx, r) for idx, (r, rl) in enumerate(right_labels) if ln == _norm(r.value)]
        syn = [(idx, r) for idx, (r, rl) in enumerate(right_labels) if (idx, r) not in exact and (lnames & rl)]
        if len(exact) == 1 or (len(exact) > 1 and len({r.code for _, r in exact}) == 1):
            idx, r = exact[0]
            ev.append(f"value label equals right value '{r.value}'")
            if li.code and r.code and li.code != r.code:
                ev.append(f"but concepts differ: left {li.code} vs right {r.code}")
                alignments.append(ValueAlignment(value=li.value, conceptCode=li.code, status="ambiguous", matchedTo=r.value, matchedConcept=r.code, evidence=ev))
            else:
                alignments.append(ValueAlignment(value=li.value, conceptCode=li.code or r.code, status="exact", matchedTo=r.value, matchedConcept=r.code, evidence=ev))
            matched_right.add(idx)
            continue
        if len(exact) > 1:
            ev.append("several right values share this label with different concepts: " + ", ".join(f"{r.value}/{r.code}" for _, r in exact))
            alignments.append(ValueAlignment(value=li.value, conceptCode=li.code, status="ambiguous", evidence=ev))
            continue
        if len(syn) == 1 or (len(syn) > 1 and len({r.code for _, r in syn}) == 1):
            idx, r = syn[0]
            shared = sorted(lnames & right_labels[idx][1])[:3]
            ev.append(f"label matches a synonym/name of right '{r.value}'" + (f" ({r.code})" if r.code else "") + f": {shared}")
            alignments.append(ValueAlignment(value=li.value, conceptCode=li.code or r.code, status="synonym", matchedTo=r.value, matchedConcept=r.code, evidence=ev))
            matched_right.add(idx)
            continue
        if len(syn) > 1:
            ev.append("label matches synonyms of several right concepts: " + ", ".join(f"{r.value}/{r.code}" for _, r in syn))
            alignments.append(ValueAlignment(value=li.value, conceptCode=li.code, status="ambiguous", evidence=ev))
            continue
        ev.append("no right value, name or synonym matched")
        alignments.append(ValueAlignment(value=li.value, conceptCode=li.code, status="unmapped", evidence=ev))

    unmatched = [r.value for i, r in enumerate(right_items) if i not in matched_right]
    summary: dict[str, int] = {}
    for a in alignments:
        summary[a.status] = summary.get(a.status, 0) + 1
    return ValueSetAlignment(release=ctx.release or "", leftCount=len(left_items), rightCount=len(right_items), alignments=alignments, unmatchedRight=unmatched, summary=summary)
