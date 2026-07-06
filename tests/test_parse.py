import sqlite3
from pathlib import Path

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.schemas import JobOffer
from cnrs_job_watcher.storage import audit_counts, connect, shortlist, upsert_offer

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
    assert classified.is_target is True
    assert classified.target_bucket == "primary_target"
    assert classified.ai_category == "generative_ai"
    assert classified.ai_relevance_score is not None
    assert classified.ai_relevance_score >= 0.7


def test_classification_excludes_postdoc_doctorate_required() -> None:
    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR8023-ERWALL-002/Default.aspx",
        reference="UMR8023-ERWALL-002",
        title="Post-doctorant en apprentissage automatique pour l'astrophysique",
        contract_type="Chercheur en contrat CDD",
        education_level="Doctorat",
        description="Doctorat requis. Deep learning et réseaux de neurones.",
        raw_text="Postdoctorant. PhD required. Machine learning.",
    )

    classified = apply_classification(offer)

    assert classified.hard_filter_passed is False
    assert classified.is_target is False
    assert classified.target_bucket == "exclude"
    assert classified.accessibility == "doctorate_required"
    assert classified.exclusion_reason == "doctorate_required_or_postdoc"


def test_classification_excludes_bac5_cdd_without_ai_signal() -> None:
    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR0000-ADMIN-001/Default.aspx",
        reference="UMR0000-ADMIN-001",
        title="Ingénieur d'étude en instrumentation",
        contract_type="IT en contrat CDD",
        education_level="BAC+5",
        description="Développement d'un banc de mesure et documentation technique.",
        raw_text="CDD BAC+5 ingénieur instrumentation.",
    )

    classified = apply_classification(offer)

    assert classified.hard_filter_passed is True
    assert classified.is_target is False
    assert classified.ai_category == "not_relevant"
    assert classified.target_bucket == "exclude"
    assert classified.exclusion_reason == "no_ai_ml_signal"


def test_classification_targets_bac5_it_ai_cdd() -> None:
    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
        reference="UMR5549-LESMAR-016",
        title="Ingénieur d'étude en Intelligence artificielle bio-inspirée",
        contract_type="IT en contrat CDD",
        education_level="BAC+5",
        description="Développement Python de modèles de deep learning avec PyTorch.",
        raw_text="Intelligence artificielle. Réseaux de neurones. Machine learning.",
    )

    classified = apply_classification(offer)

    assert classified.hard_filter_passed is True
    assert classified.is_target is True
    assert classified.target_bucket == "secondary_target"
    assert classified.ai_category == "ml_deep_learning"


def test_sqlite_migration_and_shortlist_use_is_target(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.sqlite"
    connection = connect(db_path)

    target = apply_classification(
        JobOffer(
            url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
            reference="UMR5549-LESMAR-016",
            title="Ingénieur d'étude en Intelligence artificielle bio-inspirée",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning et intelligence artificielle.",
        )
    )
    not_relevant = apply_classification(
        JobOffer(
            url="https://emploi.cnrs.fr/Offres/CDD/UMR0000-ADMIN-001/Default.aspx",
            reference="UMR0000-ADMIN-001",
            title="Ingénieur d'étude en instrumentation",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Banc de mesure et instrumentation.",
            raw_text="CDD BAC+5 ingénieur.",
        )
    )

    upsert_offer(connection, target)
    upsert_offer(connection, not_relevant)

    rows = shortlist(connection, min_score=0.25)

    assert [offer.reference for offer in rows] == ["UMR5549-LESMAR-016"]
    assert rows[0].target_bucket == "secondary_target"

    counts = audit_counts(connection)
    assert counts["total"] == 2
    assert counts["by_bucket"] == {"exclude": 1, "secondary_target": 1}
    assert counts["by_exclusion_reason"] == {"no_ai_ml_signal": 1}


def test_sqlite_migration_adds_target_columns_to_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE offers (
            url TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            reference TEXT,
            title TEXT NOT NULL,
            contract_type TEXT,
            duration TEXT,
            education_level TEXT,
            experience_level TEXT,
            location TEXT,
            lab TEXT,
            published_at_text TEXT,
            description TEXT,
            skills TEXT,
            raw_text TEXT NOT NULL,
            unavailable INTEGER NOT NULL DEFAULT 0,
            hard_filter_passed INTEGER NOT NULL DEFAULT 0,
            ai_relevance_score REAL,
            ai_category TEXT,
            ai_reason TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    legacy.commit()
    legacy.close()

    connection = connect(db_path)
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(offers)").fetchall()
    }

    assert {
        "is_target",
        "target_bucket",
        "accessibility",
        "exclusion_reason",
        "short_summary",
        "risk_flags",
        "classifier_version",
    }.issubset(columns)
