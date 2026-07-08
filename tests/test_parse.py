import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.evaluation import load_evaluation_cases, run_evaluation
from cnrs_job_watcher.export import export_csv, export_markdown
from cnrs_job_watcher.fetch import CnrsClient, parse_offer_sitemap_urls
from cnrs_job_watcher.llm_classifier import classification_json_schema, classify_offer_hybrid
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.profiles import SearchProfile, dedupe_offers, filter_offers_by_profile
from cnrs_job_watcher.schemas import JobOffer
from cnrs_job_watcher.sources import CnrsSourceAdapter
from cnrs_job_watcher.storage import (
    audit_counts,
    changed_offers,
    connect,
    finish_run,
    get_llm_cache,
    latest_run_started_at,
    mark_missing_offers,
    record_offer_snapshot,
    set_llm_cache,
    shortlist,
    start_run,
    upsert_offer,
)

FIXTURES = Path(__file__).parent / "fixtures"

SITEMAP_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://emploi.cnrs.fr/Offres.aspx</loc></url>
  <url><loc>emploi.cnrs.fr/Offres/Doctorant/UPR8001-JUACOR-012/Default.aspx</loc></url>
  <url><loc>emploi.cnrs.fr/Offres/Doctorant/UMR7654-PHINGH-001/Default.aspx</loc></url>
  <url><loc>emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx</loc></url>
  <url><loc>emploi.cnrs.fr/Offres/PASS/UMR0000-STAGE-001/Default.aspx</loc></url>
  <url><loc>emploi.cnrs.fr/Offres/Doctorant/UPR8001-JUACOR-012/Default.aspx</loc></url>
