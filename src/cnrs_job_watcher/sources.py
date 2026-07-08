from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from cnrs_job_watcher.anrt.fetch import ANRT_BASE_URL, AnrtClient, AnrtKind
from cnrs_job_watcher.anrt.parse import (
    parse_anrt_list_page,
    parse_anrt_offer_detail,
    parse_anrt_pagination_urls,
    parse_anrt_result_count,
)
from cnrs_job_watcher.fetch import CnrsClient
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.schemas import JobOffer, ListPageStats


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    display_name: str
    requires_auth: bool = False


@dataclass(frozen=True)
class AnrtKindDiscoveryAudit:
    kind: str
    pages_fetched: int
    urls_discovered: int
    ui_total: int | None = None
    max_pages_reached: bool = False


@dataclass(frozen=True)
class AnrtDiscoveryAudit:
    kinds: tuple[AnrtKindDiscoveryAudit, ...]
    total_pages_fetched: int
    total_urls_discovered: int
    duplicate_urls: int
    max_pages_reached: bool


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

    def __init__(
        self,
        client: AnrtClient,
        kind: AnrtKind = AnrtKind.BOTH,
        max_list_pages: int = 50,
    ) -> None:
        self.client = client
        self.kind = kind
        self.max_list_pages = max_list_pages
        self._detail_kinds: dict[str, AnrtKind] = {}
        self._datatable_rows: dict[str, dict[str, Any]] = {}
        self.last_discovery_audit = AnrtDiscoveryAudit(
            kinds=(),
            total_pages_fetched=0,
            total_urls_discovered=0,
            duplicate_urls=0,
            max_pages_reached=False,
        )

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
        duplicate_urls = 0
        kind_audits: list[AnrtKindDiscoveryAudit] = []
        for kind in self._kinds_to_fetch():
            pages_seen: set[str] = set()
            queued_pages: list[str | None] = [None]
            kind_urls: set[str] = set()
            ui_total: int | None = None
            while queued_pages and len(pages_seen) < self.max_list_pages:
                page_url = queued_pages.pop(0)
                page_key = page_url or f"kind:{kind.value}"
                if page_key in pages_seen:
                    continue
                pages_seen.add(page_key)
                html = (
                    self.client.fetch_list_page(kind, use_cache=use_cache)
                    if page_url is None
                    else self.client.fetch_list_url(page_url, use_cache=use_cache)
                )
                if ui_total is None:
                    ui_total = parse_anrt_result_count(html)
                for url in parse_anrt_list_page(html, kind):
                    kind_urls.add(url)
                    if url in seen:
                        duplicate_urls += 1
                        continue
                    seen.add(url)
                    self._detail_kinds[url] = kind
                    urls.append(url)
                for next_url in parse_anrt_pagination_urls(html):
                    if next_url not in pages_seen and next_url not in queued_pages:
                        queued_pages.append(next_url)
            ajax_pages_fetched = 0
            ajax_max_pages_reached = False
            if not kind_urls and hasattr(self.client, "fetch_datatables_page"):
                (
                    ajax_urls,
                    ajax_total,
                    ajax_pages_fetched,
                    ajax_duplicates,
                    ajax_max_pages_reached,
                ) = self._discover_datatables_urls(
                    kind,
                    seen=seen,
                    use_cache=use_cache,
                )
                duplicate_urls += ajax_duplicates
                kind_urls.update(ajax_urls)
                urls.extend(ajax_urls)
                if ui_total is None:
                    ui_total = ajax_total
            max_pages_reached = bool(
                queued_pages and len(pages_seen) >= self.max_list_pages
            ) or ajax_max_pages_reached
            kind_audits.append(
                AnrtKindDiscoveryAudit(
                    kind=kind.value,
                    pages_fetched=len(pages_seen) + ajax_pages_fetched,
                    urls_discovered=len(kind_urls),
                    ui_total=ui_total,
                    max_pages_reached=max_pages_reached,
                )
            )
        total_pages = sum(audit.pages_fetched for audit in kind_audits)
        self.last_discovery_audit = AnrtDiscoveryAudit(
            kinds=tuple(kind_audits),
            total_pages_fetched=total_pages,
            total_urls_discovered=len(urls),
            duplicate_urls=duplicate_urls,
            max_pages_reached=any(audit.max_pages_reached for audit in kind_audits),
        )
        return urls

    def fetch_detail(self, url: str, use_cache: bool = True) -> str:
        if url in self._datatable_rows:
            return json.dumps({"row": self._datatable_rows[url]}, ensure_ascii=False)
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

    def _discover_datatables_urls(
        self,
        kind: AnrtKind,
        *,
        seen: set[str],
        use_cache: bool,
    ) -> tuple[list[str], int | None, int, int, bool]:
        discovered: list[str] = []
        total: int | None = None
        pages_fetched = 0
        duplicates = 0
        max_pages_reached = False
        length = 25
        for page_index in range(self.max_list_pages):
            start = page_index * length
            payload = self.client.fetch_datatables_page(  # type: ignore[attr-defined]
                kind,
                start=start,
                length=length,
                draw=page_index + 1,
                use_cache=use_cache,
            )
            pages_fetched += 1
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                break
            if total is None:
                total = _int_or_none(payload.get("recordsFiltered")) or _int_or_none(
                    payload.get("recordsTotal")
                )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if not _has_datatable_offer_content(row):
                    continue
                url = _anrt_datatable_detail_url(row)
                if url in seen:
                    duplicates += 1
                    continue
                seen.add(url)
                self._detail_kinds[url] = kind
                self._datatable_rows[url] = row
                discovered.append(url)
            if not rows or (total is not None and start + len(rows) >= total):
                break
        else:
            max_pages_reached = total is None or len(discovered) < total
        return discovered, total, pages_fetched, duplicates, max_pages_reached


def _anrt_datatable_detail_url(row: dict[str, Any]) -> str:
    token = row.get("crypt") or row.get("id")
    return f"{ANRT_BASE_URL}/espace-membre/offre/detail/{token}"


def _has_datatable_offer_content(row: dict[str, Any]) -> bool:
    return bool(str(row.get("titre") or "").strip() or str(row.get("these") or "").strip())


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
