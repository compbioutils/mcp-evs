"""Shape raw EVS JSON into compact records (proposal Section 6.2).

Parsing is deliberately tolerant: EVS payload shapes vary slightly by endpoint and
``include`` flag, and the contract fixtures under ``tests/fixtures`` pin what we have
seen live. Nothing here invents content; absent fields stay ``None``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import (
    Concept,
    ConceptRef,
    Definition,
    Edge,
    HistoryEvent,
    MapAssertion,
    Mapset,
    Path,
    Property,
    Qualifier,
    Subset,
    Synonym,
)

# NCIt roles with negative semantics (proposal Section 6.4). Configurable at deployment;
# this default covers the Disease_Excludes_* family.
DEFAULT_NEGATIVE_ROLES: frozenset[str] = frozenset(
    {
        "Disease_Excludes_Abnormal_Cell",
        "Disease_Excludes_Cytogenetic_Abnormality",
        "Disease_Excludes_Finding",
        "Disease_Excludes_Molecular_Abnormality",
        "Disease_Excludes_Normal_Cell_Origin",
        "Disease_Excludes_Normal_Tissue_Origin",
        "Disease_Excludes_Primary_Anatomic_Site",
        "Disease_Excludes_Metastatic_Anatomic_Site",
    }
)

INCLUDE_FLAGS: frozenset[str] = frozenset(
    {
        "minimal", "summary", "full",
        "synonyms", "definitions", "properties", "children", "parents", "roles", "inverseRoles",
        "associations", "inverseAssociations", "maps", "history", "paths", "descendants",
        "disjointWith", "subsetLink", "extensions",
    }
)


def normalise_include(include: Iterable[str] | str | None, default: str = "summary") -> str:
    if include is None:
        return default
    items = [include] if isinstance(include, str) else list(include)
    flat: list[str] = []
    for item in items:
        flat.extend(p.strip() for p in item.split(",") if p.strip())
    bad = [f for f in flat if f not in INCLUDE_FLAGS]
    if bad:
        from ..core.errors import invalid_request

        raise invalid_request("unknown include flag(s)", unknown=bad, allowed=sorted(INCLUDE_FLAGS))
    return ",".join(dict.fromkeys(flat)) or default


# ------------------------------------------------------------------ primitives
def ref(d: dict[str, Any] | None, *, release: str | None = None) -> ConceptRef | None:
    if not d:
        return None
    return ConceptRef(
        code=str(d.get("code")),
        name=d.get("name"),
        terminology=d.get("terminology"),
        release=d.get("version") or release,
        leaf=d.get("leaf"),
        level=d.get("level"),
    )


def refs(items: Iterable[dict[str, Any]] | None, *, release: str | None = None) -> list[ConceptRef]:
    return [r for r in (ref(i, release=release) for i in (items or [])) if r]


def _qualifiers(items: Any) -> list[Qualifier] | None:
    if not items:
        return None
    return [Qualifier(type=str(q.get("type")), value=str(q.get("value"))) for q in items if isinstance(q, dict)]


def edge(d: dict[str, Any], kind: str, *, negative_roles: frozenset[str] = DEFAULT_NEGATIVE_ROLES) -> Edge:
    rel_type = d.get("type")
    incoming = kind in {"inverseRole", "inverseAssociation", "parent"}
    return Edge(
        kind=kind,  # type: ignore[arg-type]
        type=rel_type,
        code=str(d.get("relatedCode") or d.get("code")),
        name=d.get("relatedName") or d.get("name"),
        direction="incoming" if incoming else "outgoing",
        polarity="negative" if rel_type in negative_roles else "positive",
        qualifiers=_qualifiers(d.get("qualifiers")),
        leaf=d.get("leaf"),
    )


def edges(items: Iterable[dict[str, Any]] | None, kind: str) -> list[Edge] | None:
    if items is None:
        return None
    return [edge(i, kind) for i in items]


def map_assertion(d: dict[str, Any]) -> MapAssertion:
    return MapAssertion(
        type=d.get("type"),
        sourceCode=d.get("sourceCode"),
        sourceName=d.get("sourceName"),
        sourceTerminology=d.get("sourceTerminology"),
        targetCode=d.get("targetCode"),
        targetName=d.get("targetName"),
        targetTermType=d.get("targetTermType"),
        targetTerminology=d.get("targetTerminology"),
        targetTerminologyVersion=d.get("targetTerminologyVersion"),
        group=d.get("group"),
        rank=d.get("rank"),
    )


def history_event(d: dict[str, Any]) -> HistoryEvent:
    return HistoryEvent(
        code=str(d.get("code")),
        name=d.get("name"),
        action=d.get("action"),
        date=d.get("date"),
        replacementCode=d.get("replacementCode"),
        replacementName=d.get("replacementName"),
    )


def properties(items: Iterable[dict[str, Any]] | None, *, keep_qualifiers: bool = False) -> list[Property] | None:
    if items is None:
        return None
    out = []
    for p in items:
        out.append(
            Property(
                type=str(p.get("type")),
                value=str(p.get("value")),
                source=p.get("source"),
                qualifiers=p.get("qualifiers") if keep_qualifiers else None,
            )
        )
    return out


# --------------------------------------------------------------------- concept
def concept(d: dict[str, Any], *, terminology: str, release: str | None, source_uri: str | None = None) -> Concept:
    props = d.get("properties")
    semantic_types = [p["value"] for p in (props or []) if p.get("type") == "Semantic_Type" and p.get("value")]
    return Concept(
        code=str(d.get("code")),
        name=d.get("name"),
        terminology=d.get("terminology") or terminology,
        release=d.get("version") or release,
        active=d.get("active"),
        conceptStatus=d.get("conceptStatus"),
        leaf=d.get("leaf"),
        semanticTypes=semantic_types,
        synonyms=[
            Synonym(name=s.get("name", ""), termType=s.get("termType"), source=s.get("source"), code=s.get("code"), subSource=s.get("subSource"))
            for s in d["synonyms"]
        ]
        if "synonyms" in d
        else None,
        definitions=[Definition(definition=x.get("definition", ""), source=x.get("source")) for x in d["definitions"]]
        if "definitions" in d
        else None,
        properties=properties(props),
        parents=refs(d["parents"], release=release) if "parents" in d else None,
        children=refs(d["children"], release=release) if "children" in d else None,
        roles=edges(d.get("roles"), "role"),
        inverseRoles=edges(d.get("inverseRoles"), "inverseRole"),
        associations=edges(d.get("associations"), "association"),
        inverseAssociations=edges(d.get("inverseAssociations"), "inverseAssociation"),
        disjointWith=edges(d.get("disjointWith"), "disjointWith"),
        maps=[map_assertion(m) for m in d["maps"]] if "maps" in d else None,
        history=[history_event(h) for h in d["history"]] if "history" in d else None,
        subsetMemberships=refs(d.get("subsets"), release=release) if "subsets" in d else None,
        sourceUri=source_uri,
    )


def paths(raw: Any, direction: str, *, release: str | None) -> list[Path]:
    """EVS returns paths either as ``[[concept,...],...]`` or ``{"paths":[{"concepts":[...]}]}``."""
    if raw is None:
        return []
    items = raw.get("paths", []) if isinstance(raw, dict) else raw
    out: list[Path] = []
    for p in items:
        concepts = p.get("concepts", []) if isinstance(p, dict) else p
        out.append(Path(direction=direction, concepts=refs(concepts, release=release)))  # type: ignore[arg-type]
    return out


def subset(d: dict[str, Any], *, release: str | None, depth: int = 0, max_depth: int = 3) -> Subset:
    children = d.get("children")
    return Subset(
        code=str(d.get("code")),
        name=d.get("name"),
        terminology=d.get("terminology"),
        release=d.get("version") or release,
        children=[subset(c, release=release, depth=depth + 1, max_depth=max_depth) for c in children]
        if children and depth < max_depth
        else None,
        properties=properties(d.get("properties")) if d.get("properties") else None,
    )


def mapset(d: dict[str, Any], *, gated: set[str]) -> Mapset:
    props = {p.get("type"): p.get("value") for p in d.get("properties", []) if isinstance(p, dict)}
    target = props.get("targetTerminology") or d.get("targetTerminology")
    return Mapset(
        code=str(d.get("code")),
        name=d.get("name"),
        version=d.get("version"),
        sourceTerminology=props.get("sourceTerminology") or d.get("sourceTerminology"),
        targetTerminology=target,
        sourceTerminologyVersion=props.get("sourceTerminologyVersion"),
        targetTerminologyVersion=props.get("targetTerminologyVersion"),
        downloadOnly=_bool(props.get("downloadOnly")),
        licenseRequired=bool(target and target.lower() in gated),
        properties=properties(d.get("properties")) if d.get("properties") else None,
    )


def _bool(v: Any) -> bool | None:
    if v is None:
        return None
    return str(v).lower() == "true"
