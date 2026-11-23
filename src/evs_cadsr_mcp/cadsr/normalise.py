"""ISO 11179 normaliser: expanded NCI API 1.0 payload -> compact records (proposal 7.1).

The expanded ``DataElement`` is parsed once; the CDE, value-domain, DEC and permissible-value
views are all derived from that one parse. Concept arrays keep ``primaryIndicator`` and
``displayOrder``; the concatenated code string (``C25164:C25150``) is derived from
``displayOrder``, never parsed from text. Parsing is tolerant of key casing drift via
:func:`client.pick`.
"""

from __future__ import annotations

from typing import Any

from .client import latest_flag, norm_status, pick, public_id
from .models import (
    AdminItem,
    AlternateName,
    ClassificationScheme,
    ClassificationSchemeItem,
    ConceptAnnotation,
    ConceptualDomain,
    Context,
    CrdcMapEntry,
    DataElement,
    DataElementConcept,
    DataElementSummary,
    Form,
    FormModule,
    FormQuestion,
    FormUsage,
    FormValidValue,
    ObjectClass,
    PermissibleValue,
    PropertyItem,
    ReferenceDocument,
    RepresentationTerm,
    ValueDomain,
    ValueMeaning,
    VersionSummary,
)

QUESTION_TEXT_TYPES = ("Preferred Question Text", "Alternate Question Text")


# ----------------------------------------------------------------- primitives
def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"yes", "y", "true", "1"}


def _admin_fields(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "publicId": public_id(d) or "",
        "version": _version(d),
        "preferredName": pick(d, "preferredName", "PreferredName"),
        "longName": pick(d, "longName", "LongName"),
        "preferredDefinition": pick(d, "preferredDefinition", "PreferredDefinition", "definition"),
        "context": _context_name(pick(d, "context", "Context", "contextName")),
        "workflowStatus": norm_status(pick(d, "workflowStatus", "WorkflowStatus")),
        "registrationStatus": pick(d, "registrationStatus", "RegistrationStatus"),
        "latestVersion": latest_flag(d),
        "dateCreated": pick(d, "dateCreated", "DateCreated"),
        "dateModified": pick(d, "dateModified", "DateModified"),
    }


def _version(d: dict[str, Any]) -> str | None:
    v = pick(d, "version", "Version")
    return None if v is None else str(v)


def _context_name(v: Any) -> str | None:
    if isinstance(v, dict):
        return pick(v, "name", "longName", "contextName")
    return None if v is None else str(v)


def concepts(items: Any) -> list[ConceptAnnotation]:
    out: list[ConceptAnnotation] = []
    for c in items or []:
        if not isinstance(c, dict):
            continue
        code = pick(c, "conceptCode", "ConceptCode", "code")
        if not code:
            continue
        out.append(
            ConceptAnnotation(
                conceptCode=str(code),
                longName=pick(c, "longName", "LongName", "name"),
                definition=pick(c, "definition", "Definition", "preferredDefinition"),
                evsSource=pick(c, "evsSource", "EvsSource", "origin"),
                primaryIndicator=_bool(pick(c, "primaryIndicator", "PrimaryIndicator")),
                displayOrder=_int(pick(c, "displayOrder", "DisplayOrder")),
            )
        )
    return out


def concept_code_string(annotations: list[ConceptAnnotation]) -> str | None:
    """Join codes in displayOrder (missing order sorts last, stable)."""
    if not annotations:
        return None
    ordered = sorted(enumerate(annotations), key=lambda t: (t[1].displayOrder is None, t[1].displayOrder if t[1].displayOrder is not None else 0, t[0]))
    return ":".join(a.conceptCode for _, a in ordered)


def _concept_bearing(cls, d: dict[str, Any] | None):
    if not d:
        return None
    ann = concepts(pick(d, "Concepts", "concepts"))
    return cls(**_admin_fields(d), concepts=ann, conceptCodes=concept_code_string(ann))


# -------------------------------------------------------------------- views
def data_element_concept(d: dict[str, Any] | None) -> DataElementConcept | None:
    if not d:
        return None
    return DataElementConcept(
        **_admin_fields(d),
        objectClass=_concept_bearing(ObjectClass, pick(d, "ObjectClass", "objectClass")),
        property=_concept_bearing(PropertyItem, pick(d, "Property", "property")),
        conceptualDomain=_conceptual_domain(pick(d, "ConceptualDomain", "conceptualDomain")),
    )


def _conceptual_domain(d: dict[str, Any] | None) -> ConceptualDomain | None:
    return ConceptualDomain(**_admin_fields(d)) if d else None


