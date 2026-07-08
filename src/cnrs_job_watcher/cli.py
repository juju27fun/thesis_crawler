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

from cnrs_job_watcher.anrt.fetch import (
    AnrtAuthenticationRequired,
    AnrtClient,
    AnrtFixtureClient,
    AnrtKind,
    is_logged_out_page,
)
from cnrs_job_watcher.anrt.fixtures import anonymize_fixture_tree, audit_anrt_fixture_tree
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
from cnrs_job_watcher.sources import AnrtSourceAdapter, CnrsSourceAdapter, SourceAdapter
from cnrs_job_watcher.storage import (
    audit_counts,
    changed_offers,
    connect,
    excluded_offers,
    finish_run,
    get_llm_cache,
    latest_run_started_at,
    mark_missing_offers,
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


class SourceName(StrEnum):
    CNRS = "cnrs"
    ANRT = "anrt"
    ALL = "all"


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
    source: SourceName = typer.Option(SourceName.CNRS, help="Source à crawler."),
    anrt_kind: AnrtKind = typer.Option(
        AnrtKind.BOTH,
        help="Sous-source ANRT: entreprise, laboratoire ou both.",
    ),
    anrt_session_file: Path | None = typer.Option(
        None,
        help="Fichier cookies Playwright/JSON local pour accéder à ANRT.",
    ),
    anrt_fixture_dir: Path | None = typer.Option(
        None,
        help="Dossier fixture ANRT anonymisé à utiliser à la place du réseau.",
    ),
) -> None:
    """Récupère les offres d'une source, parse les détails, classe et stocke."""
    connection = connect(db)
    llm_provider = provider_from_env() if classifier != ClassifierMode.RULES else None
    if classifier != ClassifierMode.RULES and llm_provider is None:
        console.print("[yellow]OPENAI_API_KEY absent; fallback règles seules.[/yellow]")

    run_sources = [SourceName.CNRS, SourceName.ANRT] if source == SourceName.ALL else [source]
    totals = {"discovered": 0, "fetched": 0, "errors": 0}
    auth_failures: list[str] = []

    for run_source in run_sources:
        if run_source == SourceName.CNRS:
            result = _crawl_cnrs_source(
                connection=connection,
                raw_dir=raw_dir,
                no_cache=no_cache,
                timeout=timeout,
                max_retries=max_retries,
                limit_pages=limit_pages,
                limit_offers=limit_offers,
                profile=profile,
                discovery=discovery,
                classifier=classifier,
                llm_provider=llm_provider,
            )
        else:
            try:
                result = _crawl_anrt_source(
                    connection=connection,
                    raw_dir=raw_dir,
                    no_cache=no_cache,
                    timeout=timeout,
                    max_retries=max_retries,
                    limit_offers=limit_offers,
                    classifier=classifier,
                    llm_provider=llm_provider,
                    discovery=discovery,
                    anrt_kind=anrt_kind,
                    anrt_session_file=anrt_session_file,
                    anrt_fixture_dir=anrt_fixture_dir,
                )
            except AnrtAuthenticationRequired as exc:
                auth_failures.append(str(exc))
                console.print(f"[red]ANRT auth requise[/red] {exc}")
                if source == SourceName.ANRT:
                    raise typer.Exit(code=2) from exc
                continue

        totals["discovered"] += result["discovered"]
        totals["fetched"] += result["fetched"]
        totals["errors"] += result["errors"]

    console.print(
        f"[green]OK[/green] {totals['fetched']} offres traitées dans {db}. "
        f"Source: {source.value}. Erreurs: {totals['errors']}."
    )
    if auth_failures:
        console.print(
            "[yellow]ANRT ignoré pour ce run multi-source: session absente/expirée.[/yellow]"
        )
    if totals["discovered"] == 0 or totals["fetched"] == 0:
        raise typer.Exit(code=1 if not auth_failures else 2)
    total_attempted = totals["fetched"] + totals["errors"]
    if total_attempted and totals["errors"] / total_attempted > max_error_rate:
        raise typer.Exit(code=1)


def _crawl_cnrs_source(
    *,
    connection: object,
    raw_dir: Path,
    no_cache: bool,
    timeout: float,
    max_retries: int,
    limit_pages: int,
    limit_offers: int | None,
    profile: SearchProfile,
    discovery: DiscoveryMode,
    classifier: ClassifierMode,
    llm_provider: LlmProvider | None,
) -> dict[str, int]:
    run_id = start_run(connection, profile=profile.value, source="cnrs")
    discovered = []
    pages_fetched = 0
    pages_to_fetch = 0
    discovered_count = 0
    offers_fetched = 0
    errors_count = 0
    status_message: str | None = None
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
            offers_fetched, errors_count = _fetch_parse_classify_store(
                source_adapter=source_adapter,
                offer_urls=offer_urls,
                no_cache=no_cache,
                classifier=classifier,
                llm_provider=llm_provider,
                connection=connection,
                run_id=run_id,
                progress_description="Récupération détails CNRS",
            )
            if not limit_offers and discovered_count and offers_fetched:
                missing_count = mark_missing_offers(
                    connection,
                    source="cnrs",
                    seen_urls=offer_urls,
                )
                if missing_count:
                    console.print(f"[yellow]CNRS[/yellow] {missing_count} offres disparues.")
    finally:
        if discovered_count == 0 or offers_fetched == 0:
            status_message = "no_offers_processed"
        finish_run(
            connection,
            run_id,
            pages_fetched=pages_fetched,
            offers_discovered=discovered_count,
            offers_fetched=offers_fetched,
            errors_count=errors_count,
            status_message=status_message,
        )
    console.print(
        f"[green]CNRS[/green] {offers_fetched} offres traitées. "
        f"Découverte: {discovery.value}. Pages liste explorées: {pages_to_fetch}. "
        f"Run: {run_id}. Erreurs: {errors_count}."
    )
    return {"discovered": discovered_count, "fetched": offers_fetched, "errors": errors_count}


