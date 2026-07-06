from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import track
from rich.table import Table

from cnrs_job_watcher.classify import apply_classification
from cnrs_job_watcher.evaluation import load_evaluation_cases, run_evaluation
from cnrs_job_watcher.export import export_csv, export_markdown
from cnrs_job_watcher.fetch import CnrsClient
from cnrs_job_watcher.llm_classifier import (
    ClassifierMode,
    LlmProvider,
    classify_offer_hybrid,
    provider_from_env,
)
from cnrs_job_watcher.parse import parse_list_page
from cnrs_job_watcher.profiles import SearchProfile, dedupe_offers, filter_offers_by_profile
from cnrs_job_watcher.schemas import JobOffer
from cnrs_job_watcher.sources import CnrsSourceAdapter
from cnrs_job_watcher.storage import (
    audit_counts,
    connect,
    excluded_offers,
    finish_run,
    get_llm_cache,
    latest_run_started_at,
    record_offer_snapshot,
    set_llm_cache,
    shortlist,
    start_run,
    upsert_offer,
)

app = typer.Typer(no_args_is_help=True)
console = Console()


class DiscoveryMode(StrEnum):
    SITEMAP = "sitemap"
    LIST = "list"


@app.command()
def crawl(
    limit_pages: int = typer.Option(
        1,
        min=1,
        help="Nombre maximum de pages liste à explorer en mode --discovery list.",
    ),
    limit_offers: int | None = typer.Option(
        None,
        min=1,
        help="Nombre maximum de pages détail à récupérer.",
    ),
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Dossier de snapshots HTML."),
    no_cache: bool = typer.Option(False, help="Ignorer les snapshots HTML existants."),
    timeout: float = typer.Option(30.0, min=1.0, help="Timeout HTTP en secondes."),
    max_retries: int = typer.Option(2, min=0, help="Nombre de retries HTTP transitoires."),
    max_error_rate: float = typer.Option(
        0.2,
        min=0,
        max=1,
        help="Taux d'erreurs détail maximum avant exit code non nul.",
    ),
    profile: SearchProfile = typer.Option(
        SearchProfile.ALL_PUBLIC,
        help="Profil de recherche logique du run.",
    ),
    classifier: ClassifierMode = typer.Option(
        ClassifierMode.RULES,
        help="Classifieur à utiliser: rules, llm ou hybrid.",
    ),
    discovery: DiscoveryMode = typer.Option(
        DiscoveryMode.SITEMAP,
        help="Source de découverte: sitemap exhaustif ou pagination liste legacy.",
    ),
) -> None:
    """Récupère les offres publiques CNRS, parse les détails, classe et stocke."""
    discovered = []
    pages_to_fetch = 0
    pages_fetched = 0
    offers_fetched = 0
    discovered_count = 0
    errors_count = 0
    connection = connect(db)
    run_id = start_run(connection, profile=profile.value)
    llm_provider = provider_from_env() if classifier != ClassifierMode.RULES else None
    if classifier != ClassifierMode.RULES and llm_provider is None:
        console.print("[yellow]OPENAI_API_KEY absent; fallback règles seules.[/yellow]")

    try:
        with CnrsClient(
            cache_dir=raw_dir,
            timeout_seconds=timeout,
            max_retries=max_retries,
        ) as client:
            source_adapter = CnrsSourceAdapter(client)
            if discovery == DiscoveryMode.SITEMAP:
                offer_urls = _filter_sitemap_urls_by_profile(
                    source_adapter.discover_urls(use_cache=not no_cache),
                    profile,
                )
                pages_fetched = 1
                pages_to_fetch = 1
                discovered_count = len(offer_urls)
            else:
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

                filtered = filter_offers_by_profile(dedupe_offers(discovered), profile)
                offer_urls = [str(offer.url) for offer in filtered]
                discovered_count = len(filtered)
            if limit_offers:
                offer_urls = offer_urls[:limit_offers]

            for url in track(offer_urls, description="Récupération détails CNRS"):
                try:
                    detail_html = client.fetch_offer_page(url, use_cache=not no_cache)
                    content_hash = hashlib.sha256(detail_html.encode("utf-8")).hexdigest()
                    offer = source_adapter.parse_detail(detail_html, url)
                    offer = _classify_offer(
                        offer.model_copy(update={"content_hash": content_hash}),
                        mode=classifier,
                        provider=llm_provider,
                        connection=connection,
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
            offers_discovered=discovered_count,
            offers_fetched=offers_fetched,
            errors_count=errors_count,
        )

    console.print(
        f"[green]OK[/green] {offers_fetched} offres traitées dans {db}. "
        f"Découverte: {discovery.value}. Pages liste explorées: {pages_to_fetch}. "
        f"Run: {run_id}. "
        f"Erreurs: {errors_count}."
    )
    if discovered_count == 0 or offers_fetched == 0:
        raise typer.Exit(code=1)
    total_attempted = offers_fetched + errors_count
    if total_attempted and errors_count / total_attempted > max_error_rate:
        raise typer.Exit(code=1)


