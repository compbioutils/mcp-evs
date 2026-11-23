"""Compact EVS records (proposal Section 9, "Compact records").

These are the shapes returned inside ``Envelope.result``. They drop redundant URIs and
large qualifier blocks unless requested, and keep field names close to the EVS REST
API so a reader can cross-check against the source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConceptRef(BaseModel):
    code: str
    name: str | None = None
    terminology: str | None = None
    release: str | None = None
    leaf: bool | None = None
    level: int | None = None


class Synonym(BaseModel):
    name: str
    termType: str | None = None
    source: str | None = None
    code: str | None = None
    subSource: str | None = None


class Definition(BaseModel):
    definition: str
    source: str | None = None


class Property(BaseModel):
    type: str
    value: str
    source: str | None = None
    qualifiers: list[dict[str, str]] | None = None


class Qualifier(BaseModel):
    type: str
    value: str


class Edge(BaseModel):
    """One relationship assertion. ``polarity`` is ``negative`` for configured exclusion roles."""

    kind: Literal["parent", "child", "root", "role", "inverseRole", "association", "inverseAssociation", "disjointWith"]
    type: str | None = None  # relationship name, e.g. Disease_Has_Finding
    code: str  # the related concept
    name: str | None = None
    direction: Literal["outgoing", "incoming"] = "outgoing"
    polarity: Literal["positive", "negative"] = "positive"
    qualifiers: list[Qualifier] | None = None
    leaf: bool | None = None


class MapAssertion(BaseModel):
    type: str | None = None
    sourceCode: str | None = None
    sourceName: str | None = None
    sourceTerminology: str | None = None
    targetCode: str | None = None
    targetName: str | None = None
    targetTermType: str | None = None
    targetTerminology: str | None = None
    targetTerminologyVersion: str | None = None
    group: str | None = None
    rank: str | None = None


class HistoryEvent(BaseModel):
    code: str
    name: str | None = None
    action: str | None = None
    date: str | None = None
    replacementCode: str | None = None
    replacementName: str | None = None


class Concept(BaseModel):
    code: str
    name: str | None = None
    terminology: str
    release: str | None = None
    active: bool | None = None
    conceptStatus: str | None = None
    leaf: bool | None = None
    semanticTypes: list[str] = Field(default_factory=list)
    synonyms: list[Synonym] | None = None
    definitions: list[Definition] | None = None
    properties: list[Property] | None = None
    parents: list[ConceptRef] | None = None
    children: list[ConceptRef] | None = None
    roles: list[Edge] | None = None
    inverseRoles: list[Edge] | None = None
    associations: list[Edge] | None = None
    inverseAssociations: list[Edge] | None = None
    disjointWith: list[Edge] | None = None
    maps: list[MapAssertion] | None = None
    mapsWithheld: list[str] | None = Field(default=None, description="Map target terminologies withheld by the license gate (configure ECM_LICENSE_KEY).")
    history: list[HistoryEvent] | None = None
    subsetMemberships: list[ConceptRef] | None = None
    sourceUri: str | None = None


class BatchConcepts(BaseModel):
    concepts: list[Concept]
    missing: list[str] = Field(default_factory=list)


MatchKind = Literal["code", "name", "synonym"]


class Match(BaseModel):
    concept: Concept
    matchKind: MatchKind
    matchedTerm: str | None = None


class SearchHit(BaseModel):
    concept: Concept
    score: float | None = None
    highlight: str | None = None


class Terminology(BaseModel):
    terminology: str
    name: str | None = None
    version: str | None = None
    terminologyVersion: str | None = None
    latest: bool = False
    monthly: bool = False
    weekly: bool = False
    date: str | None = None
    description: str | None = None
    licenseStatus: Literal["open", "display_obligation", "key_required"] = "open"
    licenseText: str | None = None


class Release(BaseModel):
    terminology: str
    version: str
    terminologyVersion: str
    date: str | None = None
    monthly: bool = False
    weekly: bool = False
    latest: bool = False
    live: bool = True
    indexed: bool = False
    active: bool = False


class MetadataBundle(BaseModel):
    terminology: str
    release: str | None
    kinds: dict[str, list[dict]] = Field(default_factory=dict)


class Path(BaseModel):
    direction: Literal["toRoot", "fromRoot", "toAncestor"]
    concepts: list[ConceptRef]


class Subset(BaseModel):
    code: str
    name: str | None = None
    terminology: str | None = None
    release: str | None = None
    children: list[Subset] | None = None
    memberCount: int | None = None
    properties: list[Property] | None = None


class Mapset(BaseModel):
    code: str
    name: str | None = None
    version: str | None = None
    sourceTerminology: str | None = None
    targetTerminology: str | None = None
    sourceTerminologyVersion: str | None = None
    targetTerminologyVersion: str | None = None
    downloadOnly: bool | None = None
    licenseRequired: bool = False
    properties: list[Property] | None = None


class MapsetEntries(BaseModel):
    mapset: Mapset
    total: int | None = None
    entries: list[MapAssertion] = Field(default_factory=list)
    licenseRequired: bool = False


class ConceptMaps(BaseModel):
    code: str
    maps: list[MapAssertion]
    withheld: list[str] = Field(default_factory=list, description="target terminologies withheld by the license gate")


# ------------------------------------------------------------- traversal (6.4)
RelationshipKind = Literal["parents", "children", "roles", "inverseRoles", "associations", "inverseAssociations"]


class Selector(BaseModel):
    """One relationship kind to follow, optionally restricted to named relationships."""

    kind: RelationshipKind
    names: list[str] | None = Field(default=None, description="Role/association names to follow, e.g. ['Disease_Has_Finding']. Ignored for parents/children.")


class TraversalBudget(BaseModel):
    maxDepth: int = Field(default=2, ge=0, le=4)
    maxNodes: int = Field(default=200, ge=1, le=1000)
    maxEdges: int = Field(default=1000, ge=1, le=5000)
    maxRequests: int = Field(default=50, ge=1, le=200, description="Outbound HTTP requests, including retries.")
    perKind: dict[str, int] | None = Field(default=None, description="Optional per-relationship-kind edge caps.")


class TraversalNode(BaseModel):
    code: str
    name: str | None = None
    depth: int
    leaf: bool | None = None
    expanded: bool = Field(description="False when the node was reached but its relationships were not fetched (bound hit, exclusion, or beyond maxDepth).")
    active: bool | None = None


class HopProvenance(BaseModel):
    """Per-hop provenance (proposal 6.4): where this edge was asserted and under which release."""

    depth: int
    relationship: str | None = None
    kind: str
    direction: Literal["outgoing", "incoming"]
    polarity: Literal["positive", "negative"]
    release: str | None = None
    sourceUri: str | None = None
    qualifiers: list[Qualifier] | None = Field(default=None, description="Present when EVS supplied qualifiers; explicitly null otherwise.")
    evidence: Literal["asserted"] = "asserted"


class TraversalEdge(BaseModel):
    source: str
    target: str
    targetName: str | None = None
    kind: str
    type: str | None = None
    direction: Literal["outgoing", "incoming"]
    polarity: Literal["positive", "negative"]
    depth: int
    hop: HopProvenance


class TraversalStats(BaseModel):
    nodes: int
    edges: int
    maxDepthReached: int
    requests: int
    perKind: dict[str, int] = Field(default_factory=dict)


class TraversalResult(BaseModel):
    start: list[str]
    nodes: list[TraversalNode]
    edges: list[TraversalEdge]
    exclusions: list[TraversalEdge] = Field(default_factory=list, description="Negative-polarity edges that were recorded but not expanded.")
    stats: TraversalStats


# -------------------------------------------------------------- sub-tree (T7)
class Criterion(BaseModel):
    """Attribute criterion for sub-tree filtering or concept-set search."""

    kind: Literal["property", "conceptStatus", "semanticType", "term", "role", "association", "associationType", "subset"]
    name: str | None = Field(default=None, description="Property, role or association name (property/role/association/associationType).")
    value: str | None = Field(default=None, description="Property value, concept status, semantic type, search term, or subset code.")
    targetCode: str | None = Field(default=None, description="Target concept for role/association criteria.")
    searchType: str | None = Field(default=None, description="For kind=term: contains | match | startsWith | phrase | AND | OR | fuzzy.")


class TreeNode(BaseModel):
    code: str
    name: str | None = None
    depth: int
    leaf: bool | None = None
    matches: bool | None = Field(default=None, description="Whether the node satisfies the criteria (null when no criteria were given).")
    expanded: bool = True
    children: list[TreeNode] = Field(default_factory=list)


class SubtreeResult(BaseModel):
    root: TreeNode
    criteria: list[Criterion]
    matchCount: int
    nodeCount: int
    stats: TraversalStats


# --------------------------------------------------------- concept sets (T5)
class PlanStep(BaseModel):
    criterion: Criterion
    route: Literal["search", "inverseRoles", "inverseAssociations", "associationsByType", "subsetMembers", "sparql"]
    endpoint: str
    count: int | None = None
    complete: bool = Field(default=True, description="False when the route was paged and the full set was not enumerated.")


class FindConceptsPlan(BaseModel):
    combinator: Literal["AND", "OR"]
    path: Literal["single_route", "search_combined", "enumerate_and_intersect", "enumerate_and_union", "sparql_required"]
    steps: list[PlanStep]
    note: str | None = None


class FindConceptsResult(BaseModel):
    concepts: list[ConceptRef]
    plan: FindConceptsPlan
