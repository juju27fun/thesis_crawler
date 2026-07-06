from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import track
from rich.table import Table

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.evaluation import load_evaluation_cases, run_evaluation
from cnrs_job_watcher.export import export_csv, export_markdown
from cnrs_job_watcher.fetch import CnrsClient
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.storage import (
    audit_counts,
    connect,
    finish_run,
    latest_run_started_at,
    record_offer_snapshot,
    shortlist,
    start_run,
    upsert_offer,
)

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def crawl(
    limit_pages: int = typer.Option(
        1,
        min=1,
        help="Nombre maximum de pages de résultats à explorer.",
    ),
    limit_offers: int | None = typer.Option(
        None,
        min=1,
        help="Nombre maximum de pages détail à récupérer.",
    ),
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Dossier de snapshots HTML."),
    no_cache: bool = typer.Option(False, help="Ignorer les snapshots HTML existants."),
    profile: str = typer.Option("all_public", help="Profil de recherche logique du run."),
) -> None:
    """Récupère les offres publiques CNRS, parse les détails, classe et stocke."""
    discovered = []
    pages_to_fetch = 0
    pages_fetched = 0
    offers_fetched = 0
    errors_count = 0
    connection = connect(db)
    run_id = start_run(connection, profile=profile)

    try:
        with CnrsClient(cache_dir=raw_dir) as client:
            first_html = client.fetch_list_page(1, use_cache=not no_cache)
            pages_fetched += 1
            first_offers, stats = parse_list_page(first_html)
            pages_to_fetch = min(limit_pages, stats.total_pages or limit_pages)
            discovered.extend(first_offers)

            for page in range(2, pages_to_fetch + 1):
                html = client.fetch_list_page(page, use_cache=not no_cache)
                pages_fetched += 1
                offers, _ = parse_list_page(html)
                discovered.extend(offers)

            unique = {str(offer.url): offer for offer in discovered}
            offer_urls = list(unique)
            if limit_offers:
                offer_urls = offer_urls[:limit_offers]

            for url in track(offer_urls, description="Récupération détails CNRS"):
                try:
                    detail_html = client.fetch_offer_page(url, use_cache=not no_cache)
                    content_hash = hashlib.sha256(detail_html.encode("utf-8")).hexdigest()
                    offer = parse_offer_detail(detail_html, url)
                    offer = apply_classification(
                        offer.model_copy(update={"content_hash": content_hash})
                    )
                    upsert_offer(connection, offer)
                    record_offer_snapshot(
                        connection,
                        offer,
                        content_hash=content_hash,
                        raw_path=str(client.offer_cache_path(url)),
                        run_id=run_id,
                    )
                    offers_fetched += 1
                except Exception as exc:  # noqa: BLE001
                    errors_count += 1
                    console.print(f"[red]Erreur offre[/red] {url}: {exc}")
    finally:
        finish_run(
            connection,
            run_id,
            pages_fetched=pages_fetched,
            offers_discovered=len({str(offer.url): offer for offer in discovered}),
            offers_fetched=offers_fetched,
            errors_count=errors_count,
        )

    console.print(
        f"[green]OK[/green] {offers_fetched} offres traitées dans {db}. "
        f"Pages liste explorées: {pages_to_fetch}. Run: {run_id}. "
        f"Erreurs: {errors_count}."
    )
    if not discovered or offers_fetched == 0:
        raise typer.Exit(code=1)


@app.command("export")
def export_command(
    format: str = typer.Option("both", help="markdown, csv ou both."),
    output: Path | None = typer.Option(None, help="Chemin de sortie. Ignoré avec --format both."),
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    min_score: float = typer.Option(0.35, min=0, max=1, help="Score minimum à exporter."),
    only_new: bool = typer.Option(False, help="Exporter seulement les offres du dernier run."),
) -> None:
    """Exporte la shortlist locale en Markdown et/ou CSV."""
    connection = connect(db)
    since = latest_run_started_at(connection) if only_new else None
    offers = shortlist(connection, min_score=min_score, since=since)

    if format not in {"markdown", "csv", "both"}:
        raise typer.BadParameter("format doit valoir markdown, csv ou both")

    if format in {"markdown", "both"}:
        markdown_output = output if output and format == "markdown" else Path("cnrs_ia_jobs.md")
        export_markdown(offers, markdown_output)
        console.print(f"[green]Markdown[/green] {markdown_output}")

    if format in {"csv", "both"}:
        csv_output = output if output and format == "csv" else Path("cnrs_ia_jobs.csv")
        export_csv(offers, csv_output)
        console.print(f"[green]CSV[/green] {csv_output}")

    console.print(f"{len(offers)} offres exportées.")


