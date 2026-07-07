from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cnrs_job_watcher.anrt.fetch import AnrtClient, AnrtKind
from cnrs_job_watcher.anrt.parse import parse_anrt_list_page, parse_anrt_offer_detail
from cnrs_job_watcher.fetch import CnrsClient
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.schemas import JobOffer, ListPageStats


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    display_name: str
    requires_auth: bool = False


SOURCE_REGISTRY: dict[str, SourceDefinition] = {
    "cnrs": SourceDefinition(name="cnrs", display_name="CNRS"),
    "anrt": SourceDefinition(name="anrt", display_name="ANRT/CIFRE", requires_auth=True),
}


def source_definition(source: str) -> SourceDefinition:
    try:
        return SOURCE_REGISTRY[source]
    except KeyError as exc:
        raise ValueError(f"Unknown source: {source}") from exc


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

    def snapshot_path(self, url: str) -> str | None:
        """Return the local raw snapshot path for a detail URL when available."""


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

    def snapshot_path(self, url: str) -> str | None:
        return str(self.client.offer_cache_path(url))


class AnrtSourceAdapter:
    source = "anrt"

    def __init__(self, client: AnrtClient, kind: AnrtKind = AnrtKind.BOTH) -> None:
        self.client = client
        self.kind = kind
        self._detail_kinds: dict[str, AnrtKind] = {}

    def discover(
        self,
        page: int = 1,
        use_cache: bool = True,
    ) -> tuple[list[JobOffer], ListPageStats]:
        del page, use_cache
        raise NotImplementedError("ANRT discovery exposes detail URLs, not normalized list cards.")

    def discover_urls(self, use_cache: bool = True) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for kind in self._kinds_to_fetch():
            html = self.client.fetch_list_page(kind, use_cache=use_cache)
            for url in parse_anrt_list_page(html, kind):
                if url in seen:
                    continue
                seen.add(url)
                self._detail_kinds[url] = kind
                urls.append(url)
        return urls

    def fetch_detail(self, url: str, use_cache: bool = True) -> str:
        return self.client.fetch_offer_page(url, use_cache=use_cache)

    def parse_detail(self, payload: str, url: str) -> JobOffer:
        kind = self._detail_kinds.get(url)
        if kind is None:
            kind = self.kind if self.kind != AnrtKind.BOTH else AnrtKind.ENTREPRISE
        return parse_anrt_offer_detail(payload, url, kind)

    def snapshot_path(self, url: str) -> str | None:
        return str(self.client.offer_cache_path(url))

    def _kinds_to_fetch(self) -> list[AnrtKind]:
        if self.kind == AnrtKind.BOTH:
            return [AnrtKind.ENTREPRISE, AnrtKind.LABORATOIRE]
        return [self.kind]
