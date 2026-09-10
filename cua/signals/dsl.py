"""A tiny typed predicate language over an ``Observation``.

One abstraction, reused everywhere a "did we reach the expected state?" question
comes up: step pre/post-conditions, the overall success checkpoint, the
``detect`` clause of a known business outcome, and the ``detect`` clause of a
recoverable condition. Keeping it to one evaluator keeps the replay engine
uniform and the artifact small.

All string matching is regex, case-insensitive, ``re.search`` semantics.
"""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class UrlMatches(BaseModel):
    kind: Literal["url_matches"] = "url_matches"
    pattern: str


class TextMatches(BaseModel):
    kind: Literal["text_matches"] = "text_matches"
    pattern: str


class AxPresent(BaseModel):
    kind: Literal["ax_present"] = "ax_present"
    role: str
    name_matches: Optional[str] = None


class AxAbsent(BaseModel):
    kind: Literal["ax_absent"] = "ax_absent"
    role: str
    name_matches: Optional[str] = None


class DialogOpen(BaseModel):
    kind: Literal["dialog_open"] = "dialog_open"
    expected: bool = True


class HttpStatus(BaseModel):
    kind: Literal["http_status"] = "http_status"
    lt: Optional[int] = None
    gte: Optional[int] = None
    eq: Optional[int] = None


class AllOf(BaseModel):
    kind: Literal["all_of"] = "all_of"
    of: List["Signal"]


class AnyOf(BaseModel):
    kind: Literal["any_of"] = "any_of"
    of: List["Signal"]


class Not(BaseModel):
    kind: Literal["not"] = "not"
    of: "Signal"


Signal = Annotated[
    Union[UrlMatches, TextMatches, AxPresent, AxAbsent, DialogOpen, HttpStatus,
          AllOf, AnyOf, Not],
    Field(discriminator="kind"),
]

for _m in (AllOf, AnyOf, Not):
    _m.model_rebuild()
