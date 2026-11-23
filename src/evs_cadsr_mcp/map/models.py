"""Mapping-module records (proposal Sections 8.2 and 9)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..cadsr.models import ConceptAnnotation, ConceptRole, DataElementSummary
from ..evs.models import ConceptRef, Edge, TraversalBudget  # noqa: F401 (TraversalBudget re-exported for tools)

ConceptStatusAtRelease = Literal["active", "retired", "not_found", "unresolved"]


class ResolvedConcept(BaseModel):
    """One caDSR concept annotation resolved against NCIt at the pinned release."""

    role: ConceptRole
    conceptCode: str
    cadsrName: str | None = None
    evsSource: str | None = None
    primaryIndicator: bool | None = None
    displayOrder: int | None = None
    ncitName: str | None = None
    conceptStatusAtRelease: ConceptStatusAtRelease
    semanticTypes: list[str] = Field(default_factory=list)
    replacement: ConceptRef | None = Field(default=None, description="Replacement concept when retired/merged, from EVS history.")
    nameAgrees: bool | None = Field(default=None, description="Whether caDSR's long name equals NCIt's preferred name or a synonym.")
    pvValue: str | None = Field(default=None, description="For ValueMeaning annotations: the permissible value they belong to.")


class CdeConceptMap(BaseModel):
    publicId: str
    version: str | None
    longName: str | None
    release: str
    objectClass: list[ResolvedConcept] = Field(default_factory=list)
    property: list[ResolvedConcept] = Field(default_factory=list)
    representationTerm: list[ResolvedConcept] = Field(default_factory=list)
    valueMeanings: list[ResolvedConcept] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict, description="Counts by conceptStatusAtRelease.")


class ConceptGroup(BaseModel):
    concept: ConceptRef
    depth: int = 0
    dataElements: list[DataElementSummary]


class DataElementsForConcept(BaseModel):
    conceptCode: str
    release: str
    expandedDescendants: bool
    groups: list[ConceptGroup]
    totalDataElements: int


class PvExplanation(BaseModel):
    publicId: str
    version: str | None
    value: str
    valueDescription: str | None = None
    valueMeaning: ConceptAnnotation | None = None
    valueMeaningLongName: str | None = None
    concept: ConceptRef | None = None
    conceptStatusAtRelease: ConceptStatusAtRelease
    definition: str | None = None
    definitionSource: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    replacement: ConceptRef | None = None
    release: str


AlignStatus = Literal["exact", "synonym", "retired", "unmapped", "ambiguous"]


class ValueSetSide(BaseModel):
    """One side of an alignment. Exactly one of the selectors must be set."""

    cde: dict[str, str] | None = Field(default=None, description="{publicId, version?}")
    values: list[str] | None = Field(default=None, description="Plain value strings.")
    gdcEnumDef: dict[str, Any] | None = Field(default=None, description="GDC enumDef block: {value: {termDef: {cde_id?, term_id: Cxxxx, source: NCIt, ...}}} or {enum: [...], enumDef: {...}}.")
    mdfEnum: list[Any] | None = Field(default=None, description="MDF Enum list; items may be strings or {Value, Term: [{Origin, Code}]}.")
    ncitSubset: str | None = Field(default=None, description="NCIt subset code, e.g. C177537.")


class ValueAlignment(BaseModel):
    value: str
    conceptCode: str | None = None
    status: AlignStatus
    matchedTo: str | None = Field(default=None, description="The right-side value / PV / member this value aligned to.")
    matchedConcept: str | None = None
    replacement: ConceptRef | None = None
    evidence: list[str] = Field(default_factory=list)


class ValueSetAlignment(BaseModel):
    release: str
    leftCount: int
    rightCount: int
    alignments: list[ValueAlignment]
    unmatchedRight: list[str] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class ModelEnumValue(BaseModel):
    value: str
    conceptCode: str | None = None
    cdeId: str | None = None
    cdeVersion: str | None = None
    source: str | None = None


class ModelProperty(BaseModel):
    """Normalised view of one property from a client-supplied model fragment."""

    model: Literal["gdc", "mdf", "unknown"]
    entity: str | None = None
    name: str
    description: str | None = None
    cdeId: str | None = None
    cdeVersion: str | None = None
    cdeSource: str | None = None
    termConceptCode: str | None = Field(default=None, description="NCIt code given at property level (MDF Term origin NCIt, or GDC termDef term_id).")
    enum: list[ModelEnumValue] = Field(default_factory=list)
    required: bool | None = None
    type: str | None = None


class ModelFragment(BaseModel):
    format: Literal["gdc_json", "gdc_yaml", "mdf_yaml"]
    content: str = Field(description="The fragment text (JSON or YAML). Parsed, never fetched or stored.")
    entity: str | None = Field(default=None, description="Entity/node name to select when the fragment holds several.")
    property: str | None = Field(default=None, description="Property name to select; omit to process all properties.")


class ModelPropertyMapping(BaseModel):
    property: ModelProperty
    release: str
    cde: CdeConceptMap | None = None
    cdeStatus: Literal["resolved", "missing_cde_id", "cde_not_found", "cde_superseded", "skipped"] = "skipped"
    latestCdeVersion: str | None = None
    alignment: ValueSetAlignment | None = None
    notes: list[str] = Field(default_factory=list)


class CdeSuggestion(BaseModel):
    publicId: str
    version: str | None = None
    longName: str | None = None
    score: float
    evidence: list[str]
    backend: str


class Finding(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    property: str | None = None
    value: str | None = None
    message: str
    suggestion: str | None = None


class LintReport(BaseModel):
    release: str
    propertiesChecked: int
    findings: list[Finding]
    summary: dict[str, int] = Field(default_factory=dict)


class Impact(BaseModel):
    conceptCode: str
    conceptName: str | None = None
    change: Literal["retired", "merged", "renamed", "not_in_target", "unchanged"]
    replacement: ConceptRef | None = None
    dataElements: list[DataElementSummary] = Field(default_factory=list)


class ReleaseImpact(BaseModel):
    fromRelease: str
    toRelease: str
    scope: dict[str, Any]
    impacts: list[Impact]
    checked: int


class Crosswalk(BaseModel):
    left: ModelPropertyMapping
    right: ModelPropertyMapping
    basis: Literal["same_cde", "same_cde_different_version", "same_concepts", "partial", "none"]
    sharedConcepts: list[str] = Field(default_factory=list)
    leftOnlyConcepts: list[str] = Field(default_factory=list)
    rightOnlyConcepts: list[str] = Field(default_factory=list)
    enumOverlap: dict[str, int] | None = None


class IcdoMapping(BaseModel):
    icdoCode: str | None = None
    icdoTerm: str | None = Field(default=None, description="ICD-O-3 term for the code, preferring the PT.")
    icdoTermType: str | None = Field(default=None, description="ICD-O term type: PT (preferred), SY (synonym), RT (related), HT (hierarchical), "
                                                               "or the obsolete forms OP, IS, ORT.")
    icdoVersions: list[str] = Field(default_factory=list, description="ICD-O-3 versions the mapping covers (the EVS files are ICD-O-3.1).")
    ncimCui: str | None = Field(default=None, description="NCI Metathesaurus CUI of the ICD-O term.")
    axis: Literal["morphology", "topography", "unknown"]
    concept: ConceptRef
    ncitName: str | None = None
    conceptStatusAtRelease: ConceptStatusAtRelease
    matchedVia: Literal["ICD-O code", "ICD-O term", "NCIt name"]
    group: ConceptRef | None = None
    release: str = Field(description="NCIt release at which conceptStatusAtRelease was checked.")
    mapRelease: str | None = Field(default=None, description="Publication date (YYYY-MM-DD) of the EVS ICD-O-3.1 mapping files the mapping came from.")


class StoredValue(BaseModel):
    conceptCode: str
    commons: str
    storedValue: str | None = None
    propertyHint: str | None = None
    source: Literal["mapset", "crdc_code_map", "cde_pv"]
    detail: dict[str, Any] | None = None


class StoredValues(BaseModel):
    conceptCode: str
    commons: str
    release: str
    values: list[StoredValue]


__all__ = [n for n in dir() if n[:1].isupper()] + ["Edge"]
