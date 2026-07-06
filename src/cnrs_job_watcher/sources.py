from __future__ import annotations

from typing import Protocol

from cnrs_job_watcher.fetch import CnrsClient
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.schemas import JobOffer, ListPageStats


class SourceAdapter(Protocol):
    source: str

    def discover(
        self,
        page: int = 1,
        use_cache: bool = True,
    ) -> tuple[list[JobOffer], ListPageStats]:
        """Return normalized list-page offers and pagination stats."""

    def fetch_detail(self, url: str, use_cache: bool = True) -> str:
        """Return the raw detail HTML or source-specific payload."""

    def parse_detail(self, payload: str, url: str) -> JobOffer:
        """Normalize a source-specific detail payload into a JobOffer."""

    def discover_urls(self, use_cache: bool = True) -> list[str]:
        """Return canonical detail URLs when the source exposes an inventory."""


class CnrsSourceAdapter:
    source = "cnrs"

    def __init__(self, client: CnrsClient) -> None:
        self.client = client

    def discover(
        self,
        page: int = 1,
        use_cache: bool = True,
    ) -> tuple[list[JobOffer], ListPageStats]:
        html = self.client.fetch_list_page(page, use_cache=use_cache)
        offers, stats = parse_list_page(html)
        return [
            offer.model_copy(update={"source": self.source, "source_specific": {}})
            for offer in offers
        ], stats

    def discover_urls(self, use_cache: bool = True) -> list[str]:
        from cnrs_job_watcher.fetch import parse_offer_sitemap_urls

        return parse_offer_sitemap_urls(self.client.fetch_offer_sitemap(use_cache=use_cache))

    def fetch_detail(self, url: str, use_cache: bool = True) -> str:
        return self.client.fetch_offer_page(url, use_cache=use_cache)

    def parse_detail(self, payload: str, url: str) -> JobOffer:
        offer = parse_offer_detail(payload, url)
        return offer.model_copy(update={"source": self.source})
