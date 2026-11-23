"""Compact caDSR records (proposal Section 9 'Compact records', Section 7.1 normaliser).

ISO/IEC 11179 structure: a DataElement (CDE) = DataElementConcept (ObjectClass + Property)
+ ValueDomain (RepresentationTerm, datatype, and for enumerated domains PermissibleValues
each pointing at a ValueMeaning). NCIt codes appear as ``Concepts[]`` on the object class,
property, representation term and each value meaning; these are kept as
:class:`ConceptAnnotation` lists with ``primaryIndicator`` and ``displayOrder``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConceptRole = Literal["ObjectClass", "Property", "RepresentationTerm", "ValueMeaning"]


class ConceptAnnotation(BaseModel):
    conceptCode: str
    longName: str | None = None
    definition: str | None = None
    evsSource: str | None = Field(default=None, description="NCI_CONCEPT_CODE for NCIt; may also be CTCAE_CODE, RADLEX_CODE, NCI_META_CUI, UMLS_CUI, LOINC_CODE.")
    primaryIndicator: bool | None = None
    displayOrder: int | None = None


class AdminItem(BaseModel):
    """Fields shared by every caDSR administered item."""

    publicId: str
    version: str | None = None
    preferredName: str | None = None
    longName: str | None = None
    preferredDefinition: str | None = None
    context: str | None = None
    workflowStatus: str | None = None
    registrationStatus: str | None = None
    latestVersion: bool | None = None
    dateCreated: str | None = None
    dateModified: str | None = None


class ConceptBearing(AdminItem):
    concepts: list[ConceptAnnotation] = Field(default_factory=list)
    conceptCodes: str | None = Field(default=None, description="Concatenated codes in displayOrder, e.g. 'C25164:C25150'. Derived, never parsed from text.")


class ObjectClass(ConceptBearing):
    pass


class PropertyItem(ConceptBearing):
    pass


class RepresentationTerm(ConceptBearing):
    pass


class ConceptualDomain(AdminItem):
    pass


class DataElementConcept(AdminItem):
    objectClass: ObjectClass | None = None
    property: PropertyItem | None = None
    conceptualDomain: ConceptualDomain | None = None


class ValueMeaning(ConceptBearing):
    pass


class PermissibleValue(BaseModel):
    value: str
    valueDescription: str | None = None
    valueMeaning: ValueMeaning | None = None
    beginDate: str | None = None
    endDate: str | None = None
    displayOrder: int | None = None


class ValueDomain(AdminItem):
    type: str | None = Field(default=None, description="Enumerated | NonEnumerated")
    dataType: str | None = None
    unitOfMeasure: str | None = None
    format: str | None = None
    minLength: int | None = None
    maxLength: int | None = None
    minValue: str | None = None
    maxValue: str | None = None
    decimalPlace: int | None = None
    representationTerm: RepresentationTerm | None = None
    conceptualDomain: ConceptualDomain | None = None
    permissibleValueCount: int | None = None
    permissibleValues: list[PermissibleValue] | None = Field(default=None, description="Present only when requested; use cadsr_get_permissible_values for paging.")


class AlternateName(BaseModel):
    name: str
    type: str | None = None
    context: str | None = None


class ClassificationSchemeItem(BaseModel):
    publicId: str | None = None
    version: str | None = None
    longName: str | None = None
    type: str | None = None


class ClassificationScheme(BaseModel):
    publicId: str | None = None
    version: str | None = None
    longName: str | None = None
    context: str | None = None
    items: list[ClassificationSchemeItem] = Field(default_factory=list)


class ReferenceDocument(BaseModel):
    name: str | None = None
    type: str | None = None
    text: str | None = None
    url: str | None = None
    context: str | None = None


class DataElement(AdminItem):
    origin: str | None = None
    dataElementConcept: DataElementConcept | None = None
    valueDomain: ValueDomain | None = None
    alternateNames: list[AlternateName] | None = None
    classificationSchemes: list[ClassificationScheme] | None = None
    referenceDocuments: list[ReferenceDocument] | None = None
    questionText: str | None = Field(default=None, description="Preferred question text from reference documents, when present.")
    sourceUri: str | None = None


class DataElementSummary(AdminItem):
    matchedRole: ConceptRole | None = None
    matchedVia: str | None = None


class VersionSummary(BaseModel):
    publicId: str
    version: str | None = None
    longName: str | None = None
    workflowStatus: str | None = None
    latestVersion: bool | None = None
    dateModified: str | None = None


class BatchDataElements(BaseModel):
    dataElements: list[DataElement]
    missing: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    """Which fan-out routes ran (proposal 7.1: 'never claims full-text search')."""

    routesRun: list[str]
    routesSkipped: list[str] = Field(default_factory=list)
    capped: list[str] = Field(default_factory=list, description="Routes whose result was cut at the per-route cap.")
    note: str = "caDSR has no keyword search; this is a declared fan-out over named lookups and is not exhaustive."


class FindDataElementsResult(BaseModel):
    dataElements: list[DataElementSummary]
    coverage: Coverage


class FormValidValue(BaseModel):
    value: str | None = None
    meaningText: str | None = None
    displayOrder: int | None = None


class FormQuestion(BaseModel):
    publicId: str | None = None
    version: str | None = None
    questionText: str | None = None
    displayOrder: int | None = None
    dataElement: VersionSummary | None = None
    validValues: list[FormValidValue] = Field(default_factory=list)


class FormModule(BaseModel):
    publicId: str | None = None
    longName: str | None = None
    displayOrder: int | None = None
    questions: list[FormQuestion] = Field(default_factory=list)


class Form(AdminItem):
    protocol: str | None = None
    type: str | None = None
    modules: list[FormModule] | None = None
    questionCount: int | None = None


class FormUsage(BaseModel):
    formPublicId: str | None = None
    formVersion: str | None = None
    formLongName: str | None = None
    modulePublicId: str | None = None
    questionText: str | None = None


class Context(BaseModel):
    name: str
    description: str | None = None
    version: str | None = None


class MatchEntity(BaseModel):
    name: str = Field(description="Column heading / question / variable name to match.")
    userTip: str | None = Field(default=None, description="Description or hint, if available.")
    permissibleValues: list[str] | None = None


class MatchResult(BaseModel):
    backend: Literal["cde_match", "ai_engine"]
    entity: str
    publicId: str | None = None
    version: str | None = None
    longName: str | None = None
    score: float | None = None
    matchedField: str | None = None
    pvAnalysis: dict | None = None
    raw: dict | None = Field(default=None, description="Backend-specific fields not covered above (bounded).")


class MatchBackend(BaseModel):
    name: Literal["cde_match", "ai_engine", "vm_match"]
    available: bool
    reason: str | None = None
    variants: list[str] | None = None


class ValueMatch(BaseModel):
    value: str
    candidates: list[dict] = Field(default_factory=list)


class CrdcMapEntry(BaseModel):
    dataElementPublicId: str | None = None
    dataElementVersion: str | None = None
    dataElementLongName: str | None = None
    raw: dict | None = None


class RegistryStatus(BaseModel):
    published: bool = False
    exportDate: str | None = None
    note: str = "caDSR publishes no release identity; items are pinned by publicId + version + retrievedAt."
