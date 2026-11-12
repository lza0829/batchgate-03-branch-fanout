from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MaxAttemptsBody(BaseModel):
    max_attempts: int = Field(ge=1, le=10)


class BranchCondition(BaseModel):
    type: Literal["rows", "flag"]
    upstream: str = Field(min_length=1)
    op: str
    value: Any
    flag: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "BranchCondition":
        if self.type == "rows":
            if self.op not in {"gte", "lte", "gt", "lt", "eq", "ne"}:
                raise ValueError(f"rows 条件 op 非法：{self.op}")
            if not isinstance(self.value, int) or isinstance(self.value, bool):
                raise ValueError("rows 条件 value 必须是整数阈值")
        else:
            if not self.flag:
                raise ValueError("flag 条件必须给出 flag 名称")
            if self.op not in {"eq", "ne"}:
                raise ValueError("flag 条件仅支持 eq/ne")
            if not isinstance(self.value, bool):
                raise ValueError("flag 条件 value 必须是布尔值")
        return self


class BranchConfigBody(BaseModel):
    branch_conditions: list[BranchCondition] = Field(default_factory=list)
    mutex_group: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _normalize_group(self) -> "BranchConfigBody":
        if self.mutex_group is not None and not self.mutex_group.strip():
            self.mutex_group = None
        return self
