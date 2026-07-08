from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cnrs_job_watcher import cli as cli_module
from cnrs_job_watcher.anrt.fetch import (
    AnrtAuthenticationRequired,
    AnrtClient,
    AnrtFixtureClient,
    AnrtKind,
    is_logged_out_page,
)
from cnrs_job_watcher.anrt.fixtures import (
    anonymize_fixture_tree,
    anonymize_html,
    audit_anrt_fixture_tree,
)
from cnrs_job_watcher.anrt.parse import (
    AnrtOfferUnavailable,
    AnrtServerErrorPage,
    AnrtUnexpectedPage,
    parse_anrt_datatables_offer,
    parse_anrt_list_page,
    parse_anrt_offer_detail,
    parse_anrt_pagination_urls,
    parse_anrt_result_count,
)
from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.evaluation import load_evaluation_cases, run_evaluation
from cnrs_job_watcher.sources import AnrtSourceAdapter, source_definition

FIXTURES = Path(__file__).parent / "fixtures"

ANRT_LIST_HTML = """
<html>
  <body>
    <h1>Offres entreprise</h1>
    <p>2 offres trouvées</p>
    <a href="/espace-membre/offre-detail/123">Voir l'offre</a>
    <a href="https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/456">
      Voir l'offre laboratoire
    </a>
    <a href="/espace-membre/offre-list/entreprise">Pagination</a>
    <a href="/contact">Contact</a>
  </body>
</html>
"""

ANRT_DETAIL_HTML = """
<html>
  <body>
    <h1>Thèse CIFRE - Deep learning pour la détection d'anomalies industrielles</h1>
    <dl>
      <dt>Référence</dt><dd>CIFRE-2026-123</dd>
      <dt>Entreprise</dt><dd>Acme Research</dd>
      <dt>Laboratoire</dt><dd>Laboratoire IA Appliquée</dd>
      <dt>Lieu</dt><dd>Paris</dd>
      <dt>Secteur</dt><dd>Industrie</dd>
      <dt>Discipline</dt><dd>Informatique</dd>
      <dt>École doctorale</dt><dd>ED Sciences Numériques</dd>
      <dt>Partenaire recherché</dt><dd>Laboratoire académique identifié</dd>
      <dt>Télétravail</dt><dd>Hybride possible</dd>
      <dt>Financement</dt><dd>Demande CIFRE à déposer</dd>
      <dt>Statut CIFRE</dt><dd>Montage en cours</dd>
      <dt>Contact</dt><dd>email-anonymise@example.invalid</dd>
    </dl>
    <h2>Description</h2>
    <p>Le projet développe des modèles de deep learning et des réseaux de neurones.</p>
    <h2>Profil</h2>
    <p>Master ou BAC+5 en machine learning, Python et PyTorch.</p>
  </body>
</html>
"""

ANRT_LOGGED_OUT_HTML = """
<html>
  <body>
    <h1>Déconnexion</h1>
    <p>Merci de votre visite. A bientôt</p>
  </body>
</html>
"""


def test_parse_anrt_list_page_extracts_detail_urls_only() -> None:
    urls = parse_anrt_list_page(ANRT_LIST_HTML, AnrtKind.ENTREPRISE)

    assert urls == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/456",
    ]


def test_parse_anrt_pagination_urls_extracts_next_pages() -> None:
    html = """
    <nav class="pagination">
      <a href="/espace-membre/offre-list/entreprise?page=2" rel="next">Suivant</a>
      <a href="/espace-membre/offre-detail/999">Offre à ignorer</a>
    </nav>
    """

    expected = (
        "https://offres-et-candidatures-cifre.anrt.asso.fr"
        "/espace-membre/offre-list/entreprise?page=2"
    )
    assert parse_anrt_pagination_urls(html) == [expected]


def test_parse_anrt_result_count_extracts_optional_ui_total() -> None:
    assert parse_anrt_result_count(ANRT_LIST_HTML) == 2
    assert parse_anrt_result_count("<html><body>Aucune offre disponible</body></html>") == 0
    assert parse_anrt_result_count("<html><body>Aucun compteur</body></html>") is None


