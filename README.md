# CNRS Job Watcher

Veilleur local d'offres publiques CNRS orienté IA/ML. Le pipeline récupère les pages publiques
`emploi.cnrs.fr`, extrait les champs utiles, applique un filtrage dur, score la pertinence IA/ML
et exporte une shortlist exploitable en Markdown et CSV.

## Stack

- Python 3.12+
- `httpx` pour le fetch HTTP
- `BeautifulSoup` pour le parsing HTML
- `pydantic` pour les modèles validés
- SQLite pour l'historique local
- `typer` + `rich` pour le CLI
- `pytest` + fixtures HTML pour protéger les parseurs

## Usage

```bash
uv sync
uv run cnrs-jobs crawl
uv run cnrs-jobs crawl --profile doctorant --limit-offers 25
uv run cnrs-jobs crawl --classifier hybrid --limit-offers 10
uv run cnrs-jobs crawl --source all --classifier hybrid
uv run cnrs-jobs anrt-session-check --anrt-session-file data/auth/anrt-cookies.json
uv run cnrs-jobs anrt-session-check --anrt-fixture-dir tests/fixtures/anrt
uv run cnrs-jobs crawl --source anrt --anrt-kind entreprise --anrt-session-file data/auth/anrt-cookies.json
uv run cnrs-jobs crawl --source anrt --anrt-fixture-dir tests/fixtures/anrt
uv run cnrs-jobs export
```

Sorties par défaut :

- `data/cnrs_jobs.sqlite`
- `data/raw/*.html`
- `data/digests/YYYY-MM-DD.md`
- `cnrs_ia_jobs.md`
- `cnrs_ia_jobs.csv`

## Commandes

```bash
uv run cnrs-jobs crawl
uv run cnrs-jobs crawl --source cnrs
uv run cnrs-jobs crawl --source all --classifier hybrid
uv run cnrs-jobs anrt-session-check --anrt-session-file data/auth/anrt-cookies.json
uv run cnrs-jobs anrt-session-check --anrt-fixture-dir tests/fixtures/anrt
uv run cnrs-jobs crawl --source anrt --anrt-kind entreprise --anrt-session-file data/auth/anrt-cookies.json
uv run cnrs-jobs crawl --source anrt --anrt-kind laboratoire --anrt-session-file data/auth/anrt-cookies.json
uv run cnrs-jobs crawl --source anrt --anrt-fixture-dir tests/fixtures/anrt
uv run cnrs-jobs anrt-anonymize-fixtures data/raw/anrt tests/fixtures/anrt_real_anonymized
uv run cnrs-jobs crawl --discovery list --limit-pages 13
uv run cnrs-jobs profile-audit --limit-pages 2
uv run cnrs-jobs export --format markdown --output cnrs_ia_jobs.md
uv run cnrs-jobs export --format csv --output cnrs_ia_jobs.csv
uv run cnrs-jobs export --source cnrs
uv run cnrs-jobs export --source all --format markdown --output thesis_ia_jobs.md
uv run cnrs-jobs audit
uv run cnrs-jobs audit --json
uv run cnrs-jobs audit --source all
uv run cnrs-jobs changes --source all
uv run cnrs-jobs changes --source anrt --json
uv run cnrs-jobs digest
uv run cnrs-jobs digest --source all
uv run cnrs-jobs digest --include-excluded
uv run cnrs-jobs eval
uv run cnrs-jobs eval --source anrt
```

Le crawler respecte les zones publiques du site et limite volontairement le rythme des requêtes.
L'IA générative n'est pas utilisée comme crawler : elle doit rester une étape de classification
sémantique optionnelle après extraction.

La découverte par défaut utilise le sitemap public CNRS des offres, puis récupère toutes les URLs
`/Offres/Doctorant/` et `/Offres/CDD/`. C'est la source robuste pour éviter les faux négatifs de
pagination. `--discovery list` conserve l'ancien parcours par pages de résultats uniquement comme
fallback/audit. Le profil `doctorant` filtre les URLs sitemap avant téléchargement ; les autres
profils larges classent après parsing des pages détail.

