from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from cnrs_job_watcher.text import slugify

BASE_URL = "https://emploi.cnrs.fr"
SEARCH_URL = f"{BASE_URL}/Offres/Recherche.aspx"
OFFERS_SITEMAP_URL = f"{BASE_URL}/Sitemaps/OffresSiteMapProviderResult.ashx"
TARGET_OFFER_PATHS = ("/Offres/Doctorant/", "/Offres/CDD/")


class CnrsClient:
    def __init__(
        self,
        cache_dir: Path = Path("data/raw"),
        delay_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": "cnrs-job-watcher/0.1 (+public research job monitoring)"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> CnrsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_list_page(self, page: int = 1, use_cache: bool = True) -> str:
        cache_path = self.cache_dir / "list" / f"page-{page}.html"
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        if page <= 1:
            response = self._request("GET", SEARCH_URL, params={"lang": "FR"})
        else:
            response = self._request("POST", SEARCH_URL, data={"Page": str(page)})
        html = response.text
        _write_snapshot(cache_path, html)
        time.sleep(self.delay_seconds)
        return html

    def fetch_offer_sitemap(self, use_cache: bool = True) -> str:
        cache_path = self.cache_dir / "sitemap" / "offers.xml"
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        response = self._request("GET", OFFERS_SITEMAP_URL)
        xml = response.text
        _write_snapshot(cache_path, xml)
        time.sleep(self.delay_seconds)
        return xml

    def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
        cache_path = self.offer_cache_path(url)
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        response = self._request("GET", url, params={"lang": "FR"} if "?" not in url else None)
        html = response.text
        _write_snapshot(cache_path, html)
        time.sleep(self.delay_seconds)
        return html

    def offer_cache_path(self, url: str) -> Path:
        return self.cache_dir / "offers" / f"{slugify(url.replace(BASE_URL, ''))}.html"

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise
                time.sleep(self.backoff_seconds * (attempt + 1))
        raise RuntimeError("unreachable retry state") from last_error


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def _write_snapshot(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def parse_offer_sitemap_urls(
    xml: str,
    include_paths: tuple[str, ...] = TARGET_OFFER_PATHS,
) -> list[str]:
    """Extract public CNRS offer URLs from the sitemap.

    The CNRS sitemap sometimes emits loc values without a scheme, so URLs are
    normalized before filtering.
    """
    root = ET.fromstring(xml.lstrip("\ufeff"))
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: list[str] = []
    seen: set[str] = set()

    for loc in root.findall(".//sm:loc", namespace):
        if loc.text is None:
            continue
        url = _normalize_cnrs_url(loc.text.strip())
        if not any(path in url for path in include_paths):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _normalize_cnrs_url(url: str) -> str:
    if url.startswith("https://") or url.startswith("http://"):
        return url
    if url.startswith("emploi.cnrs.fr"):
        return f"https://{url}"
    if url.startswith("/"):
        return f"{BASE_URL}{url}"
    return url