def test_parse_anrt_detail_maps_to_common_job_offer() -> None:
    offer = parse_anrt_offer_detail(
        ANRT_DETAIL_HTML,
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
        AnrtKind.ENTREPRISE,
    )

    assert offer.source == "anrt"
    assert offer.source_specific["anrt_kind"] == "entreprise"
    assert offer.source_specific["company_name"] == "Acme Research"
    assert offer.source_specific["laboratory_name"] == "Laboratoire IA Appliquée"
    assert offer.source_specific["sector"] == "Industrie"
    assert offer.source_specific["discipline"] == "Informatique"
    assert offer.source_specific["doctoral_school"] == "ED Sciences Numériques"
    assert offer.source_specific["partner_expected"] == "Laboratoire académique identifié"
    assert offer.source_specific["remote_or_hybrid"] == "Hybride possible"
    assert offer.source_specific["funding_status"] == "Demande CIFRE à déposer"
    assert offer.source_specific["cifre_status"] == "Montage en cours"
    assert offer.source_specific["contact_visible"] is True
    assert offer.reference == "CIFRE-2026-123"
    assert offer.contract_type == "CIFRE"
    assert offer.education_level == "BAC+5 / Master"
    assert offer.location == "Paris"
    assert "deep learning" in (offer.description or "")


def test_anrt_logged_out_page_is_rejected() -> None:
    with pytest.raises(AnrtAuthenticationRequired):
        parse_anrt_list_page(ANRT_LOGGED_OUT_HTML, AnrtKind.ENTREPRISE)

    with pytest.raises(AnrtAuthenticationRequired):
        parse_anrt_offer_detail(
            ANRT_LOGGED_OUT_HTML,
            "https://offres-et-candidatures-cifre.anrt.asso.fr/logout",
            AnrtKind.ENTREPRISE,
        )


def test_anrt_logged_in_page_with_logout_link_is_not_rejected() -> None:
    html = """
    <html>
      <body>
        <nav><a href="/logout">Déconnexion</a></nav>
        <h1>Offres entreprise</h1>
        <a href="/espace-membre/offre-detail/123">Voir l'offre</a>
      </body>
    </html>
    """

    assert is_logged_out_page(html, "/espace-membre/offre-list/entreprise") is False
    assert parse_anrt_list_page(html, AnrtKind.ENTREPRISE) == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123"
    ]


def test_anrt_parser_rejects_unavailable_offer_and_server_error_pages() -> None:
    unavailable_html = "<html><body><h1>Offre indisponible</h1></body></html>"
    with pytest.raises(AnrtOfferUnavailable, match="unavailable"):
        parse_anrt_offer_detail(
            unavailable_html,
            "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/999",
            AnrtKind.ENTREPRISE,
        )

    server_error_html = "<html><body><h1>Erreur serveur</h1><p>HTTP 500</p></body></html>"
    with pytest.raises(AnrtServerErrorPage, match="server error"):
        parse_anrt_list_page(server_error_html, AnrtKind.LABORATOIRE)


def test_anrt_parser_rejects_authenticated_non_offer_detail_page() -> None:
    non_offer_html = "<html><body><main>Tableau de bord candidat</main></body></html>"

    with pytest.raises(AnrtUnexpectedPage, match="title not found"):
        parse_anrt_offer_detail(
            non_offer_html,
            "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/tableau-de-bord",
            AnrtKind.ENTREPRISE,
        )