def _crawl_anrt_source(
    *,
    connection: object,
    raw_dir: Path,
    no_cache: bool,
    timeout: float,
    max_retries: int,
    limit_offers: int | None,
    classifier: ClassifierMode,
    llm_provider: LlmProvider | None,
    discovery: DiscoveryMode,
    anrt_kind: AnrtKind,
    anrt_session_file: Path | None,
    anrt_fixture_dir: Path | None,
) -> dict[str, int]:
    run_id = start_run(
        connection,
        profile="anrt_cifre",
        source="anrt",
        source_kind=anrt_kind.value,
    )
    pages_fetched = 0
    discovered_count = 0
    offers_fetched = 0
    errors_count = 0
    status_message: str | None = None
    try:
        if discovery != DiscoveryMode.SITEMAP:
            console.print(
                "[yellow]ANRT ignore --discovery list; discovery via listes membre.[/yellow]"
            )
        if anrt_fixture_dir:
            client_context = AnrtFixtureClient(anrt_fixture_dir)
        else:
            try:
                client_context = AnrtClient(
                    cache_dir=raw_dir,
                    session_file=anrt_session_file,
                    timeout_seconds=timeout,
                    max_retries=max_retries,
                )
            except AnrtAuthenticationRequired as exc:
                status_message = "auth_required"
                raise exc
        with client_context as client:
            source_adapter = AnrtSourceAdapter(client, kind=anrt_kind)
            try:
                offer_urls = source_adapter.discover_urls(use_cache=not no_cache)
            except AnrtAuthenticationRequired as exc:
                status_message = "auth_required"
                raise exc
            discovery_audit = source_adapter.last_discovery_audit
            pages_fetched = discovery_audit.total_pages_fetched
            discovered_count = len(offer_urls)
            if discovery_audit.max_pages_reached:
                status_message = "max_list_pages_reached"
            if limit_offers:
                offer_urls = offer_urls[:limit_offers]
            offers_fetched, errors_count = _fetch_parse_classify_store(
                source_adapter=source_adapter,
                offer_urls=offer_urls,
                no_cache=no_cache,
                classifier=classifier,
                llm_provider=llm_provider,
                connection=connection,
                run_id=run_id,
                progress_description="Récupération détails ANRT",
            )
            if (
                not limit_offers
                and anrt_kind == AnrtKind.BOTH
                and discovered_count
                and offers_fetched
            ):
                missing_count = mark_missing_offers(
                    connection,
                    source="anrt",
                    seen_urls=offer_urls,
                )
                if missing_count:
                    console.print(f"[yellow]ANRT[/yellow] {missing_count} offres disparues.")
    finally:
        if status_message is None and (discovered_count == 0 or offers_fetched == 0):
            status_message = "no_offers_processed"
        finish_run(
            connection,
            run_id,
            pages_fetched=pages_fetched,
            offers_discovered=discovered_count,
            offers_fetched=offers_fetched,
            errors_count=errors_count,
            status_message=status_message,
        )
    console.print(
        f"[green]ANRT[/green] {offers_fetched} offres traitées. "
        f"Kind: {anrt_kind.value}. Pages liste: {pages_fetched}. "
        f"Découverte: {discovered_count}. Run: {run_id}. Erreurs: {errors_count}."
    )
    return {"discovered": discovered_count, "fetched": offers_fetched, "errors": errors_count}


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


