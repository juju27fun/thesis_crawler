from __future__ import annotations

import pytest

from cnrs_job_watcher.anrt.fetch import AnrtAuthenticationRequired, AnrtKind
from cnrs_job_watcher.anrt.parse import parse_anrt_list_page, parse_anrt_offer_detail
from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.sources import AnrtSourceAdapter, source_definition

ANRT_LIST_HTML = """
<html>
  <body>
    <h1>Offres entreprise</h1>
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
    class FakeClient:
        def fetch_list_page(self, kind: AnrtKind, use_cache: bool = True) -> str:
            return ANRT_LIST_HTML

        def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
            return ANRT_DETAIL_HTML

        def offer_cache_path(self, url: str) -> str:
            return f"/tmp/{url.rsplit('/', 1)[-1]}.html"

    adapter = AnrtSourceAdapter(FakeClient(), kind=AnrtKind.BOTH)

    urls = adapter.discover_urls()
    detail = adapter.parse_detail(adapter.fetch_detail(urls[0]), urls[0])

    assert urls == [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/123",
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-detail/456",
    ]
    assert detail.source == "anrt"
    assert detail.source_specific["anrt_kind"] == "entreprise"


def test_source_registry_marks_anrt_as_authenticated_source() -> None:
    assert source_definition("cnrs").requires_auth is False
    assert source_definition("anrt").requires_auth is True

    with pytest.raises(ValueError):
        source_definition("unknown")
