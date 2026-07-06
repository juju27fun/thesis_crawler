from __future__ import annotations

from cnrs_job_watcher.schemas import Classification, JobOffer

STRONG_TERMS = {
    "machine learning": "machine learning",
    "deep learning": "deep learning",
    "apprentissage automatique": "apprentissage automatique",
    "intelligence artificielle": "intelligence artificielle",
    "ia générative": "IA générative",
    "modèle génératif": "modèles génératifs",
    "modeles generatifs": "modèles génératifs",
    "réseaux de neurones": "réseaux de neurones",
    "reseaux de neurones": "réseaux de neurones",
    "neural network": "neural network",
    "graph neural": "graph neural network",
    "gnn": "GNN",
    "llm": "LLM",
    "transformer": "transformer",
    "nlp": "NLP",
    "traitement automatique du langage": "TAL",
    "vision artificielle": "vision artificielle",
    "computer vision": "computer vision",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "jax": "JAX",
    "mlops": "MLOps",
    "reinforcement learning": "reinforcement learning",
    "apprentissage par renforcement": "apprentissage par renforcement",
    "modèles de diffusion": "modèles de diffusion",
    "modeles de diffusion": "modèles de diffusion",
    "diffusion model": "diffusion model",
}

ADJACENT_TERMS = {
    "data science": "data science",
    "science des données": "science des données",
    "bioinformatique": "bioinformatique",
    "annotation sémantique": "annotation sémantique",
    "annotation semantique": "annotation sémantique",
    "neurosciences computationnelles": "neurosciences computationnelles",
    "calcul scientifique": "calcul scientifique",
    "big data": "big data",
}

NEGATIVE_TERMS = {
    "gestion administrative",
    "ressources humaines",
    "chef.fe de projets",
    "chef de projets",
    "chargé de communication",
    "charge de communication",
}


def classify_offer(offer: JobOffer) -> Classification:
    text = " ".join(
        value
        for value in [
            offer.title,
            offer.contract_type or "",
            offer.education_level or "",
            offer.description or "",
            offer.skills or "",
            offer.raw_text,
        ]
        if value
    ).lower()

    hard_filter_passed, target_type, accessibility = hard_filter(offer, text)
    strong_hits = [label for term, label in STRONG_TERMS.items() if term in text]
    adjacent_hits = [label for term, label in ADJACENT_TERMS.items() if term in text]
    negative_hits = [term for term in NEGATIVE_TERMS if term in text]

    score = 0.0
    if hard_filter_passed:
        score += 0.25
    score += min(len(strong_hits) * 0.14, 0.56)
    score += min(len(adjacent_hits) * 0.06, 0.18)
    if _is_thesis(offer, text):
        score += 0.08
    if negative_hits:
        score -= 0.25
    score = max(0.0, min(1.0, round(score, 2)))

    generative_hits = [
        "IA générative",
        "modèles génératifs",
        "modèles de diffusion",
        "diffusion model",
        "LLM",
        "transformer",
    ]
    if any(hit in strong_hits for hit in generative_hits):
        domain = "generative_ai"
    elif strong_hits:
        domain = "ml_deep_learning"
    elif adjacent_hits:
        domain = "data_science_adjacent"
    else:
        domain = "not_relevant"

    is_target = hard_filter_passed and score >= 0.35 and domain != "not_relevant"
    reason = _build_reason(strong_hits, adjacent_hits, negative_hits, hard_filter_passed, offer)

    return Classification(
        is_target=is_target,
        target_type=target_type,
        ai_domain=domain,
        relevance_score=score,
        accessibility=accessibility,
        reason=reason,
    )


def apply_classification(offer: JobOffer) -> JobOffer:
    classification = classify_offer(offer)
    return offer.model_copy(
        update={
            "hard_filter_passed": classification.target_type != "not_target",
            "ai_relevance_score": classification.relevance_score,
            "ai_category": classification.ai_domain,
            "ai_reason": classification.reason,
        }
    )


def hard_filter(offer: JobOffer, text: str | None = None) -> tuple[bool, str, str]:
    text = text or " ".join(
        [offer.title, offer.contract_type or "", offer.education_level or ""]
    ).lower()
    contract = (offer.contract_type or "").lower()
    education = (offer.education_level or "").lower()

    if _is_thesis(offer, text):
        accessibility = (
            "bac5_accessible" if "bac+5" in education or "doctorant" in contract else "unclear"
        )
        return True, "thesis_or_bac5_cdd", accessibility

    is_cdd = "cdd" in contract
    is_it = "it" in contract or "ingénieur" in text or "ingenieur" in text
    is_bac5 = "bac+5" in education or "bac +5" in text or "master" in text
    doctorate_required = any(
        term in text for term in ["doctorat requis", "phd required", "post-doctor", "postdoctor"]
    )

    if is_cdd and is_it and is_bac5 and not doctorate_required:
        return True, "bac5_cdd", "bac5_accessible"
    if doctorate_required:
        return False, "not_target", "doctorate_required"
    return False, "not_target", "unclear"


def _is_thesis(offer: JobOffer, text: str) -> bool:
    contract = (offer.contract_type or "").lower()
    thesis_terms = ["thèse", "these", "doctorant", "contrat doctoral", "phd"]
    return any(term in text for term in thesis_terms) or "doctorant" in contract


def _build_reason(
    strong_hits: list[str],
    adjacent_hits: list[str],
    negative_hits: list[str],
    hard_filter_passed: bool,
    offer: JobOffer,
) -> str:
    if negative_hits:
        return f"Signal d'exclusion potentiel ({negative_hits[0]}) malgré quelques mots-clés."
    if strong_hits:
        target = "contrat/niveau compatible" if hard_filter_passed else "contrat/niveau à vérifier"
        return f"{target}; signaux IA/ML détectés: {', '.join(strong_hits[:4])}."
    if adjacent_hits:
        hits = ", ".join(adjacent_hits[:3])
        return f"Offre connexe data/scientifique ({hits}); pertinence IA/ML à vérifier."
    if offer.unavailable:
        return "Offre indisponible sur le portail CNRS."
    return "Aucun signal IA/ML fort détecté."