@app.command("anrt-session-check")
def anrt_session_check(
    anrt_session_file: Path | None = typer.Option(
        None,
        help="Fichier cookies Playwright/JSON local pour accéder à ANRT.",
    ),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Dossier de snapshots HTML."),
    anrt_fixture_dir: Path | None = typer.Option(
        None,
        help="Dossier fixture ANRT anonymisé à utiliser à la place du réseau.",
    ),
    no_cache: bool = typer.Option(False, help="Ignorer les snapshots HTML existants."),
    timeout: float = typer.Option(30.0, min=1.0, help="Timeout HTTP en secondes."),
    max_retries: int = typer.Option(1, min=0, help="Nombre de retries HTTP transitoires."),
) -> None:
    """Vérifie qu'une session ANRT locale atteint les listes entreprise/laboratoire."""
    client_context = (
        AnrtFixtureClient(anrt_fixture_dir)
        if anrt_fixture_dir
        else AnrtClient(
            cache_dir=raw_dir,
            session_file=anrt_session_file,
            timeout_seconds=timeout,
            max_retries=max_retries,
        )
    )
    with client_context as client:
        adapter = AnrtSourceAdapter(client, kind=AnrtKind.BOTH)
        try:
            urls = adapter.discover_urls(use_cache=not no_cache)
        except AnrtAuthenticationRequired as exc:
            console.print(f"[red]ANRT auth requise[/red] {exc}")
            raise typer.Exit(code=2) from exc

    table = Table(title="ANRT session")
    table.add_column("Statut")
    table.add_column("Pages liste", justify="right")
    table.add_column("URLs découvertes", justify="right")
    table.add_column("Doublons", justify="right")
    audit = adapter.last_discovery_audit
    status = "connectée"
    if audit.max_pages_reached:
        status = "connectée, limite pagination atteinte"
    table.add_row(
        status,
        str(audit.total_pages_fetched),
        str(len(urls)),
        str(audit.duplicate_urls),
    )
    kind_table = Table(title="ANRT discovery par origine")
    kind_table.add_column("Origine")
    kind_table.add_column("Pages", justify="right")
    kind_table.add_column("URLs", justify="right")
    kind_table.add_column("Compteur UI", justify="right")
    kind_table.add_column("Limite", justify="right")
    for kind_audit in audit.kinds:
        kind_table.add_row(
            kind_audit.kind,
            str(kind_audit.pages_fetched),
            str(kind_audit.urls_discovered),
            str(kind_audit.ui_total) if kind_audit.ui_total is not None else "n/a",
            "oui" if kind_audit.max_pages_reached else "non",
        )
    console.print(table)
    console.print(kind_table)


