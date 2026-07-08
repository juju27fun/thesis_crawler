from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from cnrs_job_watcher.anrt.fetch import ANRT_BASE_URL, AnrtKind
from cnrs_job_watcher.anrt.parse import parse_anrt_list_page
from cnrs_job_watcher.text import slugify

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?:(?:\+|00)33[\s.-]?(?:\(0\)[\s.-]?)?|0)[1-9](?:[\s.-]?\d{2}){4}"
)


@dataclass(frozen=True)
class AnrtFixtureAudit:
    fixture_dir: str
    list_pages_present: list[str]
    missing_list_pages: list[str]
    detail_files: int
    discovered_urls: int
    missing_detail_urls: list[str]
    contact_leak_files: list[str]

    @property
    def ok(self) -> bool:
        return (
            not self.missing_list_pages
            and not self.missing_detail_urls
            and not self.contact_leak_files
        )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def anonymize_html(html: str) -> str:
    html = EMAIL_RE.sub("email-anonymise@example.invalid", html)
    html = PHONE_RE.sub("00 00 00 00 00", html)
    return html


def anonymize_fixture_tree(input_dir: Path, output_dir: Path) -> int:
    count = 0
    for source_path in input_dir.rglob("*.html"):
        relative = source_path.relative_to(input_dir)
        target_path = output_dir / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            anonymize_html(source_path.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        count += 1
    return count


def audit_anrt_fixture_tree(fixture_dir: Path) -> AnrtFixtureAudit:
    list_dir = fixture_dir / "list"
    detail_dir = fixture_dir / "detail"
    list_pages_present: list[str] = []
    missing_list_pages: list[str] = []
    discovered_urls: list[str] = []

    for kind in [AnrtKind.ENTREPRISE, AnrtKind.LABORATOIRE]:
        path = list_dir / f"{kind.value}.html"
        if not path.exists():
            missing_list_pages.append(str(path.relative_to(fixture_dir)))
            continue
        list_pages_present.append(str(path.relative_to(fixture_dir)))
        discovered_urls.extend(parse_anrt_list_page(path.read_text(encoding="utf-8"), kind))

    missing_detail_urls = [
        url
        for url in sorted(set(discovered_urls))
        if not _fixture_detail_path(fixture_dir, url).exists()
    ]
    contact_leak_files = [
        str(path.relative_to(fixture_dir))
        for path in sorted(fixture_dir.rglob("*.html"))
        if _contains_contact_leak(path.read_text(encoding="utf-8"))
    ]

    return AnrtFixtureAudit(
        fixture_dir=str(fixture_dir),
        list_pages_present=list_pages_present,
        missing_list_pages=missing_list_pages,
        detail_files=len(list(detail_dir.glob("*.html"))) if detail_dir.exists() else 0,
        discovered_urls=len(set(discovered_urls)),
        missing_detail_urls=missing_detail_urls,
        contact_leak_files=contact_leak_files,
    )


def _fixture_detail_path(fixture_dir: Path, url: str) -> Path:
    filename = f"{slugify(url.replace(ANRT_BASE_URL, ''))}.html"
    return fixture_dir / "detail" / filename


def _contains_contact_leak(html: str) -> bool:
    return EMAIL_RE.search(html) is not None or PHONE_RE.search(html) is not None
