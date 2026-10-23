"""Sample-only evidence and capability routing at the pipeline boundary."""
from dataclasses import fields
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from redqueen.baseline import BaselineDetector
from redqueen.config import Settings
from redqueen.failure_analysis import build_evidence
from redqueen.pipeline import PipelineResult, SimulationBoundary
from redqueen.schemas import ALLOWED_FIELDS, Clause, DefenseRule, Evidence
from redqueen.simulator import DEFAULT_DEMO_SPEC, generate_datasets, generate_legit_background


@pytest.fixture
def sample():
    return generate_datasets(DEFAULT_DEMO_SPEC, 1337, Settings())["sample"]


def test_evidence_is_deterministic_sample_only_and_contains_permitted_features(sample):
    flags = BaselineDetector().predict(sample)
    before = sample.copy(deep=True)
    a = build_evidence(sample, flags, Settings())
    b = build_evidence(sample, flags, Settings())
    assert a == b
    assert len(a.missed_fraud) == 25
    assert len(a.lookalike_legit) == 25
    assert set(a.permitted_fields) == set(ALLOWED_FIELDS)
    for row in a.missed_fraud + a.lookalike_legit:
        assert set(row) == set(ALLOWED_FIELDS)
        assert not set(row).intersection({"txn_id", "split", "is_fraud", "attack_name"})
    target_misses = sample[
        sample.is_fraud.eq(1) & sample.attack_name.eq(DEFAULT_DEMO_SPEC.name) & ~flags]
    assert a.missed_fraud == target_misses[list(ALLOWED_FIELDS)].head(25).to_dict("records")
    stats = a.summary_stats
    assert stats["n_missed_target"] == len(target_misses)
    assert stats["n_fraud"] == sample.is_fraud.sum()
    assert stats["baseline_recall"] == pytest.approx(
        flags[sample.is_fraud.eq(1)].mean())
    for name, spec in ALLOWED_FIELDS.items():
        if spec.dtype != "str":
            expected = pd.DataFrame(a.missed_fraud)[name].quantile(0.5)
            assert stats["quantiles"]["missed_fraud"][name]["0.5"] == expected
    assert '"txn_id"' not in a.model_dump_json()
    assert_frame_equal(sample, before)


@pytest.mark.parametrize("split", ["validation", "sealed", "mixed", "missing", None])
def test_non_sample_evidence_rejected(sample, split):
    frame = sample.copy()
    if split == "missing":
        frame = frame.drop(columns="split")
    elif split == "mixed":
        frame.loc[frame.index[-1], "split"] = "sealed"
    else:
        frame["split"] = split
    with pytest.raises(ValueError, match="sample-only"):
        build_evidence(frame, pd.Series(False, index=frame.index), Settings())


def test_misaligned_flags_rejected(sample):
    with pytest.raises(ValueError):
        build_evidence(sample, pd.Series(False, index=sample.index[::-1]), Settings())


@pytest.mark.parametrize("case", ["no_misses", "no_fraud", "empty", "all_fraud", "generic_only"])
def test_evidence_empty_cohorts(sample, case):
    frame = sample.copy()
    if case == "no_fraud":
        frame = frame[frame.is_fraud.eq(0)]
    elif case == "empty":
        frame = frame.iloc[:0]
    elif case == "all_fraud":
        frame = frame[frame.is_fraud.eq(1)]
    elif case == "generic_only":
        frame = frame[frame.attack_name.eq("background")]
    flags = pd.Series(case == "no_misses", index=frame.index, dtype=bool)
    result = build_evidence(frame, flags, Settings())
    if case == "all_fraud":
        assert result.missed_fraud
        assert result.lookalike_legit == []
    else:
        assert result.missed_fraud == []
        assert result.lookalike_legit == []
    if case in ("empty", "no_fraud", "generic_only"):
        assert result.summary_stats["baseline_target_recall"] == 0.0


def test_multiple_attack_names_cannot_ambiguously_select_target(sample):
    frame = sample.copy()
    position = frame.index[frame.attack_name.eq(DEFAULT_DEMO_SPEC.name)][0]
    frame.loc[position, "attack_name"] = "another_target"
    with pytest.raises(ValueError, match="one named target"):
        build_evidence(frame, pd.Series(False, index=frame.index), Settings())


def test_nearest_neighbours_by_hand_stable_ties_and_generic_exclusion():
    frame = generate_legit_background(6, 42)
    # Hold every feature constant except amount; sample-range normalisation
    # makes the two $101 legitimate rows equally close to the $100 miss.
    for field in ALLOWED_FIELDS:
        frame[field] = frame[field].iloc[0]
    frame["amount"] = [100.0, 101.0, 99.0, 101.0, 1000.0, 40.0]
    frame["is_fraud"] = [1, 0, 0, 0, 0, 1]
    frame["attack_name"] = ["target", "none", "none", "none", "none", "background"]
    frame["split"] = "sample"
    evidence = build_evidence(frame, pd.Series(False, index=frame.index), Settings())
    assert len(evidence.missed_fraud) == 1  # generic miss never enters evidence
    assert [row["amount"] for row in evidence.lookalike_legit] == [101.0, 99.0, 101.0, 1000.0]