@app.command("anrt-login")
def anrt_login(
    output: Path = typer.Option(
        Path("data/auth/anrt-cookies.json"),
        help="Fichier storage_state Playwright à écrire hors Git.",
    ),
    start_url: str = typer.Option(
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/entreprise",
        help="URL ANRT à ouvrir pour la connexion.",
    ),
    timeout_seconds: int = typer.Option(
        600,
        min=30,
        help="Temps maximum laissé pour se connecter dans le navigateur.",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="Lancer le navigateur sans interface visible.",
    ),
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Vérifier la session sur les listes entreprise/laboratoire avant d'écrire le fichier.",
    ),
) -> None:
    """Ouvre un navigateur Playwright pour créer une session ANRT locale hors Git."""
    try:
        sync_playwright = _load_sync_playwright()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    console.print(
        "[bold]Connexion ANRT[/bold] Connecte-toi dans le navigateur ouvert, "
        "puis reviens ici pour valider."
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        typer.confirm(
            "Appuie sur Entrée quand la session ANRT est connectée",
            default=True,
            show_default=False,
            abort=False,
        )
        if verify:
            _verify_anrt_browser_session(page, timeout_seconds=timeout_seconds)
        context.storage_state(path=str(output))
        browser.close()

    console.print(f"[green]Session ANRT enregistrée[/green] {output}")
    console.print(
        "Vérification recommandée: "
        f"uv run cnrs-jobs anrt-session-check --anrt-session-file {output} --no-cache"
    )


@app.command("anrt-real-smoke")
def anrt_real_smoke(
    anrt_session_file: Path | None = typer.Option(
        None,
        help="Fichier cookies Playwright/JSON local pour accéder à ANRT.",
    ),
    anrt_fixture_dir: Path | None = typer.Option(
        None,
        help="Dossier fixture ANRT anonymisé à utiliser à la place du réseau.",
    ),
    anrt_kind: AnrtKind = typer.Option(
        AnrtKind.BOTH,
        help="Sous-source ANRT à valider: entreprise, laboratoire ou both.",
    ),
    limit_offers: int = typer.Option(
        20,
        min=1,
        help="Nombre maximum d'offres détail à traiter pour le smoke réel.",
    ),
    db: Path = typer.Option(
        Path("data/validation/anrt_real_smoke.sqlite"),
        help="Base SQLite locale dédiée à la validation ANRT.",
    ),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Dossier de snapshots HTML."),
    report: Path = typer.Option(
        Path("data/validation/anrt_real_smoke.md"),
        help="Rapport Markdown de validation à écrire.",
    ),
    digest_output: Path = typer.Option(
        Path("data/validation/anrt_real_digest.md"),
        help="Digest Markdown ANRT extrait du smoke.",
    ),
    anonymized_fixture_dir: Path | None = typer.Option(
        None,
        help="Dossier optionnel où écrire des fixtures anonymisées depuis les snapshots du smoke.",
    ),
    classifier: ClassifierMode = typer.Option(
        ClassifierMode.RULES,
        help="Classifieur à utiliser: rules, llm ou hybrid.",
    ),
    min_score: float = typer.Option(0.1, min=0, max=1, help="Score minimum du digest."),
    no_cache: bool = typer.Option(False, help="Ignorer les snapshots HTML existants."),
    timeout: float = typer.Option(30.0, min=1.0, help="Timeout HTTP en secondes."),
    max_retries: int = typer.Option(1, min=0, help="Nombre de retries HTTP transitoires."),
) -> None:
    """Lance un smoke ANRT borné et écrit un rapport de preuve local."""
    connection = connect(db)
    llm_provider = provider_from_env() if classifier != ClassifierMode.RULES else None
    if classifier != ClassifierMode.RULES and llm_provider is None:
        console.print("[yellow]OPENAI_API_KEY absent; fallback règles seules.[/yellow]")

    try:
        result = _crawl_anrt_source(
            connection=connection,
            raw_dir=raw_dir,
            no_cache=no_cache,
            timeout=timeout,
            max_retries=max_retries,
            limit_offers=limit_offers,
            classifier=classifier,
            llm_provider=llm_provider,
            discovery=DiscoveryMode.SITEMAP,
            anrt_kind=anrt_kind,
            anrt_session_file=anrt_session_file,
            anrt_fixture_dir=anrt_fixture_dir,
        )
    except AnrtAuthenticationRequired as exc:
        counts = audit_counts(connection, source="anrt")
        _write_anrt_smoke_report(
            report,
            db=db,
            raw_dir=raw_dir,
            digest_output=digest_output,
            result={"discovered": 0, "fetched": 0, "errors": 0},
            counts=counts,
            status="auth_required",
            message=str(exc),
            fixture_audit=None,
        )
        console.print(f"[red]ANRT auth requise[/red] {exc}")
        console.print(f"[yellow]Rapport[/yellow] {report}")
        raise typer.Exit(code=2) from exc

    offers = shortlist(connection, min_score=min_score, source="anrt")
    export_markdown(offers, digest_output)
    fixture_audit: dict[str, object] | None = None
    if anonymized_fixture_dir:
        anonymize_fixture_tree(raw_dir / "anrt", anonymized_fixture_dir)
        fixture_audit = audit_anrt_fixture_tree(anonymized_fixture_dir).to_dict()

    status = "ok" if result["fetched"] > 0 else "no_offers_processed"
    counts = audit_counts(connection, source="anrt")
    _write_anrt_smoke_report(
        report,
        db=db,
        raw_dir=raw_dir,
        digest_output=digest_output,
        result=result,
        counts=counts,
        status=status,
        message=None,
        fixture_audit=fixture_audit,
    )
    console.print(f"[green]Rapport ANRT[/green] {report}")
    console.print(f"[green]Digest ANRT[/green] {digest_output} ({len(offers)} offres).")
    if result["fetched"] == 0 or result["errors"] > 0:
        raise typer.Exit(code=1)


@app.command("anrt-mvp-audit")
def anrt_mvp_audit(
    db: Path = typer.Option(
        Path("data/validation/anrt_real_smoke.sqlite"),
        help="Base SQLite produite par le smoke/crawl ANRT réel.",
    ),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Dossier de snapshots HTML."),
    digest: Path = typer.Option(
        Path("data/validation/anrt_real_digest.md"),
        help="Digest ANRT produit par le smoke réel.",
    ),
    fixture_dir: Path | None = typer.Option(
        None,
        help="Dossier de fixtures ANRT réelles anonymisées à auditer.",
    ),
    eval_dataset: Path | None = typer.Option(
        None,
        help="Dataset d'évaluation ANRT réel anonymisé à vérifier.",
    ),
    output: Path = typer.Option(
        Path("data/validation/anrt_mvp_audit.md"),
        help="Rapport Markdown d'audit MVP à écrire.",
    ),
    min_offers: int = typer.Option(20, min=1, help="Minimum d'offres ANRT réelles attendues."),
    min_raw_list_files: int = typer.Option(2, min=0, help="Minimum de snapshots liste attendus."),
    min_raw_detail_files: int = typer.Option(
        20,
        min=0,
        help="Minimum de snapshots détail attendus.",
    ),
    min_eval_cases: int = typer.Option(
        20,
        min=1,
        help="Minimum de cas dans le dataset d'évaluation ANRT réel.",
    ),
    min_bucket_accuracy: float = typer.Option(
        0.9,
        min=0,
        max=1,
        help="Seuil minimal d'accuracy bucket pour l'évaluation.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Sortie JSON machine-readable."),
) -> None:
    """Audite si les preuves locales suffisent pour déclarer le MVP ANRT atteint."""
    payload = _build_anrt_mvp_audit_payload(
        db=db,
        raw_dir=raw_dir,
        digest=digest,
        fixture_dir=fixture_dir,
        eval_dataset=eval_dataset,
        min_offers=min_offers,
        min_raw_list_files=min_raw_list_files,
        min_raw_detail_files=min_raw_detail_files,
        min_eval_cases=min_eval_cases,
        min_bucket_accuracy=min_bucket_accuracy,
    )
    _write_anrt_mvp_audit_report(output, payload)
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        table = Table(title="ANRT MVP audit")
        table.add_column("Gate")
        table.add_column("Statut")
        table.add_column("Détail")
        for gate in payload["gates"]:
            table.add_row(
                str(gate["name"]),
                "ok" if gate["passed"] else "manquant",
                str(gate["detail"]),
            )
        console.print(table)
        console.print(f"[bold]Rapport[/bold] {output}")
    if not payload["passed"]:
        raise typer.Exit(code=1)


@app.command("anrt-anonymize-fixtures")
def anrt_anonymize_fixtures(
    input_dir: Path = typer.Argument(..., help="Dossier de snapshots ANRT HTML source."),
    output_dir: Path = typer.Argument(..., help="Dossier de fixtures anonymisées à produire."),
) -> None:
    """Copie des snapshots ANRT HTML en masquant emails et téléphones évidents."""
    if not input_dir.exists() or not input_dir.is_dir():
        raise typer.BadParameter(f"Dossier source introuvable: {input_dir}")
    count = anonymize_fixture_tree(input_dir, output_dir)
    console.print(f"[green]OK[/green] {count} fichiers HTML anonymisés vers {output_dir}.")


@app.command("anrt-fixture-audit")
def anrt_fixture_audit(
    fixture_dir: Path = typer.Argument(..., help="Dossier fixture ANRT anonymisé à auditer."),
    json_output: bool = typer.Option(False, "--json", help="Sortie JSON machine-readable."),
) -> None:
    """Vérifie qu'un dossier fixture ANRT est complet et anonymisé."""
    if not fixture_dir.exists() or not fixture_dir.is_dir():
        raise typer.BadParameter(f"Dossier fixture introuvable: {fixture_dir}")
    audit = audit_anrt_fixture_tree(fixture_dir)
    if json_output:
        console.print(json.dumps(audit.to_dict(), ensure_ascii=False))
        return

    table = Table(title="ANRT fixture audit")
    table.add_column("Statut")
    table.add_column("Listes")
    table.add_column("Détails", justify="right")
    table.add_column("URLs découvertes", justify="right")
    table.add_column("Détails manquants", justify="right")
    table.add_column("Fuites contact", justify="right")
    table.add_row(
        "ok" if audit.ok else "à corriger",
        ", ".join(audit.list_pages_present) or "aucune",
        str(audit.detail_files),
        str(audit.discovered_urls),
        str(len(audit.missing_detail_urls)),
        str(len(audit.contact_leak_files)),
    )
    console.print(table)
    if audit.missing_list_pages:
        console.print(f"[yellow]Listes manquantes[/yellow] {', '.join(audit.missing_list_pages)}")
    if audit.missing_detail_urls:
        console.print(f"[yellow]Détails manquants[/yellow] {len(audit.missing_detail_urls)}")
    if audit.contact_leak_files:
        console.print(f"[red]Contacts non anonymisés[/red] {', '.join(audit.contact_leak_files)}")


@app.command("export")
def export_command(
    format: str = typer.Option("both", help="markdown, csv ou both."),
    output: Path | None = typer.Option(None, help="Chemin de sortie. Ignoré avec --format both."),
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    min_score: float = typer.Option(0.35, min=0, max=1, help="Score minimum à exporter."),
    only_new: bool = typer.Option(False, help="Exporter seulement les offres du dernier run."),
    include_excluded: bool = typer.Option(False, help="Inclure les exclusions notables."),
    source: SourceName | None = typer.Option(None, help="Filtrer par source normalisée."),
) -> None:
    """Exporte la shortlist locale en Markdown et/ou CSV."""
    connection = connect(db)
    since = latest_run_started_at(connection) if only_new else None
    source_filter = _source_filter_value(source)
    offers = shortlist(connection, min_score=min_score, since=since, source=source_filter)
    if include_excluded:
        offers.extend(excluded_offers(connection, since=since, source=source_filter))

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
    source: SourceName | None = typer.Option(None, help="Filtrer par source normalisée."),
) -> None:
    """Affiche les compteurs qualité du dernier état local."""
    connection = connect(db)
    counts = audit_counts(connection, source=_source_filter_value(source))
    if json_output:
        console.print(json.dumps(counts, ensure_ascii=False, default=str))
        return

    console.print(f"[bold]Offres en base[/bold] {counts['total']}")
    console.print(f"[bold]Indisponibles[/bold] {counts['unavailable']}")
    console.print(f"[bold]Disparues[/bold] {counts['missing']}")

    bucket_table = Table(title="Buckets")
    bucket_table.add_column("Bucket")
    bucket_table.add_column("Offres", justify="right")
    for bucket, count in dict(counts["by_bucket"]).items():
        bucket_table.add_row(str(bucket), str(count))
    console.print(bucket_table)

    source_table = Table(title="Sources")
    source_table.add_column("Source")
    source_table.add_column("Offres", justify="right")
    for source_name, count in dict(counts["by_source"]).items():
        source_table.add_row(str(source_name), str(count))
    console.print(source_table)

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
            f"#{run['id']} source={run.get('source', 'cnrs')} "
            f"kind={run.get('source_kind') or 'n/a'} profile={run['profile']} "
            f"pages={run['pages_fetched']} fetched={run['offers_fetched']} "
            f"errors={run['errors_count']} status={run.get('status_message') or 'ok'}"
        )

    top_table = Table(title="Top scores bruts")
    top_table.add_column("Source")
    top_table.add_column("Référence")
    top_table.add_column("Bucket")
    top_table.add_column("Score", justify="right")
    top_table.add_column("Titre")
    for row in list(counts["top_scores"]):
        score = row["ai_relevance_score"]
        top_table.add_row(
            str(row["source"]),
            str(row["reference"] or ""),
            str(row["target_bucket"]),
            f"{score:.2f}" if isinstance(score, float) else str(score),
            str(row["title"]),
        )
    console.print(top_table)


