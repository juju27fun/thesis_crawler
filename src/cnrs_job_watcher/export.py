from __future__ import annotations

import csv
from pathlib import Path

from cnrs_job_watcher.schemas import JobOffer


def export_markdown(offers: list[JobOffer], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True) if output.parent != Path(".") else None
    lines = ["# Offres CNRS IA / ML accessibles BAC+5", ""]
    if not offers:
        lines.append("Aucune offre pertinente dans la base locale pour le seuil demandé.")
    for offer in offers:
        score = f"{offer.ai_relevance_score:.2f}" if offer.ai_relevance_score is not None else "n/a"
        lines.extend(
            [
                f"## {offer.title}",
                "",
                f"- Type : {offer.contract_type or 'n/a'}",
                f"- Durée : {offer.duration or 'n/a'}",
                f"- Niveau : {offer.education_level or 'n/a'}",
                f"- Lieu : {offer.location or 'n/a'}",
                f"- Labo : {offer.lab or 'n/a'}",
                f"- Publication : {offer.published_at_text or 'n/a'}",
                f"- Score : {score}",
                f"- Pourquoi : {offer.ai_reason or 'n/a'}",
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
                "title",
                "contract_type",
                "duration",
                "education_level",
                "location",
                "lab",
                "published_at_text",
                "url",
                "score",
                "category",
                "reason",
            ],
        )
        writer.writeheader()
        for offer in offers:
            writer.writerow(
                {
                    "title": offer.title,
                    "contract_type": offer.contract_type,
                    "duration": offer.duration,
                    "education_level": offer.education_level,
                    "location": offer.location,
                    "lab": offer.lab,
                    "published_at_text": offer.published_at_text,
                    "url": str(offer.url),
                    "score": offer.ai_relevance_score,
                    "category": offer.ai_category,
                    "reason": offer.ai_reason,
                }
            )
