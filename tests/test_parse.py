from pathlib import Path

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_list_page_extracts_cards_and_stats() -> None:
    html = (FIXTURES / "list_page.html").read_text(encoding="utf-8")

    offers, stats = parse_list_page(html)

    assert stats.total_offers == 592
    assert stats.total_pages == 13
    assert len(offers) == 1
    assert (
        offers[0].title
        == "Thèse (H/F) Invariance et transférabilité dans les modèles génératifs"
    )
    assert offers[0].contract_type == "CDD Doctorant"
    assert offers[0].duration == "36 mois"
    assert offers[0].education_level == "BAC+5"
    assert offers[0].location == "RENNES • Ille-et-Vilaine"


def test_parse_offer_detail_extracts_reference_and_description() -> None:
    html = (FIXTURES / "offer_page.html").read_text(encoding="utf-8")

    offer = parse_offer_detail(
        html,
        "https://emploi.cnrs.fr/Offres/Doctorant/UMR6074-NICKER-008/Default.aspx",
    )

    assert offer.reference == "UMR6074-NICKER-008"
    assert offer.contract_type == "CDD Doctorant"
    assert offer.duration == "36 mois"
    assert offer.location == "35042 RENNES"
    assert "modèles génératifs" in (offer.description or "")


def test_classification_targets_generative_ai_thesis() -> None:
    html = (FIXTURES / "offer_page.html").read_text(encoding="utf-8")
    offer = parse_offer_detail(
        html,
        "https://emploi.cnrs.fr/Offres/Doctorant/UMR6074-NICKER-008/Default.aspx",
    )

    classified = apply_classification(offer)

    assert classified.hard_filter_passed is True
    assert classified.ai_category == "generative_ai"
    assert classified.ai_relevance_score is not None
    assert classified.ai_relevance_score >= 0.7
