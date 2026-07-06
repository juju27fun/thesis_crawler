from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import track

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.export import export_csv, export_markdown
from cnrs_job_watcher.fetch import CnrsClient
from cnrs_job_watcher.parse import parse_list_page, parse_offer_detail
from cnrs_job_watcher.storage import connect, shortlist, upsert_offer

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
