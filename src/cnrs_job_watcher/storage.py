from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from cnrs_job_watcher.schemas import JobOffer


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    initialize(connection)
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS offers (
            url TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            reference TEXT,
            title TEXT NOT NULL,
            contract_type TEXT,
            duration TEXT,
            education_level TEXT,
            experience_level TEXT,
            location TEXT,
            lab TEXT,
            published_at_text TEXT,
            description TEXT,
            skills TEXT,
            raw_text TEXT NOT NULL,
            unavailable INTEGER NOT NULL DEFAULT 0,
            hard_filter_passed INTEGER NOT NULL DEFAULT 0,
            ai_relevance_score REAL,
            ai_category TEXT,
            ai_reason TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_offers_score ON offers(ai_relevance_score)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_offers_reference ON offers(reference)")
    connection.commit()


def upsert_offer(connection: sqlite3.Connection, offer: JobOffer) -> None:
    now = datetime.now(UTC).isoformat()
    payload = offer.model_dump(mode="json")
    payload["url"] = str(offer.url)
    payload["unavailable"] = int(offer.unavailable)
    payload["hard_filter_passed"] = int(offer.hard_filter_passed)
    payload["last_seen_at"] = now

    connection.execute(
        """
        INSERT INTO offers (
            url, source, reference, title, contract_type, duration, education_level,
            experience_level, location, lab, published_at_text, description, skills,
            raw_text, unavailable, hard_filter_passed, ai_relevance_score, ai_category,
            ai_reason, first_seen_at, last_seen_at
        ) VALUES (
            :url, :source, :reference, :title, :contract_type, :duration, :education_level,
            :experience_level, :location, :lab, :published_at_text, :description, :skills,
            :raw_text, :unavailable, :hard_filter_passed, :ai_relevance_score, :ai_category,
            :ai_reason, :first_seen_at, :last_seen_at
        )
        ON CONFLICT(url) DO UPDATE SET
            reference = excluded.reference,
            title = excluded.title,
            contract_type = excluded.contract_type,
            duration = excluded.duration,
            education_level = excluded.education_level,
            experience_level = excluded.experience_level,
            location = excluded.location,
            lab = excluded.lab,
            published_at_text = excluded.published_at_text,
            description = excluded.description,
            skills = excluded.skills,
            raw_text = excluded.raw_text,
            unavailable = excluded.unavailable,
            hard_filter_passed = excluded.hard_filter_passed,
            ai_relevance_score = excluded.ai_relevance_score,
            ai_category = excluded.ai_category,
            ai_reason = excluded.ai_reason,
            last_seen_at = excluded.last_seen_at
        """,
        payload,
    )
    connection.commit()


def shortlist(connection: sqlite3.Connection, min_score: float = 0.35) -> list[JobOffer]:
    rows = connection.execute(
        """
        SELECT * FROM offers
        WHERE unavailable = 0
          AND hard_filter_passed = 1
          AND COALESCE(ai_relevance_score, 0) >= ?
        ORDER BY ai_relevance_score DESC, title ASC
        """,
        (min_score,),
    ).fetchall()
    return [_row_to_offer(row) for row in rows]


def all_offers(connection: sqlite3.Connection) -> Iterable[JobOffer]:
    rows = connection.execute("SELECT * FROM offers ORDER BY last_seen_at DESC").fetchall()
    return [_row_to_offer(row) for row in rows]


def _row_to_offer(row: sqlite3.Row) -> JobOffer:
    data = dict(row)
    data["url"] = row["url"]
    data["unavailable"] = bool(row["unavailable"])
    data["hard_filter_passed"] = bool(row["hard_filter_passed"])
    return JobOffer.model_validate(data)
