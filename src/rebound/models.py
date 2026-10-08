"""Portable data contracts; authority remains with the tool adapter."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolKind(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    RECONCILABLE = "reconcilable"
    OPAQUE = "opaque"


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    key: str = Field(min_length=1, max_length=256)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: str
    status: Literal["committed", "absent", "pending", "unknown"]
    result: dict[str, Any] | None = None
    authoritative: bool = False
    observed_at: float
    valid_until: float
    source: str
    final: bool = False

    @model_validator(mode="after")
    def valid_window(self) -> "Evidence":
        import math

        if not math.isfinite(self.observed_at) or not math.isfinite(self.valid_until):
            raise ValueError("evidence timestamps must be finite")
        if self.valid_until < self.observed_at:
            raise ValueError("valid_until must not precede observed_at")
        return self


class Decision(BaseModel):
    action: Literal["reuse", "retry", "probe", "review", "fail"]
    reason: str
    evidence: Evidence | None = None

