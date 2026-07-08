from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from cnrs_job_watcher.text import slugify

ANRT_BASE_URL = "https://offres-et-candidatures-cifre.anrt.asso.fr"


class AnrtKind(StrEnum):
    ENTREPRISE = "entreprise"
    LABORATOIRE = "laboratoire"
    BOTH = "both"


class AnrtAuthenticationRequired(RuntimeError):
    """Raised when ANRT member pages are not reachable with the current session."""


class AnrtClient:
    def __init__(
        self,
        cache_dir: Path = Path("data/raw"),
        session_file: Path | None = None,
        delay_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.session_file = session_file
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": "cnrs-job-watcher/0.1 (+local CIFRE monitoring)"},
        )
        if session_file:
            try:
                self._load_session_file(session_file)
            except Exception:
                self.client.close()
                raise

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> AnrtClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_list_page(self, kind: AnrtKind, use_cache: bool = True) -> str:
        if kind == AnrtKind.BOTH:
            raise ValueError("fetch_list_page expects entreprise or laboratoire, not both")
        url = f"{ANRT_BASE_URL}/espace-membre/offre-list/{kind.value}"
        return self.fetch_list_url(url, use_cache=use_cache)

    def fetch_list_url(self, url: str, use_cache: bool = True) -> str:
        cache_path = self.list_cache_path(url)
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        response = self._request("GET", url)
        html = response.text
        if is_logged_out_page(html, str(response.url)):
            raise AnrtAuthenticationRequired(
                "ANRT session required: member offer list redirected to login/logout."
            )
        _write_snapshot(cache_path, html)
        time.sleep(self.delay_seconds)
        return html

    def list_cache_path(self, url: str) -> Path:
        filename = f"{slugify(url.replace(ANRT_BASE_URL, ''))}.html"
        return self.cache_dir / "anrt" / "list" / filename

    def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
        cache_path = self.offer_cache_path(url)
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        response = self._request("GET", url)
        html = response.text
        if is_logged_out_page(html, str(response.url)):
            raise AnrtAuthenticationRequired(
                "ANRT session required: detail page redirected to login/logout."
            )
        _write_snapshot(cache_path, html)
        time.sleep(self.delay_seconds)
        return html

    def offer_cache_path(self, url: str) -> Path:
        filename = f"{slugify(url.replace(ANRT_BASE_URL, ''))}.html"
        return self.cache_dir / "anrt" / "detail" / filename

    def _load_session_file(self, session_file: Path) -> None:
        if not session_file.exists():
            raise AnrtAuthenticationRequired(f"ANRT session file not found: {session_file}")
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AnrtAuthenticationRequired(
                f"ANRT session file is not valid JSON: {session_file}"
            ) from exc
        cookies = _extract_session_cookies(data)
        loaded_count = 0
        for cookie in cookies:
            if not _is_usable_cookie(cookie):
                continue
            self.client.cookies.set(
                str(cookie["name"]),
                str(cookie["value"]),
                domain=_cookie_domain(cookie),
                path=str(cookie.get("path") or "/"),
            )
            loaded_count += 1
        if loaded_count == 0:
            raise AnrtAuthenticationRequired(
                "ANRT session file contains no usable cookies. "
                "Expected a Playwright storage_state JSON or a JSON cookies list."
            )

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                if _is_auth_redirect(exc):
                    raise AnrtAuthenticationRequired(
                        "ANRT session required: member page returned login/logout status."
                    ) from exc
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise
                time.sleep(self.backoff_seconds * (attempt + 1))
        raise RuntimeError("unreachable retry state") from last_error


def is_logged_out_page(html: str, final_url: str = "") -> bool:
    text = html.lower()
    url = final_url.lower()
    return (
        "/logout" in url
        or "/deconnexion" in url
        or "déconnexion" in text
        or "deconnexion" in text
        or "merci de votre visite" in text
    )


def _cookie_domain(cookie: dict[str, Any]) -> str:
    domain = str(cookie.get("domain") or "offres-et-candidatures-cifre.anrt.asso.fr")
    return domain.lstrip(".")


def _extract_session_cookies(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        return data["cookies"]
    raise AnrtAuthenticationRequired("ANRT session file must contain a cookies list.")


def _is_usable_cookie(cookie: Any) -> bool:
    return (
        isinstance(cookie, dict)
        and isinstance(cookie.get("name"), str)
        and bool(cookie["name"])
        and cookie.get("value") is not None
    )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def _is_auth_redirect(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    url = str(exc.response.url).lower()
    return exc.response.status_code in {401, 403} and (
        "/logout" in url or "/deconnexion" in url or "/login" in url
    )


def _write_snapshot(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


class AnrtFixtureClient:
    """Read ANRT list/detail pages from an anonymized local fixture directory."""

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    def close(self) -> None:
        return None

    def __enter__(self) -> AnrtFixtureClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_list_page(self, kind: AnrtKind, use_cache: bool = True) -> str:
        del use_cache
        if kind == AnrtKind.BOTH:
            raise ValueError("fetch_list_page expects entreprise or laboratoire, not both")
        path = self.fixture_dir / "list" / f"{kind.value}.html"
        if not path.exists():
            raise FileNotFoundError(f"ANRT fixture list page not found: {path}")
        return path.read_text(encoding="utf-8")

    def fetch_list_url(self, url: str, use_cache: bool = True) -> str:
        del use_cache
        path = self.list_cache_path(url)
        if not path.exists():
            raise FileNotFoundError(f"ANRT fixture list page not found: {path}")
        return path.read_text(encoding="utf-8")

    def fetch_offer_page(self, url: str, use_cache: bool = True) -> str:
        del use_cache
        path = self.offer_cache_path(url)
        if not path.exists():
            raise FileNotFoundError(f"ANRT fixture detail page not found: {path}")
        return path.read_text(encoding="utf-8")

    def offer_cache_path(self, url: str) -> Path:
        filename = f"{slugify(url.replace(ANRT_BASE_URL, ''))}.html"
        return self.fixture_dir / "detail" / filename

    def list_cache_path(self, url: str) -> Path:
        filename = f"{slugify(url.replace(ANRT_BASE_URL, ''))}.html"
        return self.fixture_dir / "list" / filename
