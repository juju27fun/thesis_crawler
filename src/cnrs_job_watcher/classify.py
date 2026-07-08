from __future__ import annotations

from datetime import UTC, datetime

from cnrs_job_watcher.schemas import Accessibility, Classification, JobOffer, TargetBucket

CLASSIFIER_VERSION = "rules-v2"

STRONG_TERMS = {
    "machine learning": "machine learning",
    "deep learning": "deep learning",
    "apprentissage automatique": "apprentissage automatique",
    "intelligence artificielle": "intelligence artificielle",
    "intelligence artificielle générative": "IA générative",
    "intelligence artificielle generative": "IA générative",
    "ia générative": "IA générative",
    "modèle génératif": "modèles génératifs",
    "modèles génératifs": "modèles génératifs",
    "modeles generatifs": "modèles génératifs",
    "modèles probabilistes et génératifs": "modèles génératifs",
    "modeles probabilistes et generatifs": "modèles génératifs",
    "variational autoencoder": "modèles génératifs",
    "variational autoencoders": "modèles génératifs",
    "vae": "modèles génératifs",
    "réseaux de neurones": "réseaux de neurones",
    "reseaux de neurones": "réseaux de neurones",
    "neural network": "neural network",
    "graph neural": "graph neural network",
    "graph neural network": "graph neural network",
    "graph neural networks": "graph neural network",
    "geometric deep learning": "geometric deep learning",
    "gnn": "GNN",
    "llm": "LLM",
    "grands modèles de langage": "LLM",
    "grands modeles de langage": "LLM",
    "modèles de langage": "LLM",
    "modeles de langage": "LLM",
    "transformer": "transformer",
    "nlp": "NLP",
    "traitement automatique du langage": "TAL",
    "taln": "TAL",
    "vision artificielle": "vision artificielle",
    "vision par ordinateur": "vision par ordinateur",
    "computer vision": "computer vision",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "jax": "JAX",
    "mlops": "MLOps",
    "reinforcement learning": "reinforcement learning",
    "apprentissage par renforcement": "apprentissage par renforcement",
    "modèle prédictif": "modèle prédictif",
    "modele predictif": "modèle prédictif",
    "modèles prédictifs": "modèles prédictifs",
    "modeles predictifs": "modèles prédictifs",
    "optimisation bayésienne": "optimisation bayésienne",
    "optimisation bayesienne": "optimisation bayésienne",
    "détection d'anomalies": "détection d'anomalies",
    "detection d'anomalies": "détection d'anomalies",
    "détection anomalie": "détection d'anomalies",
    "detection anomalie": "détection d'anomalies",
    "modèles de diffusion": "modèles de diffusion",
    "modeles de diffusion": "modèles de diffusion",
    "diffusion model": "diffusion model",
    "foundation model": "foundation model",
    "foundation models": "foundation model",
    "modèle de fondation": "foundation model",
    "modele de fondation": "foundation model",
    "modèles de fondation": "foundation model",
    "modeles de fondation": "foundation model",
    "apprentissage auto-supervisé": "apprentissage auto-supervisé",
    "apprentissage auto-supervise": "apprentissage auto-supervisé",
    "self-supervised learning": "self-supervised learning",
    "embedding": "embedding",
    "embeddings": "embedding",
    "représentation latente": "représentation latente",
    "representation latente": "représentation latente",
    "représentations latentes": "représentation latente",
    "representations latentes": "représentation latente",
    "protein design": "protein design",
    "structure prediction": "structure prediction",
    "prédiction de structure": "prédiction de structure",
    "prediction de structure": "prédiction de structure",
    "rna design": "RNA design",
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
    "jumeau numérique": "jumeau numérique",
    "jumeau numerique": "jumeau numérique",
    "chemoinformatique": "chemoinformatique",
    "séries temporelles": "séries temporelles",
    "series temporelles": "séries temporelles",
}

NEGATIVE_TERMS = {
    "gestion administrative",
    "ressources humaines",
    "chef.fe de projets",
    "chef de projets",
    "chargé de communication",
    "charge de communication",
    "transformation numérique",
    "transformation numerique",
    "innovation numérique",
    "innovation numerique",
    "logiciel sans composant ia",
    "logiciel métier sans ia",
    "logiciel metier sans ia",
    "sans composant ia",
    "statistiques descriptives uniquement",
    "data engineering sans apprentissage",
    "sans apprentissage automatique",
    "usage marketing du mot ia",
    "usage marketing de l'ia",
    "marketing de l'ia",
    "communication ia",
    "communication autour de l'ia",
    "coordination de programme ia",
}

POSTDOC_TERMS = {
    "post-doctorant",
    "post doctorant",
    "postdoctorant",
    "post-doctoral",
    "postdoctoral",
    "postdoc",
}

DOCTORATE_REQUIRED_TERMS = {
    "doctorat requis",
    "doctorat exigé",
    "doctorat exige",
    "phd required",
    "ph.d. required",
}

