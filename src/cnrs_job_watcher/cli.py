from __future__ import annotations

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
from cnrs_job_watcher.storage import audit_counts, connect, shortlist, upsert_offer

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
) -> None:
    """Récupère les offres publiques CNRS, parse les détails, classe et stocke."""
    discovered = []
    with CnrsClient(cache_dir=raw_dir) as client:
        first_html = client.fetch_list_page(1, use_cache=not no_cache)
        first_offers, stats = parse_list_page(first_html)
        pages_to_fetch = min(limit_pages, stats.total_pages or limit_pages)
        discovered.extend(first_offers)

        for page in range(2, pages_to_fetch + 1):
            html = client.fetch_list_page(page, use_cache=not no_cache)
            offers, _ = parse_list_page(html)
            discovered.extend(offers)

        unique = {str(offer.url): offer for offer in discovered}
        offer_urls = list(unique)
        if limit_offers:
            offer_urls = offer_urls[:limit_offers]

        connection = connect(db)
        for url in track(offer_urls, description="Récupération détails CNRS"):
            detail_html = client.fetch_offer_page(url, use_cache=not no_cache)
            offer = parse_offer_detail(detail_html, url)
            offer = apply_classification(offer)
            upsert_offer(connection, offer)

    console.print(
        f"[green]OK[/green] {len(offer_urls)} offres traitées dans {db}. "
        f"Pages liste explorées: {pages_to_fetch}."
    )


@app.command("export")
def export_command(
    format: str = typer.Option("both", help="markdown, csv ou both."),
    output: Path | None = typer.Option(None, help="Chemin de sortie. Ignoré avec --format both."),
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    min_score: float = typer.Option(0.35, min=0, max=1, help="Score minimum à exporter."),
) -> None:
    """Exporte la shortlist locale en Markdown et/ou CSV."""
    connection = connect(db)
    offers = shortlist(connection, min_score=min_score)

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
