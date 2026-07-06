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
uv run cnrs-jobs crawl --limit-pages 2 --limit-offers 25
uv run cnrs-jobs crawl --profile doctorant --limit-pages 2
uv run cnrs-jobs crawl --classifier hybrid --limit-pages 1 --limit-offers 10
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
uv run cnrs-jobs crawl --limit-pages 13
uv run cnrs-jobs profile-audit --limit-pages 2
uv run cnrs-jobs export --format markdown --output cnrs_ia_jobs.md
uv run cnrs-jobs export --format csv --output cnrs_ia_jobs.csv
uv run cnrs-jobs export --source cnrs
uv run cnrs-jobs audit
uv run cnrs-jobs audit --json
uv run cnrs-jobs digest
uv run cnrs-jobs digest --include-excluded
uv run cnrs-jobs eval
```

Le crawler respecte les zones publiques du site et limite volontairement le rythme des requêtes.
L'IA générative n'est pas utilisée comme crawler : elle doit rester une étape de classification
sémantique optionnelle après extraction.

Les profils `doctorant`, `cdd_bac5` et `ai_audit` filtrent les cartes de résultats avant
téléchargement des pages détail. Le formulaire CNRS expose bien des valeurs serveur comme
`DOCTOR`, `ITCDD` et `CHRCDD`, mais le POST filtré dépend du comportement ASP.NET/JavaScript ;
le crawler conserve donc le parcours public général comme source robuste, puis applique ces profils
localement.

Le classifieur par défaut est `rules`, sans appel externe. Le mode `hybrid` utilise
`OPENAI_API_KEY` quand elle est disponible, valide la réponse par JSON Schema strict, puis met en
cache la décision par hash HTML de l'offre. Sans clé API, il retombe sur les règles locales.

`--include-excluded` ajoute les exclusions notables au Markdown/CSV pour auditer le bruit proche du
seuil sans modifier la shortlist par défaut. Un exemple cron local est disponible dans
`docs/local_automation.md`.

Le modèle est prêt pour plusieurs portails : `JobOffer.source`, `source_specific` et l'interface
`SourceAdapter` permettent d'ajouter une source sans modifier la classification centrale. CNRS reste
la seule source active pour l'instant.

## Development contract

Avant de livrer une modification du pipeline, lancer au minimum :

```bash
uv run ruff check .
uv run pytest
```

Pour valider le comportement réel CNRS sur un petit échantillon :

```bash
uv run cnrs-jobs crawl --limit-pages 1 --limit-offers 5 \
  --db /tmp/cnrs_smoke.sqlite \
  --raw-dir /tmp/cnrs_smoke_raw \
  --max-error-rate 0.2 \
  --no-cache
uv run cnrs-jobs export --db /tmp/cnrs_smoke.sqlite --min-score 0.25
uv run cnrs-jobs audit --db /tmp/cnrs_smoke.sqlite
uv run cnrs-jobs digest --db /tmp/cnrs_smoke.sqlite --output /tmp/cnrs_digest.md
uv run cnrs-jobs eval
```

Les bases SQLite, snapshots HTML et exports générés restent hors Git.

`cnrs-jobs eval` utilise un dataset annoté de 31 cas couvrant thèses IA, CDD BAC+5,
adjacents à relire, postdocs, stages/apprentissages/CDI et bruit administratif. Le fichier
`tests/fixtures/evaluation/observed_offers.json` ajoute 40 offres CNRS réellement crawlées le
2026-07-06 et auto-étiquetées comme baseline de régression. Ensemble, ces jeux bloquent les
régressions critiques et suivent précision/rappel sur les buckets cibles.