EXCLUDED_CONTRACT_TERMS = {
    "stage",
    "convention de stage",
    "contrat d’apprentissage",
    "contrat d'apprentissage",
    "cdi",
    "mobilité",
    "mobilite",
}


def classify_offer(offer: JobOffer) -> Classification:
    body_text = " ".join(value for value in [offer.description or "", offer.skills or ""] if value)
    if not body_text:
        body_text = offer.raw_text
    text = " ".join(
        value
        for value in [
            offer.title,
            offer.contract_type or "",
            offer.education_level or "",
            body_text,
        ]
        if value
    ).lower()

    hard_filter_passed, target_type, accessibility, eligibility_exclusion = hard_filter(offer, text)
    strong_hits = [label for term, label in STRONG_TERMS.items() if term in text]
    adjacent_hits = [label for term, label in ADJACENT_TERMS.items() if term in text]
    negative_hits = [term for term in NEGATIVE_TERMS if term in text]

    score = 0.0
    if hard_filter_passed:
        score += 0.25
    score += min(len(strong_hits) * 0.14, 0.56)
    score += min(len(adjacent_hits) * 0.06, 0.18)
    if _is_thesis(offer):
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
    if negative_hits:
        domain = "not_relevant"
    elif any(hit in strong_hits for hit in generative_hits):
        domain = "generative_ai"
    elif strong_hits:
        domain = "ml_deep_learning"
    elif adjacent_hits:
        domain = "data_science_adjacent"
    else:
        domain = "not_relevant"

    target_bucket, is_target, exclusion_reason, risk_flags = _decide_bucket(
        offer=offer,
        hard_filter_passed=hard_filter_passed,
        target_type=target_type,
        accessibility=accessibility,
        domain=domain,
        score=score,
        negative_hits=negative_hits,
        eligibility_exclusion=eligibility_exclusion,
    )
    reason = _build_reason(
        strong_hits,
        adjacent_hits,
        negative_hits,
        hard_filter_passed,
        offer,
        target_bucket,
        exclusion_reason,
    )
    short_summary = _build_short_summary(offer, domain, target_bucket)
    why_interesting = _build_why_interesting(
        offer=offer,
        domain=domain,
        bucket=target_bucket,
        score=score,
        exclusion_reason=exclusion_reason,
    )

    return Classification(
        is_target=is_target,
        target_type=target_type,
        ai_domain=domain,
        target_bucket=target_bucket,
        relevance_score=score,
        accessibility=accessibility,
        exclusion_reason=exclusion_reason,
        short_summary=short_summary,
        why_interesting=why_interesting,
        risk_flags=risk_flags,
        classifier_version=CLASSIFIER_VERSION,
        reason=reason,
    )


def apply_classification(offer: JobOffer) -> JobOffer:
    classification = classify_offer(offer)
    return offer.model_copy(
        update={
            "hard_filter_passed": classification.target_type != "not_target",
            "is_target": classification.is_target,
            "target_bucket": classification.target_bucket,
            "accessibility": classification.accessibility,
            "exclusion_reason": classification.exclusion_reason,
            "short_summary": classification.short_summary,
            "why_interesting": classification.why_interesting,
            "risk_flags": classification.risk_flags,
            "classifier_version": classification.classifier_version,
            "last_classified_at": datetime.now(UTC),
            "ai_relevance_score": classification.relevance_score,
            "ai_category": classification.ai_domain,
            "ai_reason": classification.reason,
        }
    )


def hard_filter(
    offer: JobOffer,
    text: str | None = None,
) -> tuple[bool, str, Accessibility, str | None]:
    text = text or " ".join(
        [offer.title, offer.contract_type or "", offer.education_level or ""]
    ).lower()
    contract = (offer.contract_type or "").lower()
    education = (offer.education_level or "").lower()
    structured_text = _structured_text(offer)

    excluded_contract = _excluded_contract_reason(contract)
    if excluded_contract:
        return False, "not_target", "not_accessible", excluded_contract

    if _is_postdoc_or_doctorate_required(text, structured_text):
        return False, "not_target", "doctorate_required", "doctorate_required"

    if offer.source == "anrt" and "cifre" in contract:
        return True, "thesis_or_bac5_cdd", "bac5_accessible", None

    if _is_thesis(offer):
        accessibility = (
            "bac5_accessible" if "bac+5" in education or "doctorant" in contract else "unclear"
        )
        return True, "thesis_or_bac5_cdd", accessibility, None

    is_cdd = "cdd" in contract
    is_it = "it" in contract or "ingénieur" in text or "ingenieur" in text
    is_bac5 = "bac+5" in education or "bac +5" in text or "master" in text

    if is_cdd and is_it and is_bac5:
        return True, "bac5_cdd", "bac5_accessible", None
    return False, "not_target", "unclear", "not_contract_or_level_target"


