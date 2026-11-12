from pathlib import Path

import pytest

from app.engines.branching import evaluate_conditions, validate_conditions
from app.engines.dependency import ready_by_upstream_success, topological_layers
from app.engines.job_runner import load_fixture, run_fixture_job


def test_ready_by_upstream_success():
    ok, _ = ready_by_upstream_success(["a", "b"], {"a", "b"})
    assert ok
    ok, reason = ready_by_upstream_success(["a", "b"], {"a"})
    assert not ok
    assert "b" in reason


def test_topological_layers():
    jobs = [
        {"name": "a", "depends_on": []},
        {"name": "b", "depends_on": []},
        {"name": "c", "depends_on": ["a", "b"]},
    ]
    layers = topological_layers(jobs)
    assert {j["name"] for j in layers[0]} == {"a", "b"}
    assert [j["name"] for j in layers[1]] == ["c"]


def test_run_fixture(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text(
        '{"watermark_ts":"2026-01-01T00:00:00Z","flags":{"replay":true},'
        '"rows":[{"id":1}]}',
        encoding="utf-8",
    )
    out = run_fixture_job(p)
    assert out["ok"] and out["artifact_rows"] == 1
    assert out["flags"] == {"replay": True}
    assert load_fixture(p)["watermark_ts"].startswith("2026")


def test_rows_threshold_hit_and_miss():
    outputs = {"ingest": {"artifact_rows": 3, "flags": {}}}
    cond = [{"type": "rows", "upstream": "ingest", "op": "gte", "value": 3}]
    met, reason = evaluate_conditions(cond, outputs)
    assert met and reason == "ok"

    cond = [{"type": "rows", "upstream": "ingest", "op": "gte", "value": 5}]
    met, reason = evaluate_conditions(cond, outputs)
    assert not met
    assert "行数条件未命中" in reason and "gte 5" in reason


def test_flag_conditions():
    outputs = {"ingest": {"artifact_rows": 3, "flags": {"needs_retry": True}}}
    hit = [
        {
            "type": "flag",
            "upstream": "ingest",
            "flag": "needs_retry",
            "op": "eq",
            "value": True,
        }
    ]
    assert evaluate_conditions(hit, outputs)[0] is True
    miss = [
        {
            "type": "flag",
            "upstream": "ingest",
            "flag": "needs_retry",
            "op": "eq",
            "value": False,
        }
    ]
    met, reason = evaluate_conditions(miss, outputs)
    assert met is False and "标志条件未命中" in reason

    missing_flag = [
        {
            "type": "flag",
            "upstream": "ingest",
            "flag": "other",
            "op": "eq",
            "value": True,
        }
    ]
    met, reason = evaluate_conditions(missing_flag, outputs)
    assert met is False and "缺少约定标志" in reason


def test_conditions_combined_with_and_and_missing_upstream():
    outputs = {"a": {"artifact_rows": 4, "flags": {"k": True}}}
    both = [
        {"type": "rows", "upstream": "a", "op": "gte", "value": 1},
        {"type": "flag", "upstream": "a", "flag": "k", "op": "eq", "value": True},
    ]
    assert evaluate_conditions(both, outputs)[0] is True

    one_fails = [
        {"type": "rows", "upstream": "a", "op": "gte", "value": 10},
        {"type": "flag", "upstream": "a", "flag": "k", "op": "eq", "value": True},
    ]
    assert evaluate_conditions(one_fails, outputs)[0] is False

    # upstream never produced (failed or itself bypassed): condition cannot pass
    assert evaluate_conditions(both, {})[0] is False


def test_validate_conditions_rejects_bad_specs():
    validate_conditions([], [])  # empty is fine
    good = [
        {"type": "rows", "upstream": "a", "op": "gte", "value": 1},
        {"type": "flag", "upstream": "a", "flag": "x", "op": "eq", "value": True},
    ]
    validate_conditions(good, ["a"])

    with pytest.raises(ValueError):
        validate_conditions(
            [{"type": "rows", "upstream": "a", "op": "bogus", "value": 1}], ["a"]
        )
    with pytest.raises(ValueError):
        validate_conditions(
            [{"type": "rows", "upstream": "a", "op": "gte", "value": "1"}], ["a"]
        )
    with pytest.raises(ValueError):
        validate_conditions(
            [{"type": "flag", "upstream": "a", "flag": "x", "op": "eq", "value": 1}],
            ["a"],
        )
    # referenced upstream must be declared in depends_on (no implicit edges)
    with pytest.raises(ValueError):
        validate_conditions(
            [{"type": "rows", "upstream": "ghost", "op": "gte", "value": 1}], ["a"]
        )