@app.command()
def changes(
    db: Path = typer.Option(Path("data/cnrs_jobs.sqlite"), help="Base SQLite locale."),
    source: SourceName | None = typer.Option(None, help="Filtrer par source normalisée."),
    limit: int = typer.Option(20, min=1, help="Nombre maximum d'offres modifiées à afficher."),
    json_output: bool = typer.Option(False, "--json", help="Sortie JSON machine-readable."),
) -> None:
    """Liste les offres dont le contenu brut a changé entre deux snapshots."""
    connection = connect(db)
    rows = changed_offers(connection, source=_source_filter_value(source), limit=limit)
    if json_output:
        console.print(json.dumps(rows, ensure_ascii=False, default=str))
        return

    table = Table(title="Offres modifiées")
    table.add_column("Source")
    table.add_column("Référence")
    table.add_column("Versions", justify="right")
    table.add_column("Dernier snapshot")
    table.add_column("Titre")
    for row in rows:
        table.add_row(
            str(row["source"]),
            str(row["reference"] or ""),
            str(row["versions"]),
            str(row["last_snapshot_at"] or ""),
            str(row["title"]),
        )
    console.print(table)


@app.command()
def eval(
    dataset: Path = typer.Option(
        Path("tests/fixtures/evaluation/offers.json"),
        help="Dataset annoté JSON.",
    ),
    source: SourceName | None = typer.Option(
        None,
        help="Dataset par défaut de la source: cnrs ou anrt.",
    ),
    min_bucket_accuracy: float = typer.Option(
        0.9,
        min=0,
        max=1,
        help="Seuil minimal de justesse bucket.",
    ),
) -> None:
    """Évalue la classification sur le dataset annoté local."""
    if source == SourceName.ANRT and dataset == Path("tests/fixtures/evaluation/offers.json"):
        dataset = Path("tests/fixtures/evaluation/anrt_offers.json")
    elif source in {SourceName.CNRS, SourceName.ALL}:
        dataset = Path("tests/fixtures/evaluation/offers.json")
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
    source: SourceName | None = typer.Option(None, help="Filtrer par source normalisée."),
) -> None:
    """Produit un digest Markdown daté, pensé pour une veille quotidienne."""
    connection = connect(db)
    since = latest_run_started_at(connection) if only_new else None
    source_filter = _source_filter_value(source)
    offers = shortlist(connection, min_score=min_score, since=since, source=source_filter)
    if include_excluded:
        offers.extend(excluded_offers(connection, since=since, source=source_filter))
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


