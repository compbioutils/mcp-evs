"""Argument types shared by the cadsr_* tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

PublicId = Annotated[str, Field(pattern=r"^[0-9]{1,12}$", description="caDSR public id, e.g. 2192199")]

VERSION_PATTERN = r"^[0-9]{1,4}(\.[0-9]{1,4})?$"

VersionArg = Annotated[str | None, Field(pattern=VERSION_PATTERN, description="caDSR version such as '1.0' or '3.0'. Omit for the latest version.")]


class DataElementId(BaseModel):
    publicId: str = Field(pattern=r"^[0-9]{1,12}$")
    version: str | None = None
