from __future__ import annotations

import json
import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from cnrs_job_watcher.classify import apply_classification, classify_offer
from cnrs_job_watcher.schemas import Accessibility, AiCategory, JobOffer, TargetBucket

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class LlmProvider(Protocol):
    def classify(self, offer: JobOffer, schema: dict[str, object]) -> Mapping[str, object]:
        """Return raw JSON-like classification data for an offer."""


class ClassifierMode(StrEnum):
    RULES = "rules"
    LLM = "llm"
    HYBRID = "hybrid"


class StaticLlmProvider:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload

    def classify(self, offer: JobOffer, schema: dict[str, object]) -> Mapping[str, object]:
        return self.payload


class LlmClassificationResult(BaseModel):
    is_target: bool
    target_bucket: TargetBucket
    ai_domain: AiCategory
    accessibility: Accessibility
    relevance_score: float = Field(ge=0, le=1)
    short_summary: str
    reason: str
    risk_flags: list[str] = Field(default_factory=list)


class OpenAIResponsesProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def classify(self, offer: JobOffer, schema: dict[str, object]) -> Mapping[str, object]:
        response = httpx.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": _build_prompt(offer),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "cnrs_offer_classification",
                        "strict": True,
                        "schema": schema,
                    }
                },
                "store": False,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        output_text = payload.get("output_text")
        if not isinstance(output_text, str):
            output_text = _extract_output_text(payload)
        return json.loads(output_text)


def classify_offer_hybrid(
    offer: JobOffer,
    provider: LlmProvider | None = None,
) -> JobOffer:
    rules_classification = classify_offer(offer)
    rules_offer = apply_classification(offer)
    should_call = _should_call_llm(
        rules_classification.ai_domain,
        rules_classification.target_type,
    )
    if provider is None or not should_call:
        return rules_offer

    try:
        llm_result = LlmClassificationResult.model_validate(
            provider.classify(offer, classification_json_schema())
        )
    except (ValidationError, ValueError, TypeError, httpx.HTTPError):
        flags = sorted({*rules_offer.risk_flags, "llm_invalid_response"})
        return rules_offer.model_copy(
            update={
                "target_bucket": (
                    "adjacent_review" if rules_offer.is_target else rules_offer.target_bucket
                ),
                "risk_flags": flags,
                "ai_reason": "Réponse LLM invalide; décision règles conservée pour revue.",
            }
        )

    return rules_offer.model_copy(
        update={
            "is_target": llm_result.is_target,
            "target_bucket": llm_result.target_bucket,
            "accessibility": llm_result.accessibility,
            "ai_relevance_score": llm_result.relevance_score,
            "ai_category": llm_result.ai_domain,
            "ai_reason": llm_result.reason,
            "short_summary": llm_result.short_summary,
            "risk_flags": llm_result.risk_flags,
            "classifier_version": "hybrid-llm-v1",
        }
    )


def provider_from_env() -> OpenAIResponsesProvider | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAIResponsesProvider(
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
    )


def classification_json_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "is_target",
            "target_bucket",
            "ai_domain",
            "accessibility",
            "relevance_score",
            "short_summary",
            "reason",
            "risk_flags",
        ],
        "properties": {
            "is_target": {"type": "boolean"},
            "target_bucket": {
                "type": "string",
                "enum": ["primary_target", "secondary_target", "adjacent_review", "exclude"],
            },
            "ai_domain": {
                "type": "string",
                "enum": [
                    "ml_deep_learning",
                    "generative_ai",
                    "general_ai",
                    "data_science_adjacent",
                    "not_relevant",
                ],
            },
            "accessibility": {
                "type": "string",
                "enum": ["bac5_accessible", "doctorate_required", "unclear", "not_accessible"],
            },
            "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
            "short_summary": {"type": "string"},
            "reason": {"type": "string"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
        },
    }


def _should_call_llm(ai_domain: AiCategory, target_type: str) -> bool:
    return target_type != "not_target" or ai_domain != "not_relevant"


def _build_prompt(offer: JobOffer) -> str:
    fields = {
        "title": offer.title,
        "contract_type": offer.contract_type,
        "duration": offer.duration,
        "education_level": offer.education_level,
        "experience_level": offer.experience_level,
        "location": offer.location,
        "lab": offer.lab,
        "description": offer.description,
        "skills": offer.skills,
        "raw_text_excerpt": offer.raw_text[:4000],
    }
    return (
        "Classifie cette offre publique CNRS pour une veille IA/ML BAC+5. "
        "Ne déduis jamais l'existence d'une offre hors des champs fournis. "
        "Exclus les postdocs et offres à doctorat requis. "
        "Réponds uniquement avec le JSON strict demandé.\n\n"
        f"{json.dumps(fields, ensure_ascii=False)}"
    )


def _extract_output_text(payload: Mapping[str, object]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise ValueError("Responses payload does not contain output text")
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    if not chunks:
        raise ValueError("Responses payload does not contain output text")
    return "".join(chunks)