def test_anrt_client_rejects_missing_or_invalid_session_file(tmp_path: Path) -> None:
    with pytest.raises(AnrtAuthenticationRequired, match="not found"):
        AnrtClient(session_file=tmp_path / "missing.json")

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{not-json", encoding="utf-8")
    with pytest.raises(AnrtAuthenticationRequired, match="not valid JSON"):
        AnrtClient(session_file=invalid_json)

    invalid_shape = tmp_path / "invalid-shape.json"
    invalid_shape.write_text(json.dumps({"storage": []}), encoding="utf-8")
    with pytest.raises(AnrtAuthenticationRequired, match="cookies list"):
        AnrtClient(session_file=invalid_shape)

    empty_cookies = tmp_path / "empty.json"
    empty_cookies.write_text(
        json.dumps({"cookies": [{"name": ""}, {"value": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(AnrtAuthenticationRequired, match="no usable cookies"):
        AnrtClient(session_file=empty_cookies)


def test_anrt_client_loads_playwright_or_raw_cookie_session(tmp_path: Path) -> None:
    playwright_state = tmp_path / "playwright-state.json"
    playwright_state.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "sessionid",
                        "value": "abc",
                        "domain": ".offres-et-candidatures-cifre.anrt.asso.fr",
                        "path": "/",
                    }
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )

    with AnrtClient(session_file=playwright_state) as client:
        assert client.client.cookies.get("sessionid") == "abc"

    raw_cookie_list = tmp_path / "cookies.json"
    raw_cookie_list.write_text(
        json.dumps([{"name": "sid", "value": "raw", "path": "/"}]),
        encoding="utf-8",
    )

    with AnrtClient(session_file=raw_cookie_list) as client:
        assert client.client.cookies.get("sid") == "raw"


def test_anrt_cifre_offer_is_classified_as_primary_when_ai_ml_is_strong() -> None:
    offer = parse_anrt_offer_detail(
        ANRT_DETAIL_HTML,
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
        AnrtKind.ENTREPRISE,
    )

    classified = apply_classification(offer)

    assert classified.is_target is True
    assert classified.target_bucket == "primary_target"
    assert classified.accessibility == "bac5_accessible"
    assert classified.ai_category == "ml_deep_learning"


def test_anrt_source_adapter_deduplicates_both_kinds_and_preserves_kind_for_detail() -> None:
    list_without_pagination = ANRT_LIST_HTML.replace(
        '<a href="/espace-membre/offre-list/entreprise">Pagination</a>',
        "",
    )

    class FakeClient:
        def fetch_list_page(self, kind: AnrtKind, use_cache: bool = True) -> str:
            return list_without_pagination

        def fetch_list_url(self, url: str, use_cache: bool = True) -> str:
            return "<html><body></body></html>"

        def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
            return ANRT_DETAIL_HTML

        def offer_cache_path(self, url: str) -> str:
            return f"/tmp/{url.rsplit('/', 1)[-1]}.html"

    adapter = AnrtSourceAdapter(FakeClient(), kind=AnrtKind.BOTH)

    urls = adapter.discover_urls()
    detail = adapter.parse_detail(adapter.fetch_detail(urls[0]), urls[0])
    audit = adapter.last_discovery_audit

    assert urls == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/456",
    ]
    assert audit.total_pages_fetched == 2
    assert audit.total_urls_discovered == 2
    assert audit.duplicate_urls == 2
    assert [kind.kind for kind in audit.kinds] == ["entreprise", "laboratoire"]
    assert [kind.ui_total for kind in audit.kinds] == [2, 2]
    assert detail.source == "anrt"
    assert detail.source_specific["anrt_kind"] == "entreprise"


def test_anrt_source_adapter_falls_back_to_datatables_inventory() -> None:
    class FakeDatatablesClient:
        def fetch_list_page(self, kind: AnrtKind, use_cache: bool = True) -> str:
            return """
            <html><body>
              <nav><a href="/logout">Déconnexion</a></nav>
              <table id="offreEntrepriseList"></table>
            </body></html>
            """

        def fetch_list_url(self, url: str, use_cache: bool = True) -> str:
            return "<html><body></body></html>"

        def fetch_datatables_page(
            self,
            kind: AnrtKind,
            *,
            start: int = 0,
            length: int = 25,
            draw: int = 1,
            use_cache: bool = True,
        ) -> dict[str, object]:
            assert kind == AnrtKind.ENTREPRISE
            assert start == 0
            assert length == 25
            return {
                "recordsFiltered": 2,
                "data": [
                    {
                        "id": 681,
                        "crypt": "Zmhh",
                        "titre": "Thèse CIFRE deep learning pour protéines",
                        "rs": "Entreprise anonymisée",
                        "entite": "Laboratoire anonymisé",
                        "discipline": "Sciences du numérique",
                        "secteur": "Santé",
                        "ville": "Paris",
                        "pays": "FRANCE",
                        "these": "<p>Deep learning appliqué aux protéines.</p>",
                    },
                    {
                        "id": 3,
                        "crypt": "Yw",
                        "titre": "",
                        "rs": "Laboratoire historique",
                        "these": "",
                    }
                ],
            }

        def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
            raise AssertionError("DataTables rows should be used as detail payloads")

        def offer_cache_path(self, url: str) -> str:
            return f"/tmp/{url.rsplit('/', 1)[-1]}.html"

    adapter = AnrtSourceAdapter(FakeDatatablesClient(), kind=AnrtKind.ENTREPRISE)

    urls = adapter.discover_urls(use_cache=False)
    offer = adapter.parse_detail(adapter.fetch_detail(urls[0], use_cache=False), urls[0])

    assert urls == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre/detail/Zmhh"
    ]
    assert adapter.last_discovery_audit.total_pages_fetched == 2
    assert adapter.last_discovery_audit.total_urls_discovered == 1
    assert adapter.last_discovery_audit.kinds[0].ui_total == 2
    assert offer.reference == "681"
    assert offer.source_specific["crypt"] == "Zmhh"
    assert offer.source_specific["company_name"] == "Entreprise anonymisée"
    assert offer.source_specific["laboratory_name"] == "Laboratoire anonymisé"
    assert "protéines" in offer.title
    assert "Deep learning appliqué" in (offer.description or "")


def test_parse_anrt_datatables_offer_normalizes_laboratory_row() -> None:
    offer = parse_anrt_datatables_offer(
        {
            "id": 682,
            "crypt": "Zmhi",
            "titre": "Apprentissage automatique pour ARN",
            "rs": "Laboratoire anonymisé",
            "sigle": "LAB",
            "discipline": "Sciences biologiques",
            "ville": "Lyon",
            "pays": "FRANCE",
            "creation": "08/07/2026 à 09:42:00",
            "these": "<p>Modèles de deep learning pour ARN.</p>",
        },
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre/detail/Zmhi",
        AnrtKind.LABORATOIRE,
    )

    classified = apply_classification(offer)

    assert classified.source_specific["anrt_kind"] == "laboratoire"
    assert classified.source_specific["laboratory_name"] == "Laboratoire anonymisé"
    assert classified.location == "Lyon, FRANCE"
    assert classified.published_at_text == "08/07/2026 à 09:42:00"
    assert classified.target_bucket == "primary_target"
    assert classified.ai_category == "ml_deep_learning"


def test_source_registry_marks_anrt_as_authenticated_source() -> None:
    assert source_definition("cnrs").requires_auth is False
    assert source_definition("anrt").requires_auth is True

    with pytest.raises(ValueError):
        source_definition("unknown")


def test_anrt_fixture_client_runs_adapter_end_to_end() -> None:
    adapter = AnrtSourceAdapter(AnrtFixtureClient(FIXTURES / "anrt"), kind=AnrtKind.BOTH)

    urls = adapter.discover_urls(use_cache=False)
    offers = [
        apply_classification(adapter.parse_detail(adapter.fetch_detail(url, use_cache=False), url))
        for url in urls
    ]

    assert [offer.reference for offer in offers] == ["CIFRE-2026-123", "CIFRE-2026-456"]
    assert offers[0].target_bucket == "primary_target"
    assert offers[0].source_specific["company_name"] == "Entreprise anonymisée A"
    assert offers[0].source_specific["application_deadline"] == "2026-09-30"
    assert offers[0].published_at_text is None
    assert offers[1].target_bucket == "adjacent_review"
    assert offers[1].source_specific["anrt_kind"] == "laboratoire"


def test_anrt_fixture_client_follows_paginated_list_pages(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "anrt"
    (fixture_dir / "list").mkdir(parents=True)
    (fixture_dir / "detail").mkdir()
    (fixture_dir / "list" / "entreprise.html").write_text(
        """
        <html><body>
          <p>2 offres disponibles</p>
          <a href="/espace-membre/offre-detail/123">Offre 1</a>
          <a href="/espace-membre/offre-list/entreprise?page=2" rel="next">Suivant</a>
        </body></html>
        """,
        encoding="utf-8",
    )
    (fixture_dir / "list" / "laboratoire.html").write_text("<html><body></body></html>")
    (fixture_dir / "list" / "espace-membre-offre-list-entreprise-page-2.html").write_text(
        """
        <html><body>
          <a href="/espace-membre/offre-detail/456">Offre 2</a>
        </body></html>
        """,
        encoding="utf-8",
    )

    adapter = AnrtSourceAdapter(AnrtFixtureClient(fixture_dir), kind=AnrtKind.ENTREPRISE)

    assert adapter.discover_urls(use_cache=False) == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/456",
    ]
    audit = adapter.last_discovery_audit
    assert audit.total_pages_fetched == 2
    assert audit.total_urls_discovered == 2
    assert audit.duplicate_urls == 0
    assert audit.max_pages_reached is False
    assert audit.kinds[0].ui_total == 2


def test_anrt_discovery_audit_reports_max_page_limit(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "anrt"
    (fixture_dir / "list").mkdir(parents=True)
    (fixture_dir / "detail").mkdir()
    (fixture_dir / "list" / "entreprise.html").write_text(
        """
        <html><body>
          <p>2 offres trouvées</p>
          <a href="/espace-membre/offre-detail/123">Offre 1</a>
          <a href="/espace-membre/offre-list/entreprise?page=2" rel="next">Suivant</a>
        </body></html>
        """,
        encoding="utf-8",
    )

    adapter = AnrtSourceAdapter(
        AnrtFixtureClient(fixture_dir),
        kind=AnrtKind.ENTREPRISE,
        max_list_pages=1,
    )

    assert adapter.discover_urls(use_cache=False) == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123"
    ]
    audit = adapter.last_discovery_audit
    assert audit.total_pages_fetched == 1
    assert audit.max_pages_reached is True
    assert audit.kinds[0].max_pages_reached is True


def test_anrt_fixture_anonymizer_masks_contact_details(tmp_path: Path) -> None:
    html = "<p>Contact: jane.doe@example.com / +33 1 23 45 67 89 / 06.11.22.33.44</p>"

    anonymized = anonymize_html(html)

    assert "jane.doe@example.com" not in anonymized
    assert "+33 1 23 45 67 89" not in anonymized
    assert "06.11.22.33.44" not in anonymized
    assert "email-anonymise@example.invalid" in anonymized

    source = tmp_path / "raw"
    output = tmp_path / "fixtures"
    (source / "detail").mkdir(parents=True)
    (source / "detail" / "offer.html").write_text(html, encoding="utf-8")

    count = anonymize_fixture_tree(source, output)

    assert count == 1
    anonymized_offer = (output / "detail" / "offer.html").read_text(encoding="utf-8")
    assert "jane.doe@example.com" not in anonymized_offer
    assert "email-anonymise@example.invalid" in anonymized_offer

    audit = audit_anrt_fixture_tree(output)
    assert audit.contact_leak_files == []


def test_anrt_fixture_audit_accepts_complete_anonymized_fixture_tree() -> None:
    audit = audit_anrt_fixture_tree(FIXTURES / "anrt")

    assert audit.ok is True
    assert audit.missing_list_pages == []
    assert audit.missing_detail_urls == []
    assert audit.contact_leak_files == []
    assert audit.discovered_urls == 2
    assert audit.detail_files == 2


def test_anrt_fixture_audit_reports_missing_details_and_contact_leaks(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "anrt"
    (fixture_dir / "list").mkdir(parents=True)
    (fixture_dir / "detail").mkdir()
    (fixture_dir / "list" / "entreprise.html").write_text(
        """
        <html><body>
          <a href="/espace-membre/offre-detail/123">Offre 1</a>
          <p>Contact: jane.doe@example.com</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    (fixture_dir / "list" / "laboratoire.html").write_text("<html><body></body></html>")

    audit = audit_anrt_fixture_tree(fixture_dir)

    assert audit.ok is False
    assert audit.missing_list_pages == []
    assert audit.detail_files == 0
    assert audit.discovered_urls == 1
    assert audit.missing_detail_urls == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123"
    ]
    assert audit.contact_leak_files == ["list/entreprise.html"]


def test_anrt_login_reports_missing_playwright(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def missing_playwright() -> object:
        raise RuntimeError("Playwright n'est pas installé.")

    monkeypatch.setattr(cli_module, "_load_sync_playwright", missing_playwright)

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-login",
            "--output",
            str(tmp_path / "anrt-cookies.json"),
            "--no-verify",
        ],
        input="\n",
    )

    assert result.exit_code == 2
    assert "Playwright n'est pas installé" in result.output
    assert not (tmp_path / "anrt-cookies.json").exists()


def test_anrt_real_smoke_runs_fixture_pipeline(tmp_path: Path) -> None:
    report = tmp_path / "anrt_smoke.md"
    digest = tmp_path / "anrt_digest.md"
    db = tmp_path / "anrt.sqlite"
    raw_dir = tmp_path / "raw"

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-real-smoke",
            "--anrt-fixture-dir",
            str(FIXTURES / "anrt"),
            "--db",
            str(db),
            "--raw-dir",
            str(raw_dir),
            "--report",
            str(report),
            "--digest-output",
            str(digest),
            "--limit-offers",
            "2",
            "--no-cache",
        ],
    )

    assert result.exit_code == 0, result.output
    report_text = report.read_text(encoding="utf-8")
    digest_text = digest.read_text(encoding="utf-8")
    assert "- Statut : ok" in report_text
    assert "- URLs découvertes : 2" in report_text
    assert "- Offres fetchées : 2" in report_text
    assert '"primary_target": 1' in report_text
    assert "ANRT entreprise" in digest_text
    assert "ANRT laboratoire" in digest_text


def test_anrt_real_smoke_reports_auth_required_without_network(tmp_path: Path) -> None:
    report = tmp_path / "auth_report.md"

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-real-smoke",
            "--anrt-session-file",
            str(tmp_path / "missing-cookies.json"),
            "--db",
            str(tmp_path / "auth.sqlite"),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--report",
            str(report),
            "--digest-output",
            str(tmp_path / "digest.md"),
            "--terms-reviewed",
        ],
    )

    assert result.exit_code == 2
    report_text = report.read_text(encoding="utf-8")
    assert "- Statut : auth_required" in report_text
    assert "- Status run : auth_required" in report_text
    assert "missing-cookies.json" in report_text


def test_anrt_real_smoke_requires_terms_review_for_real_session(tmp_path: Path) -> None:
    report = tmp_path / "terms_report.md"

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-real-smoke",
            "--anrt-session-file",
            str(tmp_path / "cookies.json"),
            "--db",
            str(tmp_path / "terms.sqlite"),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--report",
            str(report),
            "--digest-output",
            str(tmp_path / "digest.md"),
        ],
    )

    assert result.exit_code == 2
    report_text = report.read_text(encoding="utf-8")
    assert "- Statut : terms_review_required" in report_text
    assert "- Status run : terms_review_required" in report_text
    assert "--anrt-terms-reviewed" in report_text


def test_anrt_mvp_audit_passes_with_complete_fixture_evidence(tmp_path: Path) -> None:
    db = tmp_path / "anrt.sqlite"
    digest = tmp_path / "anrt_digest.md"
    smoke_report = tmp_path / "anrt_smoke.md"
    mvp_report = tmp_path / "anrt_mvp.md"

    smoke = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-real-smoke",
            "--anrt-fixture-dir",
            str(FIXTURES / "anrt"),
            "--db",
            str(db),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--report",
            str(smoke_report),
            "--digest-output",
            str(digest),
            "--limit-offers",
            "2",
            "--no-cache",
        ],
    )
    assert smoke.exit_code == 0, smoke.output

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-mvp-audit",
            "--db",
            str(db),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--digest",
            str(digest),
            "--fixture-dir",
            str(FIXTURES / "anrt"),
            "--eval-dataset",
            str(FIXTURES / "evaluation" / "anrt_offers.json"),
            "--output",
            str(mvp_report),
            "--min-offers",
            "2",
            "--min-raw-list-files",
            "0",
            "--min-raw-detail-files",
            "0",
            "--min-eval-cases",
            "20",
        ],
    )

    assert result.exit_code == 0, result.output
    report_text = mvp_report.read_text(encoding="utf-8")
    assert "- Statut : ok" in report_text
    assert "| both_origins_present | ok |" in report_text
    assert "| evaluation_no_missed_targets | ok | 0 |" in report_text


def test_anrt_mvp_audit_fails_when_evidence_is_missing(tmp_path: Path) -> None:
    report = tmp_path / "missing_mvp.md"

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-mvp-audit",
            "--db",
            str(tmp_path / "missing.sqlite"),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--digest",
            str(tmp_path / "missing_digest.md"),
            "--output",
            str(report),
            "--min-offers",
            "2",
        ],
    )

    assert result.exit_code == 1
    report_text = report.read_text(encoding="utf-8")
    assert "- Statut : incomplet" in report_text
    assert "| db_exists | manquant |" in report_text
    assert "| evaluation_dataset_provided | manquant | eval_dataset missing |" in report_text


def test_anrt_export_eval_seed_from_fixture_smoke_db(tmp_path: Path) -> None:
    db = tmp_path / "anrt.sqlite"
    seed = tmp_path / "anrt_seed.json"

    smoke = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-real-smoke",
            "--anrt-fixture-dir",
            str(FIXTURES / "anrt"),
            "--db",
            str(db),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--report",
            str(tmp_path / "smoke.md"),
            "--digest-output",
            str(tmp_path / "digest.md"),
            "--limit-offers",
            "2",
            "--no-cache",
        ],
    )
    assert smoke.exit_code == 0, smoke.output

    result = CliRunner().invoke(
        cli_module.app,
        [
            "anrt-export-eval-seed",
            "--db",
            str(db),
            "--output",
            str(seed),
            "--limit",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    cases = load_evaluation_cases(seed)
    summary = run_evaluation(cases)
    assert len(cases) == 2
    assert cases[0].notes == "TODO: relire et confirmer l'annotation issue du classifieur."
    assert cases[0].offer.source == "anrt"
    assert summary.false_targets == 0
    assert summary.missed_targets == 0
