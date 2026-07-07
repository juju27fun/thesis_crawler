from __future__ import annotations

from bs4 import BeautifulSoup

from cnrs_job_watcher.anrt.fetch import ANRT_BASE_URL, AnrtAuthenticationRequired, AnrtKind
from cnrs_job_watcher.schemas import JobOffer


def parse_anrt_list_page(html: str, kind: AnrtKind) -> list[str]:
    _ensure_not_logged_out(html)
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not _looks_like_offer_href(href):
            continue
        url = _absolute_url(href)
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def parse_anrt_offer_detail(html: str, url: str, kind: AnrtKind) -> JobOffer:
    _ensure_not_logged_out(html)
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text("\n", strip=True)

    title = _first_text(
        soup,
        [
            "[data-field='title']",
            ".offer-title",
            ".offre-title",
            "h1",
            "h2",
        ],
    )
    if not title:
        raise ValueError("ANRT offer title not found")

    source_specific = {
        "anrt_kind": kind.value,
    }
    company = _field_text(soup, ["Entreprise", "Société", "Structure", "Organisation"])
    laboratory = _field_text(soup, ["Laboratoire", "Unité", "Equipe", "Équipe"])
    sector = _field_text(soup, ["Secteur", "Domaine", "Discipline"])
    deadline = _field_text(soup, ["Date limite", "Clôture", "Deadline"])
    if company:
        source_specific["company_name"] = company
    if laboratory:
        source_specific["laboratory_name"] = laboratory
    if sector:
        source_specific["sector"] = sector
    if deadline:
        source_specific["application_deadline"] = deadline

    description = _section_text(soup, ["Description", "Sujet", "Projet", "Contexte"])
    skills = _section_text(soup, ["Profil", "Compétences", "Competences", "Candidat"])
    location = _field_text(soup, ["Lieu", "Localisation", "Ville"])
    published_at = _field_text(soup, ["Publication", "Publié", "Publiée", "Date"])
    reference = _field_text(soup, ["Référence", "Reference", "Identifiant", "ID"])

    lab = laboratory or company
    if kind == AnrtKind.ENTREPRISE and company:
        lab = company

    return JobOffer(
        source="anrt",
        source_specific=source_specific,
        url=_absolute_url(url),
        reference=reference or _reference_from_url(url),
        title=title,
        contract_type="CIFRE",
        duration=_field_text(soup, ["Durée", "Duree"]) or "36 mois",
        education_level=_field_text(soup, ["Niveau", "Diplôme", "Diplome"]) or "BAC+5 / Master",
        location=location,
        lab=lab,
        published_at_text=published_at,
        description=description,
        skills=skills,
        raw_text=raw_text,
    )


def _ensure_not_logged_out(html: str) -> None:
    text = html.lower()
    if "déconnexion" in text or "deconnexion" in text or "merci de votre visite" in text:
        raise AnrtAuthenticationRequired("ANRT page is logged out.")


def _looks_like_offer_href(href: str) -> bool:
    normalized = href.lower()
    if not normalized or normalized.startswith("#"):
        return False
    if "offre-list" in normalized:
        return False
    return "offre" in normalized and (
        "detail" in normalized
        or "show" in normalized
        or "fiche" in normalized
        or "/offre/" in normalized
        or "/offre-detail/" in normalized
    )


def _absolute_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"{ANRT_BASE_URL}{href}"
    return f"{ANRT_BASE_URL}/{href}"


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = element.get_text(" ", strip=True)
            if text:
                return text
    return None


def _field_text(soup: BeautifulSoup, labels: list[str]) -> str | None:
    for label in labels:
        direct = soup.select_one(f"[data-field='{label.lower()}']")
        if direct:
            text = direct.get_text(" ", strip=True)
            if text:
                return text

        label_lower = label.lower()
        for element in soup.find_all(
            string=lambda value, needle=label_lower: bool(value and needle in value.lower())
        ):
            parent = element.parent
            if parent is None:
                continue
            value = _value_near_label(parent, label)
            if value:
                return value
    return None


def _value_near_label(parent: object, label: str) -> str | None:
    text = parent.get_text(" ", strip=True) if hasattr(parent, "get_text") else ""
    if ":" in text:
        before, after = text.split(":", 1)
        if label.lower() in before.lower() and after.strip():
            return after.strip()
    next_sibling = getattr(parent, "find_next_sibling", lambda *_: None)()
    if next_sibling:
        value = next_sibling.get_text(" ", strip=True)
        if value:
            return value
    return None


def _section_text(soup: BeautifulSoup, labels: list[str]) -> str | None:
    for label in labels:
        selector = f"[data-section='{label.lower()}']"
        section = soup.select_one(selector)
        if section:
            text = section.get_text(" ", strip=True)
            if text:
                return text

        label_lower = label.lower()
        heading = soup.find(lambda tag, needle=label_lower: _is_section_heading(tag, needle))
        if heading:
            parts: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h2", "h3", "h4"}:
                    break
                text = sibling.get_text(" ", strip=True)
                if text:
                    parts.append(text)
            if parts:
                return " ".join(parts)
    return None


def _reference_from_url(url: str) -> str | None:
    cleaned = url.rstrip("/").split("/")[-1]
    return cleaned or None


def _is_section_heading(tag: object, needle: str) -> bool:
    if not hasattr(tag, "name") or not hasattr(tag, "get_text"):
        return False
    return tag.name in {"h2", "h3", "h4"} and needle in tag.get_text(" ", strip=True).lower()