def permissible_values(vd: dict[str, Any] | None) -> list[PermissibleValue]:
    out: list[PermissibleValue] = []
    for i, pv in enumerate(pick(vd, "PermissibleValues", "permissibleValues") or []):
        if not isinstance(pv, dict):
            continue
        vm_raw = pick(pv, "ValueMeaning", "valueMeaning")
        out.append(
            PermissibleValue(
                value=str(pick(pv, "value", "Value", default="")),
                valueDescription=pick(pv, "valueDescription", "ValueDescription"),
                valueMeaning=_concept_bearing(ValueMeaning, vm_raw),
                beginDate=pick(pv, "beginDate", "BeginDate"),
                endDate=pick(pv, "endDate", "EndDate"),
                displayOrder=_int(pick(pv, "displayOrder", "DisplayOrder")) if pick(pv, "displayOrder", "DisplayOrder") is not None else i,
            )
        )
    return out


def value_domain(vd: dict[str, Any] | None, *, include_pvs: bool) -> ValueDomain | None:
    if not vd:
        return None
    pvs = permissible_values(vd)
    return ValueDomain(
        **_admin_fields(vd),
        type=pick(vd, "type", "Type", "valueDomainType"),
        dataType=pick(vd, "dataType", "DataType", "datatype"),
        unitOfMeasure=pick(vd, "unitOfMeasure", "UnitOfMeasure"),
        format=pick(vd, "format", "Format", "displayFormat"),
        minLength=_int(pick(vd, "minLength", "MinLength", "minimumLength")),
        maxLength=_int(pick(vd, "maxLength", "MaxLength", "maximumLength")),
        minValue=_str(pick(vd, "minValue", "MinValue", "minimumValue")),
        maxValue=_str(pick(vd, "maxValue", "MaxValue", "maximumValue")),
        decimalPlace=_int(pick(vd, "decimalPlace", "DecimalPlace")),
        representationTerm=_concept_bearing(RepresentationTerm, pick(vd, "RepresentationTerm", "representationTerm")),
        conceptualDomain=_conceptual_domain(pick(vd, "ConceptualDomain", "conceptualDomain")),
        permissibleValueCount=len(pvs),
        permissibleValues=pvs if include_pvs else None,
    )


def _str(v: Any) -> str | None:
    return None if v is None else str(v)


def alternate_names(items: Any) -> list[AlternateName]:
    return [AlternateName(name=str(pick(a, "name", "Name", "alternateName", default="")), type=pick(a, "type", "Type"), context=_context_name(pick(a, "context", "Context")))
            for a in items or [] if isinstance(a, dict)]


def classification_schemes(items: Any) -> list[ClassificationScheme]:
    out = []
    for cs in items or []:
        if not isinstance(cs, dict):
            continue
        out.append(
            ClassificationScheme(
                publicId=public_id(cs), version=_version(cs), longName=pick(cs, "longName", "LongName"), context=_context_name(pick(cs, "context", "Context")),
                items=[ClassificationSchemeItem(publicId=public_id(i), version=_version(i), longName=pick(i, "longName", "LongName"), type=pick(i, "type", "Type"))
                       for i in (pick(cs, "ClassificationSchemeItems", "classificationSchemeItems") or []) if isinstance(i, dict)],
            )
        )
    return out


def reference_documents(items: Any) -> list[ReferenceDocument]:
    return [ReferenceDocument(name=pick(r, "name", "Name"), type=pick(r, "type", "Type"), text=pick(r, "description", "Description", "text"),
                              url=pick(r, "url", "URL"), context=_context_name(pick(r, "context", "Context")))
            for r in items or [] if isinstance(r, dict)]


def question_text(docs: list[ReferenceDocument]) -> str | None:
    for wanted in QUESTION_TEXT_TYPES:
        for d in docs:
            if d.type == wanted and d.text:
                return d.text
    return None


def data_element(raw: dict[str, Any], *, include: set[str], source_uri: str | None = None) -> DataElement:
    """``include`` ⊂ {valueDomain, permissibleValues, dataElementConcept, alternateNames,
    classificationSchemes, referenceDocuments}; the CDE header is always present."""
    docs = reference_documents(pick(raw, "ReferenceDocuments", "referenceDocuments"))
    return DataElement(
        **_admin_fields(raw),
        origin=pick(raw, "origin", "Origin"),
        dataElementConcept=data_element_concept(pick(raw, "DataElementConcept", "dataElementConcept")) if "dataElementConcept" in include else None,
        valueDomain=value_domain(pick(raw, "ValueDomain", "valueDomain"), include_pvs="permissibleValues" in include) if ("valueDomain" in include or "permissibleValues" in include) else None,
        alternateNames=alternate_names(pick(raw, "AlternateNames", "alternateNames")) if "alternateNames" in include else None,
        classificationSchemes=classification_schemes(pick(raw, "ClassificationSchemes", "classificationSchemes")) if "classificationSchemes" in include else None,
        referenceDocuments=docs if "referenceDocuments" in include else None,
        questionText=question_text(docs),
        sourceUri=source_uri,
    )


