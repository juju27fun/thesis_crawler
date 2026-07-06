from __future__ import annotations

import time
from pathlib import Path

import httpx

from cnrs_job_watcher.text import slugify

BASE_URL = "https://emploi.cnrs.fr"
SEARCH_URL = f"{BASE_URL}/Offres/Recherche.aspx"


class CnrsClient:
    def __init__(
        self,
        cache_dir: Path = Path("data/raw"),
        delay_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_seconds = delay_seconds
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
            response = self.client.get(SEARCH_URL, params={"lang": "FR"})
        else:
            response = self.client.post(SEARCH_URL, data={"Page": str(page)})
        response.raise_for_status()
        html = response.text
        _write_snapshot(cache_path, html)
        time.sleep(self.delay_seconds)
        return html

    def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
        cache_path = self.cache_dir / "offers" / f"{slugify(url.replace(BASE_URL, ''))}.html"
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        response = self.client.get(url, params={"lang": "FR"} if "?" not in url else None)
        response.raise_for_status()
        html = response.text
        _write_snapshot(cache_path, html)
        time.sleep(self.delay_seconds)
        return html


def _write_snapshot(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