Le classifieur par défaut est `rules`, sans appel externe. Le mode `hybrid` utilise
`OPENAI_API_KEY` quand elle est disponible, valide la réponse par JSON Schema strict, puis met en
cache la décision par hash HTML de l'offre. Sans clé API, il retombe sur les règles locales.

`--include-excluded` ajoute les exclusions notables au Markdown/CSV pour auditer le bruit proche du
seuil sans modifier la shortlist par défaut. Un exemple cron local est disponible dans
`docs/local_automation.md`.

Les crawls complets marquent aussi les offres d'une source comme `missing` lorsqu'elles ne sont plus
retrouvées. Elles restent dans l'historique SQLite, mais ne sortent plus dans la shortlist/digest par
défaut.
`cnrs-jobs changes` liste les offres dont le hash de snapshot a changé entre deux fetchs.

Le modèle est prêt pour plusieurs portails : `JobOffer.source`, `source_specific` et l'interface
`SourceAdapter` permettent d'ajouter une source sans modifier la classification centrale. CNRS reste
la source publique stable. ANRT/CIFRE est disponible comme source authentifiée préparatoire :
`--source anrt` sait refuser explicitement une session absente ou expirée, parser des pages
entreprise/laboratoire et produire des offres normalisées, mais un audit avec compte connecté reste
nécessaire avant automatisation quotidienne.

`--source all` lance CNRS puis ANRT. Si la session ANRT est absente ou expirée, CNRS continue et le
run signale l'authentification ANRT manquante. Un run `--source anrt` seul échoue avec code `2` dans
ce cas, pour éviter de confondre une session invalide avec une absence d'offres. Pour `export`,
`digest` et `audit`, `--source all` signifie "ne pas filtrer par source".

`--anrt-fixture-dir` remplace l'accès réseau ANRT par un dossier local anonymisé contenant
`list/entreprise.html`, `list/laboratoire.html` et les détails sous `detail/`. C'est le mode de
debugging recommandé avant de modifier les sélecteurs. `anrt-anonymize-fixtures` aide à produire des
fixtures committables depuis des snapshots locaux en masquant emails et téléphones évidents.

## Development contract

Avant de livrer une modification du pipeline, lancer au minimum :

```bash
uv run ruff check .
uv run pytest
```

Pour valider le comportement réel CNRS sur un petit échantillon :

```bash
uv run cnrs-jobs crawl --limit-offers 5 \
  --db /tmp/cnrs_smoke.sqlite \
  --raw-dir /tmp/cnrs_smoke_raw \
  --max-error-rate 0.2 \
  --no-cache
uv run cnrs-jobs export --db /tmp/cnrs_smoke.sqlite --min-score 0.25
uv run cnrs-jobs audit --db /tmp/cnrs_smoke.sqlite
uv run cnrs-jobs digest --db /tmp/cnrs_smoke.sqlite --output /tmp/cnrs_digest.md
uv run cnrs-jobs eval
uv run cnrs-jobs eval --source anrt
uv run cnrs-jobs crawl --source anrt --anrt-fixture-dir tests/fixtures/anrt \
  --db /tmp/anrt_fixture.sqlite --raw-dir /tmp/anrt_fixture_raw --no-cache
```

Pour valider la couverture sitemap des thèses ratées par la pagination :

```bash
uv run cnrs-jobs crawl --discovery sitemap --profile doctorant --limit-offers 165 \
  --db /tmp/cnrs_sitemap_refs.sqlite \
  --raw-dir /tmp/cnrs_sitemap_refs_raw
```

Les bases SQLite, snapshots HTML et exports générés restent hors Git.

`cnrs-jobs eval` utilise un dataset annoté de 31 cas couvrant thèses IA, CDD BAC+5,
adjacents à relire, postdocs, stages/apprentissages/CDI et bruit administratif. Le fichier
`tests/fixtures/evaluation/observed_offers.json` ajoute 40 offres CNRS réellement crawlées le
2026-07-06 et auto-étiquetées comme baseline de régression. Ensemble, ces jeux bloquent les
régressions critiques et suivent précision/rappel sur les buckets cibles.
`cnrs-jobs eval --source anrt` utilise un dataset synthétique ANRT/CIFRE couvrant sujets IA forts,
offres biomédicales avec signaux ML dans le détail, data adjacente et CIFRE hors IA.
