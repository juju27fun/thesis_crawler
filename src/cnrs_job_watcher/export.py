from __future__ import annotations

import csv
from pathlib import Path

from cnrs_job_watcher.schemas import JobOffer, TargetBucket
from cnrs_job_watcher.sources import source_definition

BUCKET_TITLES: dict[TargetBucket, str] = {
    "primary_target": "Très pertinentes",
    "secondary_target": "Pertinentes mais à vérifier",
    "adjacent_review": "Adjacentes / revue manuelle",
    "exclude": "Exclusions notables",
}


def export_markdown(offers: list[JobOffer], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True) if output.parent != Path(".") else None
    lines = ["# Offres de thèse IA / ML", ""]
    if not offers:
        lines.append("Aucune offre pertinente dans la base locale pour le seuil demandé.")
    for bucket, title in BUCKET_TITLES.items():
        bucket_offers = [offer for offer in offers if offer.target_bucket == bucket]
        if not bucket_offers:
            continue
        lines.extend([f"## {title}", ""])
        for offer in bucket_offers:
            score = (
                f"{offer.ai_relevance_score:.2f}" if offer.ai_relevance_score is not None else "n/a"
            )
            flags = ", ".join(offer.risk_flags) if offer.risk_flags else "aucun"
            origin = _display_origin(offer)
            source_details = _source_detail_lines(offer)
            lines.extend(
                [
                    f"### {offer.title}",
                    "",
                    f"- Source : {origin}",
                    f"- Type : {offer.contract_type or 'n/a'}",
                    f"- Durée : {offer.duration or 'n/a'}",
                    f"- Niveau : {offer.education_level or 'n/a'}",
                    f"- Lieu : {offer.location or 'n/a'}",
                    f"- Labo : {offer.lab or 'n/a'}",
                    f"- Publication : {offer.published_at_text or 'n/a'}",
                    *source_details,
                    f"- Score : {score}",
                    f"- Résumé : {offer.short_summary or 'n/a'}",
                    f"- Intérêt : {offer.why_interesting or 'n/a'}",
                    f"- Pourquoi : {offer.ai_reason or 'n/a'}",
                    f"- Flags : {flags}",
                    f"- Lien : {offer.url}",
                    "",
                ]
            )
    output.write_text("\n".join(lines), encoding="utf-8")


def export_csv(offers: list[JobOffer], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True) if output.parent != Path(".") else None
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reference",
                "source",
                "origin",
                "bucket",
                "score",
                "title",
                "contract",
                "level",
                "contract_type",
                "duration",
                "education_level",
                "location",
                "lab",
                "published_at_text",
                "company",
                "source_laboratory",
                "sector",
                "application_deadline",
                "category",
                "summary",
                "why_interesting",
                "reason",
                "flags",
                "url",
            ],
        )
        writer.writeheader()
        for offer in offers:
            writer.writerow(
                {
                    "reference": offer.reference,
                    "source": offer.source,
                    "origin": _display_origin(offer),
                    "bucket": offer.target_bucket,
                    "score": offer.ai_relevance_score,
                    "title": offer.title,
                    "contract": offer.contract_type,
                    "level": offer.education_level,
                    "contract_type": offer.contract_type,
                    "duration": offer.duration,
                    "education_level": offer.education_level,
                    "location": offer.location,
                    "lab": offer.lab,
                    "published_at_text": offer.published_at_text,
                    "company": offer.source_specific.get("company_name"),
                    "source_laboratory": offer.source_specific.get("laboratory_name"),
                    "sector": offer.source_specific.get("sector"),
                    "application_deadline": offer.source_specific.get("application_deadline"),
                    "category": offer.ai_category,
                    "summary": offer.short_summary,
                    "why_interesting": offer.why_interesting,
                    "reason": offer.ai_reason,
                    "flags": ",".join(offer.risk_flags),
                    "url": str(offer.url),
                }
            )


def _display_origin(offer: JobOffer) -> str:
    if offer.source == "anrt":
        kind = offer.source_specific.get("anrt_kind")
        if kind == "entreprise":
            return "ANRT entreprise"
        if kind == "laboratoire":
            return "ANRT laboratoire"
        return "ANRT"
    if offer.source == "cnrs":
        return source_definition("cnrs").display_name
    if offer.source in {"anrt"}:
        return source_definition(offer.source).display_name
    return offer.source


def _source_detail_lines(offer: JobOffer) -> list[str]:
    if offer.source != "anrt":
        return []
    details = [
        ("Entreprise", offer.source_specific.get("company_name")),
        ("Laboratoire source", offer.source_specific.get("laboratory_name")),
        ("Secteur", offer.source_specific.get("sector")),
        ("Date limite", offer.source_specific.get("application_deadline")),
    ]
    return [f"- {label} : {value}" for label, value in details if value]
