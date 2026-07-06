from __future__ import annotations

from enum import StrEnum

from cnrs_job_watcher.schemas import JobOffer


class SearchProfile(StrEnum):
    ALL_PUBLIC = "all_public"
    DOCTORANT = "doctorant"
    CDD_BAC5 = "cdd_bac5"
    AI_AUDIT = "ai_audit"


AI_PROFILE_TERMS = {
    "machine learning",
    "deep learning",
    "apprentissage automatique",
    "intelligence artificielle",
    "ia générative",
    "generative",
    "réseaux de neurones",
    "reseaux de neurones",
    "neural network",
    "llm",
    "transformer",
    "nlp",
    "vision artificielle",
    "computer vision",
    "pytorch",
    "tensorflow",
    "jax",
    "mlops",
    "data science",
    "science des données",
    "bioinformatique",
}


def filter_offers_by_profile(
    offers: list[JobOffer],
    profile: SearchProfile,
) -> list[JobOffer]:
    if profile == SearchProfile.ALL_PUBLIC:
        return offers
    if profile == SearchProfile.DOCTORANT:
        return [offer for offer in offers if _is_doctorant_card(offer)]
    if profile == SearchProfile.CDD_BAC5:
        return [offer for offer in offers if _is_cdd_bac5_card(offer)]
    if profile == SearchProfile.AI_AUDIT:
        return [offer for offer in offers if _has_ai_card_signal(offer)]
    return offers


def dedupe_offers(offers: list[JobOffer]) -> list[JobOffer]:
    deduped: dict[str, JobOffer] = {}
    for offer in offers:
        key = offer.reference or str(offer.url)
        deduped[key] = offer
    return list(deduped.values())


def _is_doctorant_card(offer: JobOffer) -> bool:
    contract = (offer.contract_type or "").lower()
    title = offer.title.lower()
    url = str(offer.url).lower()
    return (
        "doctorant" in contract
        or "contrat doctoral" in contract
        or "doctorant" in title
        or "thèse" in title
        or "these" in title
        or "/offres/doctorant/" in url
    )


def _is_cdd_bac5_card(offer: JobOffer) -> bool:
    contract = (offer.contract_type or "").lower()
    education = (offer.education_level or "").lower()
    return "cdd" in contract and ("bac+5" in education or "bac +5" in education)


def _has_ai_card_signal(offer: JobOffer) -> bool:
    text = " ".join(
        [
            offer.title,
            offer.contract_type or "",
            offer.education_level or "",
            offer.raw_text,
        ]
    ).lower()
    return any(term in text for term in AI_PROFILE_TERMS)