def _is_thesis(offer: JobOffer) -> bool:
    contract = (offer.contract_type or "").lower()
    title = offer.title.lower()
    url = str(offer.url).lower()
    if any(term in contract for term in ["cdd doctorant", "contrat doctoral", "doctorant"]):
        return True
    if any(term in title for term in ["thèse", "these", "doctorant", "contrat doctoral"]):
        return True
    return "/offres/doctorant/" in url


def _structured_text(offer: JobOffer) -> str:
    values = [offer.title, offer.contract_type or "", offer.education_level or "", str(offer.url)]
    return " ".join(
        value
        for value in values
        if value
    ).lower()


def _is_postdoc_or_doctorate_required(text: str, structured_text: str) -> bool:
    return any(term in text for term in DOCTORATE_REQUIRED_TERMS) or any(
        term in structured_text for term in POSTDOC_TERMS
    )


def _excluded_contract_reason(structured_text: str) -> str | None:
    for term in EXCLUDED_CONTRACT_TERMS:
        if term in structured_text:
            return f"excluded_contract:{term}"
    return None


def _decide_bucket(
    *,
    offer: JobOffer,
    hard_filter_passed: bool,
    target_type: str,
    accessibility: Accessibility,
    domain: str,
    score: float,
    negative_hits: list[str],
    eligibility_exclusion: str | None,
) -> tuple[TargetBucket, bool, str | None, list[str]]:
    risk_flags: list[str] = []
    if accessibility == "doctorate_required":
        risk_flags.append("doctorate_required")
    if "bac+3" in (offer.education_level or "").lower() or "bac+4" in (
        offer.education_level or ""
    ).lower():
        risk_flags.append("bac3_4")
    if offer.unavailable:
        risk_flags.append("expired_or_unavailable")

    if offer.unavailable:
        return "exclude", False, "expired_or_unavailable", risk_flags
    if eligibility_exclusion and eligibility_exclusion.startswith("excluded_contract:"):
        return "exclude", False, eligibility_exclusion, risk_flags
    if accessibility == "doctorate_required":
        risk_flags.append("postdoc")
        return "exclude", False, "doctorate_required_or_postdoc", risk_flags
    if negative_hits:
        return "exclude", False, f"negative_signal:{negative_hits[0]}", risk_flags
    if domain == "not_relevant":
        return "exclude", False, "no_ai_ml_signal", risk_flags
    if offer.source == "anrt" and target_type == "thesis_or_bac5_cdd":
        if domain == "data_science_adjacent":
            return "adjacent_review", True, eligibility_exclusion, risk_flags
        return "primary_target", True, None, risk_flags
    if target_type == "thesis_or_bac5_cdd":
        return "primary_target", True, None, risk_flags
    if target_type == "bac5_cdd":
        return "secondary_target", True, None, risk_flags
    if domain == "data_science_adjacent" and score >= 0.18:
        return "adjacent_review", True, eligibility_exclusion, risk_flags
    if score < 0.35:
        return "exclude", False, "score_below_threshold", risk_flags
    if domain in {"ml_deep_learning", "generative_ai"} and score >= 0.35:
        return "adjacent_review", True, eligibility_exclusion, risk_flags
    return "exclude", False, eligibility_exclusion or "not_target", risk_flags


def _build_reason(
    strong_hits: list[str],
    adjacent_hits: list[str],
    negative_hits: list[str],
    hard_filter_passed: bool,
    offer: JobOffer,
    target_bucket: TargetBucket,
    exclusion_reason: str | None,
) -> str:
    if exclusion_reason and target_bucket == "exclude":
        return f"Exclue: {exclusion_reason}."
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


def _build_short_summary(offer: JobOffer, domain: str, bucket: TargetBucket) -> str:
    label = {
        "generative_ai": "IA générative",
        "ml_deep_learning": "IA/ML",
        "general_ai": "IA",
        "data_science_adjacent": "data science adjacente",
        "not_relevant": "hors cible IA/ML",
    }[domain]
    contract = offer.contract_type or "contrat non précisé"
    return f"{contract} classé {bucket} pour {label}."


def _build_why_interesting(
    *,
    offer: JobOffer,
    domain: str,
    bucket: TargetBucket,
    score: float,
    exclusion_reason: str | None,
) -> str:
    if bucket == "exclude":
        return f"À ignorer pour la veille actuelle: {exclusion_reason or 'hors cible'}."
    level = offer.education_level or "niveau à vérifier"
    contract = offer.contract_type or "contrat à vérifier"
    domain_label = {
        "generative_ai": "IA générative",
        "ml_deep_learning": "IA/ML",
        "general_ai": "IA",
        "data_science_adjacent": "data/data science",
        "not_relevant": "signal IA faible",
    }[domain]
    if bucket == "primary_target":
        return f"Prioritaire: {contract} {level}, sujet {domain_label}, score {score:.2f}."
    if bucket == "secondary_target":
        return f"Bonne piste CDD: {contract} {level}, travail {domain_label}, score {score:.2f}."
    return f"À relire: signal {domain_label}, mais contrat/niveau à confirmer, score {score:.2f}."