def _fetch_parse_classify_store(
    *,
    source_adapter: SourceAdapter,
    offer_urls: list[str],
    no_cache: bool,
    classifier: ClassifierMode,
    llm_provider: LlmProvider | None,
    connection: object,
    run_id: int,
    progress_description: str,
) -> tuple[int, int]:
    offers_fetched = 0
    errors_count = 0
    for url in track(offer_urls, description=progress_description):
        try:
            detail_payload = source_adapter.fetch_detail(url, use_cache=not no_cache)
            content_hash = hashlib.sha256(detail_payload.encode("utf-8")).hexdigest()
            offer = source_adapter.parse_detail(detail_payload, url)
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
                raw_path=source_adapter.snapshot_path(url),
                run_id=run_id,
            )
            offers_fetched += 1
        except Exception as exc:  # noqa: BLE001
            errors_count += 1
            console.print(f"[red]Erreur offre[/red] {url}: {exc}")
    return offers_fetched, errors_count


def _filter_sitemap_urls_by_profile(urls: list[str], profile: SearchProfile) -> list[str]:
    if profile == SearchProfile.DOCTORANT:
        return [url for url in urls if "/Offres/Doctorant/" in url]
    return urls


def _source_filter_value(source: SourceName | None) -> str | None:
    if source is None or source == SourceName.ALL:
        return None
    return source.value


