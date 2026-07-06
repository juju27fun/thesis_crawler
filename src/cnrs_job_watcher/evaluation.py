from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.schemas import Accessibility, AiCategory, JobOffer, TargetBucket


class EvaluationCase(BaseModel):
    reference: str
    expected_bucket: TargetBucket
    expected_ai_domain: AiCategory
    expected_accessibility: Accessibility
    notes: str | None = None
    offer: JobOffer


class EvaluationResult(BaseModel):
    reference: str
    bucket_ok: bool
    domain_ok: bool
    accessibility_ok: bool
    expected_bucket: TargetBucket
    actual_bucket: TargetBucket
    expected_ai_domain: AiCategory
    actual_ai_domain: AiCategory
    expected_accessibility: Accessibility
    actual_accessibility: Accessibility
    is_false_target: bool
    is_missed_target: bool


class EvaluationSummary(BaseModel):
    total: int
    bucket_accuracy: float
    domain_accuracy: float
    accessibility_accuracy: float
    target_precision: float
    target_recall: float
    false_targets: int
    missed_targets: int
    results: list[EvaluationResult]


def load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [EvaluationCase.model_validate(item) for item in data]


def run_evaluation(cases: list[EvaluationCase]) -> EvaluationSummary:
    results: list[EvaluationResult] = []
    target_buckets = {"primary_target", "secondary_target", "adjacent_review"}
    for case in cases:
        classified = apply_classification(case.offer)
        actual_domain = classified.ai_category or "not_relevant"
        expected_is_target = case.expected_bucket in target_buckets
        actual_is_target = classified.target_bucket in target_buckets
        results.append(
            EvaluationResult(
                reference=case.reference,
                bucket_ok=classified.target_bucket == case.expected_bucket,
                domain_ok=actual_domain == case.expected_ai_domain,
                accessibility_ok=classified.accessibility == case.expected_accessibility,
                expected_bucket=case.expected_bucket,
                actual_bucket=classified.target_bucket,
                expected_ai_domain=case.expected_ai_domain,
                actual_ai_domain=actual_domain,
                expected_accessibility=case.expected_accessibility,
                actual_accessibility=classified.accessibility,
                is_false_target=actual_is_target and not expected_is_target,
                is_missed_target=expected_is_target and not actual_is_target,
            )
        )

    total = len(results)
    expected_targets = sum(case.expected_bucket in target_buckets for case in cases)
    actual_targets = sum(result.actual_bucket in target_buckets for result in results)
    true_targets = sum(
        result.actual_bucket in target_buckets and result.expected_bucket in target_buckets
        for result in results
    )
    return EvaluationSummary(
        total=total,
        bucket_accuracy=_ratio(sum(result.bucket_ok for result in results), total),
        domain_accuracy=_ratio(sum(result.domain_ok for result in results), total),
        accessibility_accuracy=_ratio(
            sum(result.accessibility_ok for result in results),
            total,
        ),
        target_precision=_ratio(true_targets, actual_targets),
        target_recall=_ratio(true_targets, expected_targets),
        false_targets=sum(result.is_false_target for result in results),
        missed_targets=sum(result.is_missed_target for result in results),
        results=results,
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 3)
