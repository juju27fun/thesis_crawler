from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from cnrs_job_watcher.schemas import JobOffer, ListPageStats
from cnrs_job_watcher.text import clean_text

BASE_URL = "https://emploi.cnrs.fr"


def parse_list_page(html: str, base_url: str = BASE_URL) -> tuple[list[JobOffer], ListPageStats]:
    soup = BeautifulSoup(html, "html.parser")
    offers: list[JobOffer] = []

    for card in soup.select("div.card.card-shadow"):
        link = card.select_one("h3 a[href*='/Offres/']")
        if not link:
            continue
        href = link.get("href", "")
        if "Recherche.aspx" in href:
            continue

        labels = [clean_text(label.get_text(" ")) for label in card.select("li.label span")]
        contract_type, duration, education = _split_labels(labels)
        meta = card.select_one(".meta")
        lab_node = meta.select_one("strong") if meta else None
        lab = clean_text(lab_node.get_text(" ")) if lab_node else None
        location = _extract_location(meta)
        published_node = card.select_one(".post-meta .maj")
        published = clean_text(published_node.get_text(" ")) if published_node else None

        offers.append(
            JobOffer(
                url=urljoin(base_url, href),
                title=clean_text(link.get_text(" ")),
                contract_type=contract_type,
                duration=duration,
                education_level=education,
                location=location,
                lab=lab,
                published_at_text=published,
                raw_text=clean_text(card.get_text(" ")),
            )
        )

    return offers, parse_list_stats(soup)


def parse_list_stats(soup: BeautifulSoup) -> ListPageStats:
    total_offers = None
    total_pages = None

    total_node = soup.select_one(".section-grey p.big strong")
    total_text = clean_text(total_node.get_text(" ")) if total_node else ""
    match = re.search(r"(\d+)", total_text.replace(" ", ""))
    if match:
        total_offers = int(match.group(1))

    page_numbers: list[int] = []
    pagination_selector = "nav[aria-label*='Pagination'] a, nav[aria-label*='Pagination'] li.active"
    for item in soup.select(pagination_selector):
        match = re.search(r"\b(\d+)\b", clean_text(item.get_text(" ")))
        if match:
            page_numbers.append(int(match.group(1)))
    if page_numbers:
        total_pages = max(page_numbers)

    return ListPageStats(total_offers=total_offers, total_pages=total_pages)


def parse_offer_detail(html: str, url: str) -> JobOffer:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" "))
    lower_text = page_text.lower()
    unavailable = (
        "offre demandée n’est plus disponible" in lower_text
        or "requested offer is no longer available" in lower_text
    )

    title_node = soup.select_one("article h1")
    title = clean_text(title_node.get_text(" ")) if title_node else "Offre CNRS indisponible"
    header = soup.select_one("article .post-header")
    labels = [
        clean_text(label.get_text(" "))
        for label in soup.select("article .post-header li.label span")
    ]
    contract_type, duration, education = _split_labels(labels)
    lab = _text_or_none(header.select_one(".meta strong") if header else None)
    location = _extract_location(header.select_one(".meta") if header else None)

    facts = _extract_quick_facts(soup)
    reference = _extract_table_value(soup, "Référence de l’offre")
    description_node = soup.select_one("#CphMain_FullOfferDisplay_Description")
    description = clean_text(description_node.get_text(" ")) if description_node else None
    sections = _extract_sections(description_node) if description_node else {}
    skills = (
        _first_section(sections, ["compétences", "votre profil", "profil"])
    )
    published = _text_or_none(soup.select_one("article .post-meta .maj"))
    source_specific = {
        "quick_facts": facts,
        "sections": sections,
        "application_deadline": _pick_fact(
            facts,
            ["Date limite de candidature", "Date de clôture", "Date limite"],
        ),
        "start_date": _pick_fact(
            facts,
            ["Date d'embauche prévue", "Date de début", "Début du contrat"],
        ),
        "salary": _pick_fact(facts, ["Rémunération", "Salaire"]),
    }

    return JobOffer(
        url=url,
        reference=reference,
        title=title,
        contract_type=facts.get("Type de Contrat") or contract_type,
        duration=facts.get("Durée du contrat") or duration,
        education_level=education,
        location=facts.get("Lieu de Travail") or location,
        lab=facts.get("L'unité") or lab,
        published_at_text=published,
        description=description,
        skills=skills,
        raw_text=page_text,
        unavailable=unavailable,
        source_specific={key: value for key, value in source_specific.items() if value},
    )


def _split_labels(labels: list[str]) -> tuple[str | None, str | None, str | None]:
    contract_type = labels[0] if labels else None
    duration = next((label for label in labels[1:] if "mois" in label.lower()), None)
    education = next((label for label in labels[1:] if "bac" in label.lower()), None)
    return contract_type, duration, education


def _extract_location(meta: Tag | None) -> str | None:
    if not meta:
        return None
    for paragraph in meta.select("p"):
        if paragraph.select_one("strong"):
            continue
        text = clean_text(paragraph.get_text(" "))
        if text:
            return text
    return None


def _extract_quick_facts(soup: BeautifulSoup) -> dict[str, str]:
    facts: dict[str, str] = {}
    for heading in soup.select(".card-dark h3"):
        label = clean_text(heading.get_text(" "))
        value_node = heading.find_next_sibling("p")
        value = clean_text(value_node.get_text(" ")) if value_node else ""
        if label and value:
            facts[label] = value
    return facts


def _extract_table_value(soup: BeautifulSoup, label: str) -> str | None:
    for row in soup.select("tr"):
        header = row.select_one("th")
        cell = row.select_one("td")
        if header and cell and clean_text(header.get_text(" ")) == label:
            return clean_text(cell.get_text(" "))
    return None


def _extract_section_after_heading(root: Tag, headings: list[str]) -> str | None:
    for heading in root.select("h2, h3"):
        heading_text = clean_text(heading.get_text(" ")).lower()
        if not any(candidate.lower() in heading_text for candidate in headings):
            continue
        chunks: list[str] = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}:
                break
            text = (
                clean_text(sibling.get_text(" "))
                if isinstance(sibling, Tag)
                else clean_text(str(sibling))
            )
            if text:
                chunks.append(text)
        return clean_text(" ".join(chunks)) or None
    return None


def _extract_sections(root: Tag) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in root.select("h2, h3"):
        heading_text = clean_text(heading.get_text(" "))
        if not heading_text:
            continue
        chunks: list[str] = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}:
                break
            text = (
                clean_text(sibling.get_text(" "))
                if isinstance(sibling, Tag)
                else clean_text(str(sibling))
            )
            if text:
                chunks.append(text)
        section_text = clean_text(" ".join(chunks))
        if section_text:
            sections[heading_text] = section_text
    return sections


def _first_section(sections: dict[str, str], headings: list[str]) -> str | None:
    for section_heading, section_text in sections.items():
        normalized = section_heading.lower()
        if any(candidate.lower() in normalized for candidate in headings):
            return section_text
    return None


def _pick_fact(facts: dict[str, str], labels: list[str]) -> str | None:
    normalized = {key.lower(): value for key, value in facts.items()}
    for label in labels:
        value = normalized.get(label.lower())
        if value:
            return value
    return None


def _text_or_none(node: Tag | None) -> str | None:
    if not node:
        return None
    return clean_text(node.get_text(" ")) or None