def summary(raw: dict[str, Any], *, matched_role: str | None = None, matched_via: str | None = None) -> DataElementSummary:
    return DataElementSummary(**_admin_fields(raw), matchedRole=matched_role, matchedVia=matched_via)  # type: ignore[arg-type]


def version_summary(raw: dict[str, Any]) -> VersionSummary:
    return VersionSummary(publicId=public_id(raw) or "", version=_version(raw), longName=pick(raw, "longName", "LongName"),
                          workflowStatus=norm_status(pick(raw, "workflowStatus", "WorkflowStatus")), latestVersion=latest_flag(raw),
                          dateModified=pick(raw, "dateModified", "DateModified"))


# -------------------------------------------------------------------- forms
def form(raw: dict[str, Any], *, include_modules: bool) -> Form:
    modules_raw = pick(raw, "Modules", "modules") or []
    modules: list[FormModule] = []
    qcount = 0
    for m in modules_raw:
        if not isinstance(m, dict):
            continue
        questions = []
        for q in pick(m, "Questions", "questions") or []:
            if not isinstance(q, dict):
                continue
            de = pick(q, "DataElement", "dataElement")
            questions.append(
                FormQuestion(
                    publicId=public_id(q), version=_version(q),
                    questionText=pick(q, "questionText", "QuestionText", "text"),
                    displayOrder=_int(pick(q, "displayOrder", "DisplayOrder")),
                    dataElement=version_summary(de) if isinstance(de, dict) else None,
                    validValues=[FormValidValue(value=_str(pick(v, "value", "Value")), meaningText=pick(v, "meaningText", "MeaningText", "valueMeaning"),
                                                displayOrder=_int(pick(v, "displayOrder", "DisplayOrder")))
                                 for v in (pick(q, "ValidValues", "validValues") or []) if isinstance(v, dict)],
                )
            )
        qcount += len(questions)
        modules.append(FormModule(publicId=public_id(m), longName=pick(m, "longName", "LongName"), displayOrder=_int(pick(m, "displayOrder", "DisplayOrder")), questions=questions))
    return Form(**_admin_fields(raw), protocol=_context_name(pick(raw, "protocol", "Protocol")), type=pick(raw, "type", "Type"),
                modules=modules if include_modules else None, questionCount=qcount)


def form_usage(raw: dict[str, Any]) -> FormUsage:
    """Legacy DSL ``Question`` rows carry the owning module/form nested under varying keys. [verify]"""
    module = pick(raw, "Module", "module") or {}
    f = pick(raw, "Form", "form") or pick(module, "Form", "form") or {}
    return FormUsage(
        formPublicId=public_id(f) or _str(pick(raw, "formPublicId", "formPublicID")),
        formVersion=_version(f) if f else _str(pick(raw, "formVersion")),
        formLongName=pick(f, "longName", "LongName") or pick(raw, "formLongName"),
        modulePublicId=public_id(module),
        questionText=pick(raw, "questionText", "QuestionText", "longName"),
    )


def context(raw: dict[str, Any]) -> Context:
    return Context(name=str(pick(raw, "name", "Name", "contextName", "longName", default="")), description=pick(raw, "description", "Description"), version=_version(raw))


def crdc_entry(raw: dict[str, Any]) -> CrdcMapEntry:
    de = pick(raw, "DataElement", "dataElement") or raw
    return CrdcMapEntry(dataElementPublicId=public_id(de), dataElementVersion=_version(de), dataElementLongName=pick(de, "longName", "LongName", "cdeLongName"), raw=_bounded(raw))


def _bounded(d: dict[str, Any], limit: int = 40) -> dict[str, Any]:
    return {k: v for k, v in list(d.items())[:limit] if not isinstance(v, (dict, list))}


__all__ = ["data_element", "summary", "version_summary", "form", "form_usage", "context", "crdc_entry", "permissible_values", "value_domain",
           "data_element_concept", "concept_code_string", "AdminItem"]