@app.command()
def audit(
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
) -> None:
    """Affiche les compteurs qualité du dernier état local."""
    connection = connect(db)
    counts = audit_counts(connection)

    console.print(f"[bold]Offres en base[/bold] {counts['total']}")
    console.print(f"[bold]Indisponibles[/bold] {counts['unavailable']}")

    bucket_table = Table(title="Buckets")
    bucket_table.add_column("Bucket")
    bucket_table.add_column("Offres", justify="right")
    for bucket, count in dict(counts["by_bucket"]).items():
        bucket_table.add_row(str(bucket), str(count))
    console.print(bucket_table)

    exclusion_table = Table(title="Exclusions")
    exclusion_table.add_column("Raison")
    exclusion_table.add_column("Offres", justify="right")
    for reason, count in dict(counts["by_exclusion_reason"]).items():
        exclusion_table.add_row(str(reason), str(count))
    console.print(exclusion_table)

    if counts["latest_run"]:
        run = dict(counts["latest_run"])
        console.print(
            "[bold]Dernier run[/bold] "
            f"#{run['id']} profile={run['profile']} "
            f"pages={run['pages_fetched']} fetched={run['offers_fetched']} "
            f"errors={run['errors_count']}"
        )

    top_table = Table(title="Top scores bruts")
    top_table.add_column("Référence")
    top_table.add_column("Bucket")
    top_table.add_column("Score", justify="right")
    top_table.add_column("Titre")
    for row in list(counts["top_scores"]):
        score = row["ai_relevance_score"]
        top_table.add_row(
            str(row["reference"] or ""),
            str(row["target_bucket"]),
            f"{score:.2f}" if isinstance(score, float) else str(score),
            str(row["title"]),
        )
    console.print(top_table)


@app.command()
def eval(
    dataset: Path = typer.Option(
        Path("tests/fixtures/evaluation/offers.json"),
        help="Dataset annoté JSON.",
    ),
    min_bucket_accuracy: float = typer.Option(
        0.9,
        min=0,
        max=1,
        help="Seuil minimal de justesse bucket.",
    ),
) -> None:
    """Évalue la classification sur le dataset annoté local."""
    summary = run_evaluation(load_evaluation_cases(dataset))

    console.print(f"[bold]Cas évalués[/bold] {summary.total}")
    console.print(f"[bold]Bucket accuracy[/bold] {summary.bucket_accuracy:.3f}")
    console.print(f"[bold]Domain accuracy[/bold] {summary.domain_accuracy:.3f}")
    console.print(f"[bold]Accessibility accuracy[/bold] {summary.accessibility_accuracy:.3f}")
    console.print(f"[bold]False targets[/bold] {summary.false_targets}")
    console.print(f"[bold]Missed targets[/bold] {summary.missed_targets}")

    failures = [
        result
        for result in summary.results
        if not (result.bucket_ok and result.domain_ok and result.accessibility_ok)
    ]
    if failures:
        table = Table(title="Écarts")
        table.add_column("Référence")
        table.add_column("Bucket")
        table.add_column("Domaine")
        table.add_column("Accessibilité")
        for result in failures:
            table.add_row(
                result.reference,
                f"{result.expected_bucket} -> {result.actual_bucket}",
                f"{result.expected_ai_domain} -> {result.actual_ai_domain}",
                f"{result.expected_accessibility} -> {result.actual_accessibility}",
            )
        console.print(table)

    if summary.bucket_accuracy < min_bucket_accuracy or summary.false_targets:
        raise typer.Exit(code=1)


@app.command()
def digest(
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    output: Path | None = typer.Option(None, help="Chemin du digest Markdown."),
    min_score: float = typer.Option(0.35, min=0, max=1, help="Score minimum à inclure."),
    only_new: bool = typer.Option(
        True,
        help="Limiter aux offres vues pour la première fois au dernier run.",
    ),
) -> None:
    """Produit un digest Markdown daté, pensé pour une veille quotidienne."""
    connection = connect(db)
    since = latest_run_started_at(connection) if only_new else None
    offers = shortlist(connection, min_score=min_score, since=since)
    output_path = output or Path("data/digests") / f"{datetime.now(UTC).date().isoformat()}.md"
    export_markdown(offers, output_path)
    scope = "nouvelles offres" if only_new else "shortlist complète"
    console.print(f"[green]Digest[/green] {output_path} ({len(offers)} {scope}).")