@app.command("profile-audit")
def profile_audit(
    limit_pages: int = typer.Option(1, min=1, help="Nombre de pages liste à auditer."),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Dossier de snapshots HTML."),
    no_cache: bool = typer.Option(False, help="Ignorer les snapshots HTML existants."),
    timeout: float = typer.Option(30.0, min=1.0, help="Timeout HTTP en secondes."),
    max_retries: int = typer.Option(2, min=0, help="Nombre de retries HTTP transitoires."),
) -> None:
    """Compare les volumes découverts par profil sur les pages liste."""
    discovered = []
    pages_fetched = 0
    with CnrsClient(cache_dir=raw_dir, timeout_seconds=timeout, max_retries=max_retries) as client:
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

    deduped = dedupe_offers(discovered)
    table = Table(title=f"Discovery profiles ({pages_fetched} pages)")
    table.add_column("Profil")
    table.add_column("Offres", justify="right")
    for profile in SearchProfile:
        table.add_row(profile.value, str(len(filter_offers_by_profile(deduped, profile))))
    console.print(table)


@app.command("export")
def export_command(
    format: str = typer.Option("both", help="markdown, csv ou both."),
    output: Path | None = typer.Option(None, help="Chemin de sortie. Ignoré avec --format both."),
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    min_score: float = typer.Option(0.35, min=0, max=1, help="Score minimum à exporter."),
    only_new: bool = typer.Option(False, help="Exporter seulement les offres du dernier run."),
    include_excluded: bool = typer.Option(False, help="Inclure les exclusions notables."),
    source: str | None = typer.Option(None, help="Filtrer par source normalisée."),
) -> None:
    """Exporte la shortlist locale en Markdown et/ou CSV."""
    connection = connect(db)
    since = latest_run_started_at(connection) if only_new else None
    offers = shortlist(connection, min_score=min_score, since=since, source=source)
    if include_excluded:
        offers.extend(excluded_offers(connection, since=since, source=source))

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
    json_output: bool = typer.Option(False, "--json", help="Sortie JSON machine-readable."),
) -> None:
    """Affiche les compteurs qualité du dernier état local."""
    connection = connect(db)
    counts = audit_counts(connection)
    if json_output:
        console.print(json.dumps(counts, ensure_ascii=False, default=str))
        return

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
    console.print(f"[bold]Target precision[/bold] {summary.target_precision:.3f}")
    console.print(f"[bold]Target recall[/bold] {summary.target_recall:.3f}")
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
    include_excluded: bool = typer.Option(False, help="Inclure les exclusions notables."),
    source: str | None = typer.Option(None, help="Filtrer par source normalisée."),
) -> None:
    """Produit un digest Markdown daté, pensé pour une veille quotidienne."""
    connection = connect(db)
    since = latest_run_started_at(connection) if only_new else None
    offers = shortlist(connection, min_score=min_score, since=since, source=source)
    if include_excluded:
        offers.extend(excluded_offers(connection, since=since, source=source))
    output_path = output or Path("data/digests") / f"{datetime.now(UTC).date().isoformat()}.md"
    export_markdown(offers, output_path)
    scope = "nouvelles offres" if only_new else "shortlist complète"
    console.print(f"[green]Digest[/green] {output_path} ({len(offers)} {scope}).")


class _CachingLlmProvider:
    def __init__(
        self,
        connection: object,
        provider: LlmProvider,
        content_hash: str,
        classifier_version: str,
    ) -> None:
        self.connection = connection
        self.provider = provider
        self.content_hash = content_hash
        self.classifier_version = classifier_version

    def classify(self, offer: JobOffer, schema: dict[str, object]) -> Mapping[str, object]:
        cached = get_llm_cache(self.connection, self.content_hash, self.classifier_version)
        if cached is not None:
            return cached
        response = self.provider.classify(offer, schema)
        set_llm_cache(self.connection, self.content_hash, self.classifier_version, response)
        return response


def _classify_offer(
    offer: JobOffer,
    *,
    mode: ClassifierMode,
    provider: LlmProvider | None,
    connection: object,
) -> JobOffer:
    if mode == ClassifierMode.RULES or provider is None or not offer.content_hash:
        return apply_classification(offer)
    cached_provider = _CachingLlmProvider(
        connection,
        provider,
        offer.content_hash,
        "hybrid-llm-v1",
    )
    return classify_offer_hybrid(offer, cached_provider)


def _filter_sitemap_urls_by_profile(urls: list[str], profile: SearchProfile) -> list[str]:
    if profile == SearchProfile.DOCTORANT:
        return [url for url in urls if "/Offres/Doctorant/" in url]
    return urls
