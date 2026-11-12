"""Conditional branching for orchestration.

A downstream job may declare branch conditions over upstream *outputs* (the
detail of a successful attempt):

- ``rows``: compare the upstream job's ``artifact_rows`` against a threshold
- ``flag``: compare a conventional flag inside the upstream fixture summary
  (the ``flags`` map) against an expected value

Conditions are AND-combined. An empty condition list means "always eligible"
once dependency readiness has passed. This is deliberately separate from
dependency edges: ``depends_on`` answers "may this job run at all", while
branch conditions answer "should this job run given what the upstream actually
produced". Mutual-exclusion groups are enforced by the orchestrator, not here.
"""

from __future__ import annotations

from typing import Any

ROWS_OPS = {"gte", "lte", "gt", "lt", "eq", "ne"}
FLAG_OPS = {"eq", "ne"}
CONDITION_TYPES = {"rows", "flag"}


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "gte":
        return left >= right
    if op == "lte":
        return left <= right
    if op == "gt":
        return left > right
    if op == "lt":
        return left < right
    raise ValueError(f"unsupported op: {op}")


def evaluate_conditions(
    conditions: list[dict[str, Any]],
    upstream_outputs: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    """Evaluate branch conditions against outputs of successful jobs.

    ``upstream_outputs`` maps job name to the successful attempt detail
    (``artifact_rows`` / ``flags``). Returns ``(met, reason)``; when not met
    the reason explains the first failing condition and is persisted on the
    ``skipped_branch`` attempt so the bypass cause stays auditable.
    """
    for cond in conditions:
        upstream = cond["upstream"]
        source = upstream_outputs.get(upstream)
        if source is None:
            return False, f"上游 {upstream} 未成功产出，分支条件无法满足"
        ctype = cond["type"]
        if ctype == "rows":
            actual = source.get("artifact_rows", 0)
            expected = cond["value"]
            if not _compare(cond["op"], actual, expected):
                return False, (
                    f"行数条件未命中：{upstream}.artifact_rows={actual}，"
                    f"要求 {cond['op']} {expected}"
                )
        elif ctype == "flag":
            flag_name = cond["flag"]
            flags = source.get("flags") or {}
            if flag_name not in flags:
                return False, (
                    f"标志条件未命中：{upstream}.flags 缺少约定标志 {flag_name}"
                )
            actual = flags[flag_name]
            expected = cond["value"]
            if not _compare(cond["op"], actual, expected):
                return False, (
                    f"标志条件未命中：{upstream}.flags.{flag_name}={actual!r}，"
                    f"要求 {cond['op']} {expected!r}"
                )
        else:  # pragma: no cover - rejected earlier by validation
            return False, f"未知分支条件类型：{ctype}"
    return True, "ok"


def validate_conditions(
    conditions: list[dict[str, Any]], depends_on: list[str]
) -> None:
    """Raise ValueError when a condition spec is ill-formed.

    Referenced upstreams must be declared in ``depends_on`` so a branch can
    never silently observe a job whose readiness was never required.
    """
    for idx, cond in enumerate(conditions):
        where = f"conditions[{idx}]"
        ctype = cond.get("type")
        if ctype not in CONDITION_TYPES:
            raise ValueError(f"{where}.type 必须是 rows 或 flag")
        upstream = cond.get("upstream")
        if not upstream or not isinstance(upstream, str):
            raise ValueError(f"{where}.upstream 不能为空")
        if upstream not in depends_on:
            raise ValueError(
                f"{where}.upstream={upstream} 不在该作业的 depends_on 中"
            )
        op = cond.get("op")
        if ctype == "rows":
            if op not in ROWS_OPS:
                raise ValueError(f"{where}.op 非法：{op}")
            value = cond.get("value")
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{where}.value 行数阈值必须是整数")
        else:
            if not cond.get("flag"):
                raise ValueError(f"{where}.flag 标志名不能为空")
            if op not in FLAG_OPS:
                raise ValueError(f"{where}.op 标志条件仅支持 eq/ne：{op}")
            if not isinstance(cond.get("value"), bool):
                raise ValueError(f"{where}.value 标志比较值必须是布尔值")
