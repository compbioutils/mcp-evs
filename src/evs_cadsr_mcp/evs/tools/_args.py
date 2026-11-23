"""Argument types shared by the evs_* tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

CODE_PATTERN = r"^C[1-9][0-9]*$"

Code = Annotated[str, Field(pattern=CODE_PATTERN, description="NCIt concept code, e.g. C3224")]

ReleaseArg = Annotated[
    str | None,
    Field(description="NCIt release such as '26.09d'. Omit for the server's active release. Only live releases are accepted."),
]

TerminologyArg = Annotated[str, Field(description="EVS terminology id; default 'ncit'.")]

IncludeArg = Annotated[
    list[str] | None,
    Field(description="EVS include flags: minimal | summary | full, or itemised flags such as children, parents, roles, "
                      "inverseRoles, associations, inverseAssociations, maps, history, disjointWith, subsetLink. Default summary."),
]
