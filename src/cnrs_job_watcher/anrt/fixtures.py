from __future__ import annotations

import re
from pathlib import Path

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?:(?:\+|00)33[\s.-]?(?:\(0\)[\s.-]?)?|0)[1-9](?:[\s.-]?\d{2}){4}"
)


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