</urlset>
"""


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


def test_parse_offer_sitemap_urls_extracts_target_public_offer_urls() -> None:
    urls = parse_offer_sitemap_urls(SITEMAP_FIXTURE)

    assert urls == [
        "https://emploi.cnrs.fr/Offres/Doctorant/UPR8001-JUACOR-012/Default.aspx",
        "https://emploi.cnrs.fr/Offres/Doctorant/UMR7654-PHINGH-001/Default.aspx",
        "https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
    ]


def test_sitemap_regression_includes_missed_arn_and_protein_theses() -> None:
    urls = parse_offer_sitemap_urls(SITEMAP_FIXTURE)

    assert any("UPR8001-JUACOR-012" in url for url in urls)
    assert any("UMR7654-PHINGH-001" in url for url in urls)


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
    assert offer.source_specific["quick_facts"]["Type de Contrat"] == "CDD Doctorant"
    assert "Sujet De Thèse" in offer.source_specific["sections"]


def test_search_profiles_filter_list_cards() -> None:
    doctorant = JobOffer(
        url="https://emploi.cnrs.fr/Offres/Doctorant/UMR6074-NICKER-008/Default.aspx",
        title="Thèse (H/F) Invariance et transférabilité",
        contract_type="CDD Doctorant",
        education_level="BAC+5",
        raw_text="CDD Doctorant BAC+5",
    )
    bac5_ai = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
        title="Ingénieur d'étude en Intelligence artificielle",
        contract_type="IT en contrat CDD",
        education_level="BAC+5",
        raw_text="Deep learning PyTorch",
    )
    bac3_ai = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR7288-AUDBAR-083/Default.aspx",
        title="Assistant ingénieur deep learning",
        contract_type="IT en contrat CDD",
        education_level="BAC+3/4",
        raw_text="Computer vision",
    )
    non_ai = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR0000-ADMIN-001/Default.aspx",
        title="Ingénieur instrumentation",
        contract_type="IT en contrat CDD",
        education_level="BAC+5",
        raw_text="Instrumentation",
    )
    offers = [doctorant, bac5_ai, bac3_ai, non_ai]

    assert filter_offers_by_profile(offers, SearchProfile.DOCTORANT) == [doctorant]
    assert filter_offers_by_profile(offers, SearchProfile.CDD_BAC5) == [
        doctorant,
        bac5_ai,
        non_ai,
    ]
    assert filter_offers_by_profile(offers, SearchProfile.AI_AUDIT) == [bac5_ai, bac3_ai]


def test_dedupe_offers_prefers_last_seen_key() -> None:
    first = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR0000-TEST-001/Default.aspx",
        reference="UMR0000-TEST-001",
        title="Version A",
    )
    second = first.model_copy(update={"title": "Version B"})

    deduped = dedupe_offers([first, second])

    assert len(deduped) == 1
    assert deduped[0].title == "Version B"


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


def test_classification_targets_missed_protein_generative_ai_thesis() -> None:
    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/Doctorant/UPR8001-JUACOR-012/Default.aspx",
        reference="UPR8001-JUACOR-012",
        title=(
            "Contrat Doctoral (H/F) en Intelligence Artificielle Générative "
            "pour la Modélisation de la Flexibilité des Protéines"
        ),
        contract_type="CDD Doctorant",
        duration="36 mois",
        education_level="Doctorat",
        description=(
            "Développer des méthodes d'intelligence artificielle pour prédire "
            "les conformations de protéines. Le projet s'appuiera sur "
            "l'apprentissage profond, les modèles génératifs de type flow "
            "matching, les modèles de langage pour protéines et PyTorch."
        ),
        raw_text="Apprentissage automatique, protéines, PyTorch.",
    )

    classified = apply_classification(offer)

    assert classified.is_target is True
    assert classified.target_bucket == "primary_target"
    assert classified.ai_category == "generative_ai"
    assert classified.ai_relevance_score is not None
    assert classified.ai_relevance_score >= 0.7


def test_classification_targets_missed_rna_ai_thesis() -> None:
    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/Doctorant/UMR7654-PHINGH-001/Default.aspx",
        reference="UMR7654-PHINGH-001",
        title="Doctorant /(H/F) en intelligence artificielle pour l'ARN",
        contract_type="CDD Doctorant",
        duration="36 mois",
        education_level="BAC+5",
        description=(
            "Développer des modèles hybrides mêlant apprentissage statistique "
            "et modélisation physique afin d'identifier les réseaux "
            "d'interactions ARN-ARN. Le projet utilisera des modèles "
            "probabilistes et génératifs, DCA et Variational Autoencoders."
        ),
        raw_text="ARN, VAE, Python.",
    )

    classified = apply_classification(offer)

    assert classified.is_target is True
    assert classified.target_bucket == "primary_target"
    assert classified.ai_category == "generative_ai"
    assert classified.ai_relevance_score is not None
    assert classified.ai_relevance_score >= 0.6


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


def test_adjacent_review_reason_is_not_exclusion_copy() -> None:
    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR8255-MATHUS-002/Default.aspx",
        reference="UMR8255-MATHUS-002",
        title="Ingénieur vision artificielle et analyse de documents",
        contract_type="IT en contrat CDD",
        education_level="BAC+3/4",
        description="Computer vision, deep learning et analyse de documents.",
        raw_text="Vision artificielle et PyTorch.",
    )

    classified = apply_classification(offer)

    assert classified.target_bucket == "adjacent_review"
    assert classified.ai_reason is not None
    assert not classified.ai_reason.startswith("Exclue:")


def test_llm_classifier_accepts_valid_structured_response() -> None:
    class FakeProvider:
        def classify(self, offer: JobOffer, schema: dict[str, object]) -> dict[str, object]:
            assert schema == classification_json_schema()
            return {
                "is_target": True,
                "target_bucket": "primary_target",
                "ai_domain": "generative_ai",
                "accessibility": "bac5_accessible",
                "relevance_score": 0.93,
                "short_summary": "Thèse sur modèles génératifs.",
                "reason": "Sujet explicitement centré sur IA générative.",
                "risk_flags": [],
            }

    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/Doctorant/UMR6074-NICKER-008/Default.aspx",
        reference="UMR6074-NICKER-008",
        title="Thèse modèles génératifs",
        contract_type="CDD Doctorant",
        education_level="BAC+5",
        description="Modèles génératifs et diffusion.",
        raw_text="IA générative",
    )

    classified = classify_offer_hybrid(offer, FakeProvider())

    assert classified.classifier_version == "hybrid-llm-v1"
    assert classified.target_bucket == "primary_target"
    assert classified.ai_relevance_score == 0.93
    assert classified.short_summary == "Thèse sur modèles génératifs."


def test_llm_classifier_invalid_response_keeps_rules_decision_for_review() -> None:
    class InvalidProvider:
        def classify(self, offer: JobOffer, schema: dict[str, object]) -> dict[str, object]:
            return {"target_bucket": "primary_target"}

    offer = JobOffer(
        url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
        reference="UMR5549-LESMAR-016",
        title="Ingénieur d'étude en Intelligence artificielle",
        contract_type="IT en contrat CDD",
        education_level="BAC+5",
        description="Deep learning, PyTorch et réseaux de neurones.",
        raw_text="Machine learning et intelligence artificielle.",
    )

    classified = classify_offer_hybrid(offer, InvalidProvider())

    assert classified.is_target is True
    assert classified.target_bucket == "adjacent_review"
    assert "llm_invalid_response" in classified.risk_flags


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
    assert counts["by_source"] == {"cnrs": 2}
    assert counts["by_exclusion_reason"] == {"no_ai_ml_signal": 1}


def test_storage_preserves_first_seen_and_filters_new_offers(tmp_path: Path) -> None:
    connection = connect(tmp_path / "history.sqlite")
    older_first_seen = datetime.now(UTC) - timedelta(days=2)
    offer = apply_classification(
        JobOffer(
            url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
            reference="UMR5549-LESMAR-016",
            title="Ingénieur d'étude en Intelligence artificielle bio-inspirée",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning et intelligence artificielle.",
            first_seen_at=older_first_seen,
        )
    )

    upsert_offer(connection, offer)
    run_id = start_run(connection)
    since = latest_run_started_at(connection)
    updated = apply_classification(
        offer.model_copy(update={"description": "Deep learning, PyTorch et JAX."})
    )
    upsert_offer(connection, updated)
    finish_run(
        connection,
        run_id,
        pages_fetched=1,
        offers_discovered=1,
        offers_fetched=1,
        errors_count=0,
    )

    all_rows = shortlist(connection, min_score=0.25)
    new_rows = shortlist(connection, min_score=0.25, since=since)

    assert len(all_rows) == 1
    assert all_rows[0].first_seen_at == older_first_seen
    assert new_rows == []


def test_run_snapshot_and_digest_export(tmp_path: Path) -> None:
    connection = connect(tmp_path / "snapshots.sqlite")
    run_id = start_run(connection, profile="all_public", source="cnrs")
    offer = apply_classification(
        JobOffer(
            url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
            reference="UMR5549-LESMAR-016",
            title="Ingénieur d'étude en Intelligence artificielle bio-inspirée",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning et intelligence artificielle.",
            content_hash="abc123",
        )
    )
    upsert_offer(connection, offer)
    record_offer_snapshot(
        connection,
        offer,
        content_hash="abc123",
        raw_path="/tmp/offer.html",
        run_id=run_id,
    )
    finish_run(
        connection,
        run_id,
        pages_fetched=1,
        offers_discovered=1,
        offers_fetched=1,
        errors_count=0,
    )

    snapshot_count = connection.execute("SELECT COUNT(*) FROM offer_snapshots").fetchone()[0]
    counts = audit_counts(connection)
    digest_path = tmp_path / "digest.md"
    export_markdown(shortlist(connection, min_score=0.25), digest_path)

    assert snapshot_count == 1
    assert counts["latest_run"]["offers_fetched"] == 1
    assert counts["latest_run"]["source"] == "cnrs"
    assert counts["latest_run"]["status_message"] is None
    assert "Ingénieur d'étude en Intelligence artificielle" in digest_path.read_text(
        encoding="utf-8"
    )


def test_changed_offers_reports_distinct_snapshot_hashes(tmp_path: Path) -> None:
    connection = connect(tmp_path / "changes.sqlite")
    run_id = start_run(connection, profile="anrt_cifre", source="anrt")
    offer = apply_classification(
        JobOffer(
            source="anrt",
            source_specific={"anrt_kind": "entreprise"},
            url="https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
            reference="CIFRE-2026-123",
            title="Thèse CIFRE deep learning",
            contract_type="CIFRE",
            education_level="BAC+5 / Master",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning.",
            content_hash="hash-a",
        )
    )
    upsert_offer(connection, offer)
    record_offer_snapshot(
        connection,
        offer,
        content_hash="hash-a",
        raw_path="/tmp/a.html",
        run_id=run_id,
    )
    record_offer_snapshot(
        connection,
        offer,
        content_hash="hash-a",
        raw_path="/tmp/a-again.html",
        run_id=run_id,
    )

    assert changed_offers(connection, source="anrt") == []

    record_offer_snapshot(
        connection,
        offer,
        content_hash="hash-b",
        raw_path="/tmp/b.html",
        run_id=run_id,
    )

    rows = changed_offers(connection, source="anrt")
    counts = audit_counts(connection, source="anrt")

    assert len(rows) == 1
    assert rows[0]["reference"] == "CIFRE-2026-123"
    assert rows[0]["versions"] == 2
    assert counts["changed_offers"][0]["versions"] == 2


def test_run_status_records_authenticated_source_failures(tmp_path: Path) -> None:
    connection = connect(tmp_path / "runs.sqlite")
    run_id = start_run(connection, profile="anrt_cifre", source="anrt", source_kind="entreprise")

    finish_run(
        connection,
        run_id,
        pages_fetched=0,
        offers_discovered=0,
        offers_fetched=0,
        errors_count=0,
        status_message="auth_required",
    )

    latest = audit_counts(connection)["latest_run"]
    assert latest["source"] == "anrt"
    assert latest["source_kind"] == "entreprise"
    assert latest["status_message"] == "auth_required"


def test_missing_offers_are_kept_in_history_but_removed_from_shortlist(tmp_path: Path) -> None:
    connection = connect(tmp_path / "missing.sqlite")
    offer = apply_classification(
        JobOffer(
            source="anrt",
            source_specific={"anrt_kind": "entreprise"},
            url="https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
            reference="CIFRE-2026-123",
            title="Thèse CIFRE deep learning",
            contract_type="CIFRE",
            education_level="BAC+5 / Master",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning.",
        )
    )
    upsert_offer(connection, offer)

    missing_count = mark_missing_offers(connection, source="anrt", seen_urls=[])

    assert missing_count == 1
    assert shortlist(connection, min_score=0.1, source="anrt") == []
    counts = audit_counts(connection, source="anrt")
    assert counts["missing"] == 1

    upsert_offer(connection, offer)
    restored = shortlist(connection, min_score=0.1, source="anrt")

    assert [row.reference for row in restored] == ["CIFRE-2026-123"]
    assert restored[0].last_seen_status == "seen"


def test_exports_include_actionable_fields_and_exclusions(tmp_path: Path) -> None:
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
    excluded = apply_classification(
        JobOffer(
            url="https://emploi.cnrs.fr/Offres/CDD/UMR0000-ADMIN-001/Default.aspx",
            reference="UMR0000-ADMIN-001",
            title="Ingénieur instrumentation",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Instrumentation et banc de mesure.",
            raw_text="Instrumentation.",
        )
    )
    markdown_path = tmp_path / "digest.md"
    csv_path = tmp_path / "digest.csv"

    export_markdown([target, excluded], markdown_path)
    export_csv([target], csv_path)

    markdown = markdown_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "## Pertinentes mais à vérifier" in markdown
    assert "## Exclusions notables" in markdown
    assert "- Intérêt :" in markdown
    assert "why_interesting" in csv_text
    assert "contract,level" in csv_text
    assert "source" in csv_text


def test_exports_include_anrt_source_specific_fields(tmp_path: Path) -> None:
    target = apply_classification(
        JobOffer(
            source="anrt",
            source_specific={
                "anrt_kind": "entreprise",
                "company_name": "Acme Research",
                "laboratory_name": "Laboratoire IA Appliquée",
                "sector": "Industrie",
                "application_deadline": "2026-09-30",
            },
            url="https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
            reference="CIFRE-2026-123",
            title="Thèse CIFRE deep learning",
            contract_type="CIFRE",
            education_level="BAC+5 / Master",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning et intelligence artificielle.",
        )
    )
    markdown_path = tmp_path / "anrt.md"
    csv_path = tmp_path / "anrt.csv"

    export_markdown([target], markdown_path)
    export_csv([target], csv_path)

    markdown = markdown_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "- Source : ANRT entreprise" in markdown
    assert "- Entreprise : Acme Research" in markdown
    assert "- Laboratoire source : Laboratoire IA Appliquée" in markdown
    assert "company,source_laboratory,sector,application_deadline" in csv_text


def test_source_specific_round_trip_and_source_filter(tmp_path: Path) -> None:
    connection = connect(tmp_path / "sources.sqlite")
    cnrs_offer = apply_classification(
        JobOffer(
            source="cnrs",
            source_specific={"portal": "emploi.cnrs.fr"},
            url="https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx",
            reference="UMR5549-LESMAR-016",
            title="Ingénieur d'étude en Intelligence artificielle bio-inspirée",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Deep learning, PyTorch et réseaux de neurones.",
            raw_text="Machine learning et intelligence artificielle.",
        )
    )
    inria_offer = apply_classification(
        JobOffer(
            source="inria",
            source_specific={"team": "mock"},
            url="https://jobs.inria.fr/public/classic/fr/offres/2026-001",
            reference="INRIA-2026-001",
            title="Ingénieur machine learning",
            contract_type="IT en contrat CDD",
            education_level="BAC+5",
            description="Machine learning, PyTorch et deep learning.",
            raw_text="Intelligence artificielle.",
        )
    )
    upsert_offer(connection, cnrs_offer)
    upsert_offer(connection, inria_offer)

    cnrs_rows = shortlist(connection, min_score=0.25, source="cnrs")
    explicit_all_rows = shortlist(connection, min_score=0.25, source=None)
    all_rows = shortlist(connection, min_score=0.25)
    cnrs_counts = audit_counts(connection, source="cnrs")
    all_counts = audit_counts(connection)

    assert [offer.source for offer in cnrs_rows] == ["cnrs"]
    assert cnrs_rows[0].source_specific == {"portal": "emploi.cnrs.fr"}
    assert {offer.source for offer in explicit_all_rows} == {"cnrs", "inria"}
    assert {offer.source for offer in all_rows} == {"cnrs", "inria"}
    assert cnrs_counts["total"] == 1
    assert cnrs_counts["by_source"] == {"cnrs": 1}
    assert all_counts["total"] == 2
    assert all_counts["by_source"] == {"cnrs": 1, "inria": 1}


def test_cnrs_source_adapter_normalizes_source() -> None:
    class FakeClient:
        def fetch_offer_sitemap(self, use_cache: bool = True) -> str:
            return SITEMAP_FIXTURE

        def fetch_list_page(self, page: int = 1, use_cache: bool = True) -> str:
            return (FIXTURES / "list_page.html").read_text(encoding="utf-8")

        def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
            return (FIXTURES / "offer_page.html").read_text(encoding="utf-8")

    adapter = CnrsSourceAdapter(FakeClient())

    offers, stats = adapter.discover()
    urls = adapter.discover_urls()
    detail = adapter.parse_detail(adapter.fetch_detail(str(offers[0].url)), str(offers[0].url))

    assert stats.total_pages == 13
    assert "https://emploi.cnrs.fr/Offres/Doctorant/UMR7654-PHINGH-001/Default.aspx" in urls
    assert offers[0].source == "cnrs"
    assert detail.source == "cnrs"


def test_cnrs_client_retries_transient_http_errors(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text="<html>ok</html>", request=request)

    client = CnrsClient(cache_dir=tmp_path, delay_seconds=0, max_retries=1, backoff_seconds=0)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    html = client.fetch_list_page(use_cache=False)

    client.close()
    assert html == "<html>ok</html>"
    assert calls == 2


def test_llm_cache_round_trips_by_content_hash(tmp_path: Path) -> None:
    connection = connect(tmp_path / "llm-cache.sqlite")
    payload = {
        "is_target": True,
        "target_bucket": "secondary_target",
        "ai_domain": "ml_deep_learning",
        "accessibility": "bac5_accessible",
        "relevance_score": 0.88,
        "short_summary": "Ingénierie IA.",
        "reason": "CDD BAC+5 avec deep learning.",
        "risk_flags": [],
    }

    set_llm_cache(connection, "hash-1", "hybrid-llm-v1", payload)

    assert get_llm_cache(connection, "hash-1", "hybrid-llm-v1") == payload
    assert get_llm_cache(connection, "hash-2", "hybrid-llm-v1") is None


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
        "source_specific",
        "target_bucket",
        "accessibility",
        "exclusion_reason",
        "short_summary",
        "why_interesting",
        "risk_flags",
        "classifier_version",
        "content_hash",
        "last_classified_at",
        "last_seen_status",
    }.issubset(columns)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'llm_cache'"
    ).fetchone()


def test_evaluation_dataset_matches_current_classifier() -> None:
    cases = load_evaluation_cases(FIXTURES / "evaluation" / "offers.json")

    summary = run_evaluation(cases)

    assert summary.total >= 30
    assert summary.bucket_accuracy == 1.0
    assert summary.domain_accuracy == 1.0
    assert summary.accessibility_accuracy == 1.0
    assert summary.target_precision == 1.0
    assert summary.target_recall == 1.0
    assert summary.false_targets == 0
    assert summary.missed_targets == 0


def test_observed_evaluation_dataset_matches_current_classifier() -> None:
    cases = load_evaluation_cases(FIXTURES / "evaluation" / "observed_offers.json")

    summary = run_evaluation(cases)

    assert summary.total >= 30
    assert summary.bucket_accuracy == 1.0
    assert summary.domain_accuracy == 1.0
    assert summary.accessibility_accuracy == 1.0
    assert summary.target_precision == 1.0
    assert summary.target_recall == 1.0
    assert summary.false_targets == 0
    assert summary.missed_targets == 0
