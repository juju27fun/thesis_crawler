from __future__ import annotations

import json
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
            is_target INTEGER NOT NULL DEFAULT 0,
            target_bucket TEXT NOT NULL DEFAULT 'exclude',
            accessibility TEXT NOT NULL DEFAULT 'unclear',
            exclusion_reason TEXT,
            short_summary TEXT,
            risk_flags TEXT NOT NULL DEFAULT '[]',
            classifier_version TEXT NOT NULL DEFAULT 'rules-v1',
            ai_relevance_score REAL,
            ai_category TEXT,
            ai_reason TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    _add_missing_columns(connection)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_offers_score ON offers(ai_relevance_score)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_offers_reference ON offers(reference)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_target ON offers(is_target, target_bucket)"
    )
    connection.commit()


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(offers)").fetchall()
    }
    columns = {
        "is_target": "INTEGER NOT NULL DEFAULT 0",
        "target_bucket": "TEXT NOT NULL DEFAULT 'exclude'",
        "accessibility": "TEXT NOT NULL DEFAULT 'unclear'",
        "exclusion_reason": "TEXT",
        "short_summary": "TEXT",
        "risk_flags": "TEXT NOT NULL DEFAULT '[]'",
        "classifier_version": "TEXT NOT NULL DEFAULT 'rules-v1'",
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE offers ADD COLUMN {name} {definition}")


def upsert_offer(connection: sqlite3.Connection, offer: JobOffer) -> None:
    now = datetime.now(UTC).isoformat()
    payload = offer.model_dump(mode="json")
    payload["url"] = str(offer.url)
    payload["unavailable"] = int(offer.unavailable)
    payload["hard_filter_passed"] = int(offer.hard_filter_passed)
    payload["is_target"] = int(offer.is_target)
    payload["risk_flags"] = json.dumps(offer.risk_flags, ensure_ascii=False)
    payload["last_seen_at"] = now

    connection.execute(
        """
        INSERT INTO offers (
            url, source, reference, title, contract_type, duration, education_level,
            experience_level, location, lab, published_at_text, description, skills,
            raw_text, unavailable, hard_filter_passed, is_target, target_bucket,
            accessibility, exclusion_reason, short_summary, risk_flags, classifier_version,
            ai_relevance_score, ai_category, ai_reason, first_seen_at, last_seen_at
        ) VALUES (
            :url, :source, :reference, :title, :contract_type, :duration, :education_level,
            :experience_level, :location, :lab, :published_at_text, :description, :skills,
            :raw_text, :unavailable, :hard_filter_passed, :is_target, :target_bucket,
            :accessibility, :exclusion_reason, :short_summary, :risk_flags, :classifier_version,
            :ai_relevance_score, :ai_category, :ai_reason, :first_seen_at, :last_seen_at
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
            is_target = excluded.is_target,
            target_bucket = excluded.target_bucket,
            accessibility = excluded.accessibility,
            exclusion_reason = excluded.exclusion_reason,
            short_summary = excluded.short_summary,
            risk_flags = excluded.risk_flags,
            classifier_version = excluded.classifier_version,
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
          AND is_target = 1
          AND COALESCE(ai_category, '') != 'not_relevant'
          AND COALESCE(ai_relevance_score, 0) >= ?
        ORDER BY
          CASE target_bucket
            WHEN 'primary_target' THEN 1
            WHEN 'secondary_target' THEN 2
            WHEN 'adjacent_review' THEN 3
            ELSE 4
          END,
          ai_relevance_score DESC,
          title ASC
        """,
        (min_score,),
    ).fetchall()
    return [_row_to_offer(row) for row in rows]


def audit_counts(connection: sqlite3.Connection) -> dict[str, object]:
    total = connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    unavailable = connection.execute(
        "SELECT COUNT(*) FROM offers WHERE unavailable = 1"
    ).fetchone()[0]
    by_bucket = {
        row["target_bucket"]: row["count"]
        for row in connection.execute(
            """
            SELECT target_bucket, COUNT(*) AS count
            FROM offers
            GROUP BY target_bucket
            ORDER BY count DESC
            """
        ).fetchall()
    }
    by_exclusion_reason = {
        row["exclusion_reason"]: row["count"]
        for row in connection.execute(
            """
            SELECT COALESCE(exclusion_reason, 'none') AS exclusion_reason, COUNT(*) AS count
            FROM offers
            WHERE is_target = 0
            GROUP BY COALESCE(exclusion_reason, 'none')
            ORDER BY count DESC
            """
        ).fetchall()
    }
    return {
        "total": total,
        "unavailable": unavailable,
        "by_bucket": by_bucket,
        "by_exclusion_reason": by_exclusion_reason,
    }


def all_offers(connection: sqlite3.Connection) -> Iterable[JobOffer]:
    rows = connection.execute("SELECT * FROM offers ORDER BY last_seen_at DESC").fetchall()
    return [_row_to_offer(row) for row in rows]


def _row_to_offer(row: sqlite3.Row) -> JobOffer:
    data = dict(row)
    data["url"] = row["url"]
    data["unavailable"] = bool(row["unavailable"])
    data["hard_filter_passed"] = bool(row["hard_filter_passed"])
    data["is_target"] = bool(row["is_target"])
    data["risk_flags"] = json.loads(row["risk_flags"] or "[]")
    return JobOffer.model_validate(data)
