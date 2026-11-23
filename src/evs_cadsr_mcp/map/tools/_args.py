"""Argument types shared by the map_* tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ..models import ModelFragment

PublicId = Annotated[str, Field(pattern=r"^[0-9]{1,12}$", description="caDSR public id")]

Code = Annotated[str, Field(pattern=r"^C[1-9][0-9]*$", description="NCIt concept code")]

ReleaseArg = Annotated[str | None, Field(description="NCIt release to pin (e.g. '26.09d'); omit for the active release.")]

FragmentArg = Annotated[ModelFragment, Field(description="Client-supplied model fragment: {format: gdc_json|gdc_yaml|mdf_yaml, content, entity?, property?}.")]