class UnreadableHeldout:
    """Fail if anything beyond opaque routing touches this held-out object."""
    def __getattr__(self, name):
        raise AssertionError(f"Held-out contents were accessed: {name}")


def test_pipeline_evidence_cannot_read_heldout_even_when_split_labels_are_spoofed(monkeypatch):
    import redqueen.pipeline as pipeline

    sample = generate_datasets(DEFAULT_DEMO_SPEC, 91, Settings(n_sample=400))["sample"]
    # A split label is not trusted to determine which frame is evidence.
    heldout = sample.copy()
    heldout["split"] = "sample"
    heldout["amount"] = 49_999.0
    monkeypatch.setattr(pipeline, "generate_datasets", lambda *args: {
        "sample": sample, "validation": heldout, "sealed": UnreadableHeldout(),
    })
    boundary = SimulationBoundary(DEFAULT_DEMO_SPEC, 91, Settings(n_sample=400))
    result = boundary.build_sample_evidence(BaselineDetector())
    assert all(row["amount"] != 49_999.0
               for row in result.missed_fraud + result.lookalike_legit)
    assert boundary.metadata == {"sample": 400, "validation": 5000, "sealed": 10_000}
    changed = boundary.metadata
    changed["sample"] = -1
    assert boundary.metadata["sample"] == 400
    assert not hasattr(boundary, "datasets")
    assert not hasattr(boundary, "sealed")
    assert not hasattr(boundary, "validation")


def test_pipeline_routes_each_heldout_only_to_its_gate_method(monkeypatch):
    import redqueen.pipeline as pipeline

    sample, validation, sealed = object(), UnreadableHeldout(), UnreadableHeldout()
    monkeypatch.setattr(pipeline, "generate_datasets", lambda *args: {
        "sample": sample, "validation": validation, "sealed": sealed,
    })
    boundary = SimulationBoundary(DEFAULT_DEMO_SPEC, 1, Settings())
    received = []
    validation_result, final_result = object(), object()

    class Gate:
        def evaluate_validation(self, rule, datasets, baseline):
            assert set(datasets) == {"validation"}
            assert datasets["validation"] is validation
            received.append("validation")
            return validation_result

        def evaluate_final(self, rule, datasets, baseline, approved_attacks):
            assert set(datasets) == {"sealed"}
            assert datasets["sealed"] is sealed
            assert approved_attacks == [DEFAULT_DEMO_SPEC.name]
            received.append("sealed")
            return final_result

    baseline = BaselineDetector()
    rule = DefenseRule(clauses=[Clause(field="amount", op=">", val=100)],
                       action="FLAG", rationale="")
    assert boundary.evaluate_validation(Gate(), rule, baseline) is validation_result
    assert received == ["validation"]
    assert boundary.evaluate_final(Gate(), rule, baseline, [DEFAULT_DEMO_SPEC.name]) is final_result
    assert received == ["validation", "sealed"]


def pipeline_result(evidence, metadata):
    # Other fields are not involved in this dataclass boundary check.
    return PipelineResult(spec=DEFAULT_DEMO_SPEC, rule=None, report=None,
                          telemetry=None, evidence=evidence, dataset_metadata=metadata)


def test_pipeline_result_remains_metadata_and_sample_evidence_only(sample):
    evidence = build_evidence(sample, BaselineDetector().predict(sample), Settings())
    result = pipeline_result(evidence, {"sample": {"rows": len(sample)}})
    assert not any(isinstance(getattr(result, f.name), pd.DataFrame) for f in fields(result))


@pytest.mark.parametrize("metadata", [
    {"sealed": pd.DataFrame({"amount": [1]})},
    {"nested": {"rows": [1, 2, 3]}}, {"raw": {"amount": 450.0}},
    {"rows": -1}, {"rows": True},
])
def test_pipeline_result_rejects_raw_or_non_count_metadata(metadata):
    evidence = Evidence(missed_fraud=[], lookalike_legit=[], permitted_fields=[], summary_stats={})
    with pytest.raises(ValueError, match="metadata"):
        pipeline_result(evidence, metadata)


@pytest.mark.parametrize("row,permitted", [
    ({"split": "sample"}, ["split"]),
    ({"txn_id": "T0"}, list(ALLOWED_FIELDS)),
    ({"amount": pd.DataFrame({"x": [1]})}, ["amount"]),
])
def test_pipeline_result_rejects_forbidden_or_non_scalar_evidence(row, permitted):
    evidence = Evidence(missed_fraud=[row], lookalike_legit=[],
                        permitted_fields=permitted, summary_stats={})
    with pytest.raises(ValueError, match="Evidence"):
        pipeline_result(evidence, {})


def test_later_phase_orchestration_remains_stub():
    from redqueen.pipeline import run_redqueen
    with pytest.raises(NotImplementedError, match="Phase 5"):
        run_redqueen("scenario", Settings())