def _write_anrt_smoke_report(
    output: Path,
    *,
    db: Path,
    raw_dir: Path,
    digest_output: Path,
    result: dict[str, int],
    counts: dict[str, object],
    status: str,
    message: str | None,
    fixture_audit: dict[str, object] | None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    latest_run = counts.get("latest_run") or {}
    by_bucket = counts.get("by_bucket") or {}
    lines = [
        "# Validation ANRT/CIFRE",
        "",
        f"- Date : {datetime.now(UTC).isoformat()}",
        f"- Statut : {status}",
        f"- Base SQLite : {db}",
        f"- Raw snapshots : {raw_dir / 'anrt'}",
        f"- Digest : {digest_output}",
        f"- URLs découvertes : {result['discovered']}",
        f"- Offres fetchées : {result['fetched']}",
        f"- Erreurs détail : {result['errors']}",
        f"- Total en base ANRT : {counts.get('total', 0)}",
        f"- Buckets : {json.dumps(by_bucket, ensure_ascii=False, sort_keys=True)}",
    ]
    if isinstance(latest_run, Mapping):
        lines.extend(
            [
                f"- Dernier run : #{latest_run.get('id', 'n/a')}",
                f"- Pages liste : {latest_run.get('pages_fetched', 'n/a')}",
                f"- Status run : {latest_run.get('status_message') or 'ok'}",
            ]
        )
    if message:
        lines.append(f"- Message : {message}")
    if fixture_audit is not None:
        lines.extend(
            [
                "",
                "## Fixtures anonymisées",
                "",
                f"- Audit OK : {fixture_audit.get('ok')}",
                f"- Détails : {fixture_audit.get('detail_files')}",
                f"- URLs découvertes : {fixture_audit.get('discovered_urls')}",
                f"- Détails manquants : {len(fixture_audit.get('missing_detail_urls', []))}",
                f"- Fuites contact : {len(fixture_audit.get('contact_leak_files', []))}",
            ]
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_anrt_mvp_audit_payload(
    *,
    db: Path,
    raw_dir: Path,
    digest: Path,
    fixture_dir: Path | None,
    eval_dataset: Path | None,
    min_offers: int,
    min_raw_list_files: int,
    min_raw_detail_files: int,
    min_eval_cases: int,
    min_bucket_accuracy: float,
) -> dict[str, object]:
    db_exists = db.exists()
    latest_anrt_run: dict[str, object] | None = None
    counts: dict[str, object] = {
        "total": 0,
        "by_bucket": {},
    }
    kind_counts: dict[str, int] = {}
    if db_exists:
        connection = connect(db)
        counts = audit_counts(connection, source="anrt")
        latest_anrt_run = _latest_anrt_run(connection)
        kind_counts = _anrt_kind_counts(connection)

    list_files = len(list((raw_dir / "anrt" / "list").glob("*.html")))
    detail_files = len(list((raw_dir / "anrt" / "detail").glob("*.html")))
    by_bucket = dict(counts.get("by_bucket") or {})
    latest_status = latest_anrt_run.get("status_message") if latest_anrt_run else None
    discovered = int(latest_anrt_run.get("offers_discovered") or 0) if latest_anrt_run else 0
    fetched = int(latest_anrt_run.get("offers_fetched") or 0) if latest_anrt_run else 0
    errors = int(latest_anrt_run.get("errors_count") or 0) if latest_anrt_run else 0
    gates = [
        _mvp_gate("db_exists", db_exists, str(db)),
        _mvp_gate(
            "latest_anrt_run_finished",
            bool(latest_anrt_run and latest_anrt_run.get("finished_at")),
            f"run={latest_anrt_run.get('id') if latest_anrt_run else 'n/a'}",
        ),
        _mvp_gate(
            "latest_anrt_run_ok",
            bool(latest_anrt_run and latest_status in {None, "", "ok"} and errors == 0),
            f"status={latest_status or 'ok'}, errors={errors}",
        ),
        _mvp_gate(
            "discovered_minimum",
            discovered >= min_offers,
            f"{discovered}/{min_offers}",
        ),
        _mvp_gate("fetched_minimum", fetched >= min_offers, f"{fetched}/{min_offers}"),
        _mvp_gate(
            "both_origins_present",
            kind_counts.get("entreprise", 0) > 0 and kind_counts.get("laboratoire", 0) > 0,
            json.dumps(kind_counts, ensure_ascii=False, sort_keys=True),
        ),
        _mvp_gate(
            "has_primary_target",
            int(by_bucket.get("primary_target") or 0) > 0,
            json.dumps(by_bucket, ensure_ascii=False, sort_keys=True),
        ),
        _mvp_gate(
            "digest_exists",
            digest.exists() and digest.stat().st_size > 0,
            str(digest),
        ),
        _mvp_gate(
            "raw_list_snapshots",
            list_files >= min_raw_list_files,
            f"{list_files}/{min_raw_list_files}",
        ),
        _mvp_gate(
            "raw_detail_snapshots",
            detail_files >= min_raw_detail_files,
            f"{detail_files}/{min_raw_detail_files}",
        ),
    ]
    fixture_summary = _anrt_fixture_gate_summary(fixture_dir, min_offers=min_offers)
    gates.extend(fixture_summary["gates"])
    evaluation_summary = _anrt_evaluation_gate_summary(
        eval_dataset,
        min_eval_cases=min_eval_cases,
        min_bucket_accuracy=min_bucket_accuracy,
    )
    gates.extend(evaluation_summary["gates"])
    return {
        "passed": all(bool(gate["passed"]) for gate in gates),
        "db": str(db),
        "raw_dir": str(raw_dir),
        "digest": str(digest),
        "fixture_dir": str(fixture_dir) if fixture_dir else None,
        "eval_dataset": str(eval_dataset) if eval_dataset else None,
        "latest_anrt_run": latest_anrt_run,
        "counts": counts,
        "kind_counts": kind_counts,
        "raw_files": {"list": list_files, "detail": detail_files},
        "fixture_audit": fixture_summary["audit"],
        "evaluation": evaluation_summary["summary"],
        "gates": gates,
    }


def _mvp_gate(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"name": name, "passed": passed, "detail": detail}


def _latest_anrt_run(connection: object) -> dict[str, object] | None:
    row = connection.execute(
        """
        SELECT *
        FROM runs
        WHERE source = 'anrt'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def _anrt_kind_counts(connection: object) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT source_specific
        FROM offers
        WHERE source = 'anrt'
          AND unavailable = 0
          AND last_seen_status != 'missing'
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        try:
            data = json.loads(row["source_specific"] or "{}")
        except json.JSONDecodeError:
            continue
        kind = data.get("anrt_kind")
        if isinstance(kind, str) and kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _anrt_fixture_gate_summary(
    fixture_dir: Path | None,
    *,
    min_offers: int,
) -> dict[str, object]:
    if fixture_dir is None:
        return {
            "audit": None,
            "gates": [
                _mvp_gate("anonymized_fixtures_provided", False, "fixture_dir missing"),
            ],
        }
    if not fixture_dir.exists():
        return {
            "audit": None,
            "gates": [
                _mvp_gate("anonymized_fixtures_provided", False, str(fixture_dir)),
            ],
        }
    audit = audit_anrt_fixture_tree(fixture_dir)
    return {
        "audit": audit.to_dict(),
        "gates": [
            _mvp_gate("anonymized_fixtures_ok", audit.ok, str(fixture_dir)),
            _mvp_gate(
                "anonymized_fixture_detail_minimum",
                audit.detail_files >= min_offers,
                f"{audit.detail_files}/{min_offers}",
            ),
        ],
    }


def _anrt_evaluation_gate_summary(
    eval_dataset: Path | None,
    *,
    min_eval_cases: int,
    min_bucket_accuracy: float,
) -> dict[str, object]:
    if eval_dataset is None:
        return {
            "summary": None,
            "gates": [_mvp_gate("evaluation_dataset_provided", False, "eval_dataset missing")],
        }
    if not eval_dataset.exists():
        return {
            "summary": None,
            "gates": [_mvp_gate("evaluation_dataset_provided", False, str(eval_dataset))],
        }
    summary = run_evaluation(load_evaluation_cases(eval_dataset))
    summary_payload = summary.model_dump(mode="json", exclude={"results"})
    return {
        "summary": summary_payload,
        "gates": [
            _mvp_gate(
                "evaluation_case_minimum",
                summary.total >= min_eval_cases,
                f"{summary.total}/{min_eval_cases}",
            ),
            _mvp_gate(
                "evaluation_bucket_accuracy",
                summary.bucket_accuracy >= min_bucket_accuracy,
                f"{summary.bucket_accuracy:.3f}/{min_bucket_accuracy:.3f}",
            ),
            _mvp_gate(
                "evaluation_no_false_targets",
                summary.false_targets == 0,
                str(summary.false_targets),
            ),
            _mvp_gate(
                "evaluation_no_missed_targets",
                summary.missed_targets == 0,
                str(summary.missed_targets),
            ),
        ],
    }


def _write_anrt_mvp_audit_report(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Audit MVP ANRT/CIFRE",
        "",
        f"- Date : {datetime.now(UTC).isoformat()}",
        f"- Statut : {'ok' if payload['passed'] else 'incomplet'}",
        f"- Base SQLite : {payload['db']}",
        f"- Raw dir : {payload['raw_dir']}",
        f"- Digest : {payload['digest']}",
        f"- Fixture dir : {payload['fixture_dir'] or 'n/a'}",
        f"- Dataset évaluation : {payload['eval_dataset'] or 'n/a'}",
        "",
        "## Gates",
        "",
        "| Gate | Statut | Détail |",
        "| --- | --- | --- |",
    ]
    for gate in payload["gates"]:
        status = "ok" if gate["passed"] else "manquant"
        detail = str(gate["detail"]).replace("|", "\\|")
        lines.append(f"| {gate['name']} | {status} | {detail} |")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_sync_playwright() -> object:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright n'est pas installé. Lance avec "
            "`uv run --with playwright cnrs-jobs anrt-login`, après "
            "`uv run --with playwright playwright install chromium` si Chromium manque."
        ) from exc
    return sync_playwright


def _verify_anrt_browser_session(page: object, *, timeout_seconds: int) -> None:
    targets = [
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/entreprise",
        "https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/laboratoire",
    ]
    for target in targets:
        page.goto(target, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        html = page.content()
        if is_logged_out_page(html, page.url):
            raise typer.BadParameter(
                "La session ANRT semble expirée ou non connectée après login."
            )
